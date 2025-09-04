#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <signal.h>
#include <pthread.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <poll.h>
#include <rdma/rdma_cma.h>
#include <infiniband/verbs.h>
/*-------------------------------------------------------------------------*/
#include "message.h"
#include "prometheus.h"
/*-------------------------------------------------------------------------*/
#define MSG_SIZE        4096
#define RECV_DEPTH      64      // 연결별로 미리 등록할 RECV 수
#define MAX_SEND_WR     128
#define MAX_RECV_WR     RECV_DEPTH
#define MAX_SGE         1
#define BACKLOG         64
/*-------------------------------------------------------------------------*/
metrics_t *m;
/*-------------------------------------------------------------------------*/
static volatile sig_atomic_t g_stop = 0;
static void on_sigint(int signo) { (void)signo; g_stop = 1; }
/*-------------------------------------------------------------------------*/
static void die(const char *msg) {
    perror(msg);
    exit(EXIT_FAILURE);
}
/*-------------------------------------------------------------------------*/
static void print_metrics_t(void) {
	printf("[SERVER] received metrics:\n");
	printf("  QoS: latency=%.2f, FPS=%d\n", m->qr.latency, m->qr.FPS);
    printf("  App: id=%d, res=%dx%d, framerate=%d, codec=%d\n",
           m->ai.app_id,
           m->af.input_res_width,
           m->af.input_res_height,
           m->af.input_framerate,
           m->af.input_codec);
    printf("  GPU: id=%d, enc_sessions=%d, enc_util=%.1f%%, dec_util=%.1f%%\n",
           m->gr.gpu_id, m->gr.enc_sessions,
           m->gr.enc_util, m->gr.dec_util);
    printf("  Node: id=%d, CPU_util=%.1f%%, isGPU=%d, pod_num=%d\n",
           m->ni.node_id, m->ni.cpu_utilization,
           m->ni.isGPU, m->ni.pod_number);
    printf("  LB: result=%d\n", m->ls.result);
    printf("  Perf: session_id=%d, pid=%d, avg_latency=%.2f, FPS=%d\n",
           m->pi.session_id, m->pi.pid,
           m->pi.avg_latency, m->pi.FPS);
	printf("\n");
}
/*-------------------------------------------------------------------------*/
struct conn_ctx {
    struct rdma_cm_id *id;
    struct ibv_pd *pd;
    struct ibv_comp_channel *comp_ch;
    struct ibv_cq *cq;
    struct ibv_qp *qp;

    // 수신 버퍼 풀 (연속 메모리 + 단일 MR)
    uint8_t *recv_region;           // 크기: RECV_DEPTH * MSG_SIZE
    struct ibv_mr *recv_mr;

    int recv_depth;
    pthread_t thr;
    int running;

    // 클라이언트 식별용
    char peer_ip[64];
    uint16_t peer_port;
};
/*-------------------------------------------------------------------------*/
static int post_one_recv(struct conn_ctx *c, int idx) {
    struct ibv_sge sge = {
        .addr   = (uintptr_t)(c->recv_region + (size_t)idx * MSG_SIZE),
        .length = MSG_SIZE,
        .lkey   = c->recv_mr->lkey,
    };
    struct ibv_recv_wr wr = {0}, *bad = NULL;
    wr.wr_id = (uintptr_t)idx;  // 완료 시 어떤 버퍼인지 식별
    wr.sg_list = &sge;
    wr.num_sge = 1;
    return ibv_post_recv(c->qp, &wr, &bad);
}
/*-------------------------------------------------------------------------*/
static int prepost_recvs(struct conn_ctx *c) {
    for (int i = 0; i < c->recv_depth; ++i) {
        if (post_one_recv(c, i)) return -1;
    }
    return 0;
}
/*-------------------------------------------------------------------------*/
static void *conn_thread(void *arg) {
    struct conn_ctx *c = (struct conn_ctx *)arg;

    // comp channel을 non-blocking으로 설정하여 종료 신호에 즉시 반응
    int flags = fcntl(c->comp_ch->fd, F_GETFL, 0);
    fcntl(c->comp_ch->fd, F_SETFL, flags | O_NONBLOCK);

    if (ibv_req_notify_cq(c->cq, 0)) {
        perror("ibv_req_notify_cq");
        goto out;
    }

    printf("[SERVER] connection started from %s:%u\n", c->peer_ip, c->peer_port);
    fflush(stdout);

    c->running = 1;
    while (c->running && !g_stop) {
        struct pollfd pfd = { .fd = c->comp_ch->fd, .events = POLLIN };
        int pr = poll(&pfd, 1, 500); // 500ms 주기로 깨어나 종료 플래그 확인
        if (pr < 0) {
            if (errno == EINTR) continue;
            perror("poll");
            break;
        }
        if (pr == 0) {
            // timeout: 종료 플래그 확인 후 계속
            continue;
        }
        if (pfd.revents & POLLIN) {
            struct ibv_cq *ev_cq = NULL;
            void *ev_ctx = NULL;
            int rc = ibv_get_cq_event(c->comp_ch, &ev_cq, &ev_ctx);
            if (rc) {
                if (errno == EAGAIN) continue; // non-blocking: 이벤트 없음
                if (errno == EINTR) continue;
                perror("ibv_get_cq_event");
                break;
            }
            ibv_ack_cq_events(ev_cq, 1);
            if (ibv_req_notify_cq(c->cq, 0)) {
                perror("ibv_req_notify_cq");
                break;
            }

            struct ibv_wc wc[32];
            int n;
            while ((n = ibv_poll_cq(c->cq, 32, wc)) > 0) {
                for (int i = 0; i < n; ++i) {
                    if (wc[i].status != IBV_WC_SUCCESS) {
                        fprintf(stderr, "[SERVER] WC error: status=%d, opcode=%d", wc[i].status, wc[i].opcode);
                        c->running = 0;
                        break;
                    }
                    if (wc[i].opcode == IBV_WC_RECV) {
                        int idx = (int)wc[i].wr_id;
                        uint8_t *buf = c->recv_region + (size_t)idx * MSG_SIZE;
						m = (metrics_t*)buf;
                        print_metrics_t();
						size_t byte_len = wc[i].byte_len;

						if (byte_len >= sizeof(metrics_t)) {
							metrics_t mlocal;
							memcpy(&mlocal, buf, sizeof(metrics_t));
							metrics_store_update(&mlocal);
						} else {
							printf("Invalid data\n");
						}

						fflush(stdout);

                        if (post_one_recv(c, idx)) {
                            perror("ibv_post_recv");
                            c->running = 0;
                            break;
                        }
                    }
                }
            }
            if (n < 0) {
                perror("ibv_poll_cq");
                break;
            }
        }
    }

out:
    // 여기서는 disconnect를 호출하지 않는다. CM DISCONNECTED 이벤트에서 정리한다.
    return NULL;
}
/*-------------------------------------------------------------------------*/
static struct conn_ctx *build_connection(struct rdma_cm_id *id) {
    struct conn_ctx *c = calloc(1, sizeof(*c));
    if (!c) return NULL;
    c->id = id;
    c->recv_depth = RECV_DEPTH;

    // 피어 주소 문자열화
    struct sockaddr *psa = rdma_get_peer_addr(id);
    if (psa && psa->sa_family == AF_INET) {
        struct sockaddr_in *sin = (struct sockaddr_in *)psa;
        inet_ntop(AF_INET, &sin->sin_addr, c->peer_ip, sizeof(c->peer_ip));
        c->peer_port = ntohs(sin->sin_port);
    } else {
        snprintf(c->peer_ip, sizeof(c->peer_ip), "?");
        c->peer_port = 0;
    }

    c->pd = ibv_alloc_pd(id->verbs);
    if (!c->pd) goto err;

    c->comp_ch = ibv_create_comp_channel(id->verbs);
    if (!c->comp_ch) goto err;

    c->cq = ibv_create_cq(id->verbs, MAX_SEND_WR + MAX_RECV_WR, NULL, c->comp_ch, 0);
    if (!c->cq) goto err;

    struct ibv_qp_init_attr qp_attr = {0};
    qp_attr.qp_type = IBV_QPT_RC;
    qp_attr.sq_sig_all = 1;
    qp_attr.send_cq = c->cq;
    qp_attr.recv_cq = c->cq;
    qp_attr.cap.max_send_wr = MAX_SEND_WR;
    qp_attr.cap.max_recv_wr = MAX_RECV_WR;
    qp_attr.cap.max_send_sge = MAX_SGE;
    qp_attr.cap.max_recv_sge = MAX_SGE;

    if (rdma_create_qp(id, c->pd, &qp_attr)) goto err;
    c->qp = id->qp;

    // 수신 영역: 연속 공간 + 단일 MR
    size_t region_sz = (size_t)c->recv_depth * MSG_SIZE;
    c->recv_region = aligned_alloc(4096, (region_sz + 4095) & ~((size_t)4095));
    if (!c->recv_region) goto err;
    c->recv_mr = ibv_reg_mr(c->pd, c->recv_region, region_sz, IBV_ACCESS_LOCAL_WRITE);
    if (!c->recv_mr) goto err;

    if (prepost_recvs(c)) goto err;

    return c;
err:
    perror("build_connection");
    if (c) {
        if (c->qp) rdma_destroy_qp(c->id);
        if (c->cq) ibv_destroy_cq(c->cq);
        if (c->comp_ch) ibv_destroy_comp_channel(c->comp_ch);
        if (c->recv_mr) ibv_dereg_mr(c->recv_mr);
        free(c->recv_region);
        if (c->pd) ibv_dealloc_pd(c->pd);
        free(c);
    }
    return NULL;
}
/*-------------------------------------------------------------------------*/
static void destroy_connection(struct conn_ctx *c) {
    if (!c) return;
    // QP/ID 정리는 DISCONNECTED 이벤트에서 순서대로 수행됨
    if (c->id->qp) rdma_destroy_qp(c->id);
    if (c->cq) ibv_destroy_cq(c->cq);
    if (c->comp_ch) ibv_destroy_comp_channel(c->comp_ch);
    if (c->recv_mr) ibv_dereg_mr(c->recv_mr);
    free(c->recv_region);
    if (c->pd) ibv_dealloc_pd(c->pd);
    free(c);
}
/*-------------------------------------------------------------------------*/
int main(int argc, char **argv) {
    uint16_t port = 7471;
    int opt;
    while ((opt = getopt(argc, argv, "p:")) != -1) {
        switch (opt) {
        case 'p': port = (uint16_t)atoi(optarg); break;
        default:
            fprintf(stderr, "Usage: %s [-p port]\n", argv[0]);
            return EXIT_FAILURE;
        }
    }

    signal(SIGINT, on_sigint);

	static pthread_t metrics_thr;
	static int metrics_port = 9123;
	metrics_store_init(BACKLOG);
	if (pthread_create(&metrics_thr, NULL, metrics_http_server, &metrics_port)) {
		perror("pthread_create(metrics_http_server)");
	}

    struct rdma_event_channel *ec = rdma_create_event_channel();
    if (!ec) die("rdma_create_event_channel");

    struct rdma_cm_id *listener = NULL;
    if (rdma_create_id(ec, &listener, NULL, RDMA_PS_TCP)) die("rdma_create_id");

    struct sockaddr_in addr = {0};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    addr.sin_addr.s_addr = INADDR_ANY;

    if (rdma_bind_addr(listener, (struct sockaddr *)&addr)) die("rdma_bind_addr");
    if (rdma_listen(listener, BACKLOG)) die("rdma_listen");

    printf("[SERVER] listening on port %u (BACKLOG=%d)\n", port, BACKLOG);
    fflush(stdout);

    while (!g_stop) {
        struct rdma_cm_event *event = NULL;
        if (rdma_get_cm_event(ec, &event)) {
            if (errno == EINTR) continue;
            perror("rdma_get_cm_event");
            break;
        }

        struct rdma_cm_event ev = *event; // 복사
        rdma_ack_cm_event(event);

        switch (ev.event) {
        case RDMA_CM_EVENT_CONNECT_REQUEST: {
            struct conn_ctx *c = build_connection(ev.id);
            if (!c) {
                fprintf(stderr, "[SERVER] failed to build connection resources\n");
                rdma_reject(ev.id, NULL, 0);
                continue;
            }
            struct rdma_conn_param cp = {0};
            cp.initiator_depth = 1;
            cp.responder_resources = 1;
            cp.rnr_retry_count = 7; // infinite retry

            if (rdma_accept(ev.id, &cp)) {
                perror("rdma_accept");
                destroy_connection(c);
                continue;
            }
            // 연결 컨텍스트를 id->context에 보관
            ev.id->context = c;
            break; }

        case RDMA_CM_EVENT_ESTABLISHED: {
            struct conn_ctx *c = (struct conn_ctx *)ev.id->context;
            if (!c) {
                fprintf(stderr, "[SERVER] ESTABLISHED with null context\n");
                rdma_disconnect(ev.id);
                break;
            }
            if (pthread_create(&c->thr, NULL, conn_thread, c)) {
                perror("pthread_create");
                rdma_disconnect(ev.id);
            }
            break; }

        case RDMA_CM_EVENT_DISCONNECTED: {
            struct conn_ctx *c = (struct conn_ctx *)ev.id->context;
            if (c) {
                c->running = 0;
                // 스레드 조인 (이미 종료되었거나 종료 중)
                if (c->thr) pthread_join(c->thr, NULL);
                rdma_destroy_id(c->id);
                destroy_connection(c);
            } else {
                rdma_destroy_id(ev.id);
            }
            break; }

        default:
            fprintf(stderr, "[SERVER] CM event %d\n", ev.event);
            break;
        }
    }

    rdma_destroy_id(listener);
    rdma_destroy_event_channel(ec);

    printf("[SERVER] exiting\n");
    return 0;
}
/*-------------------------------------------------------------------------*/
