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
#include <rdma/rdma_cma.h>
#include <infiniband/verbs.h>
#include <stdatomic.h>
/*-------------------------------------------------------------------------*/
#include "message.h"
#include "prometheus.h"
/*-------------------------------------------------------------------------*/
/* RDMA shared resources */
static struct ibv_pd           *g_pd  = NULL;
static struct ibv_comp_channel *g_cc  = NULL;
static struct ibv_cq           *g_cq  = NULL;
static struct ibv_srq          *g_srq = NULL;
static pthread_t                g_poller_thr;
static volatile sig_atomic_t    g_stop_poll = 0;
/*-------------------------------------------------------------------------*/
#define MSG_SIZE     4096
#define BACKLOG      64

/* SRQ receive buffer pool */
#define SRQ_MSG_SIZE MSG_SIZE
//#define SRQ_DEPTH    16384
#define SRQ_DEPTH    1024

struct recv_buf {
    uint8_t data[SRQ_MSG_SIZE];
};
static struct recv_buf *g_rbuf_pool = NULL;
static struct ibv_mr   *g_rbuf_mr   = NULL;
/*-------------------------------------------------------------------------*/
static int g_inited = 0;
/*-------------------------------------------------------------------------*/
/* QP number → connection context mapping */
#define QP_MAP_SIZE 65536

struct conn_ctx {
    struct rdma_cm_id *id;
    struct ibv_qp     *qp;
    int                running;
    char               peer_ip[64];
    uint16_t           peer_port;
};

static struct conn_ctx *g_qp_map[QP_MAP_SIZE];
static pthread_mutex_t  g_qp_mu = PTHREAD_MUTEX_INITIALIZER;
/*-------------------------------------------------------------------------*/
static volatile sig_atomic_t g_stop = 0;
static void on_sigint(int signo) { (void)signo; g_stop = 1; }
/*-------------------------------------------------------------------------*/
static void die(const char *msg) { 
	perror(msg); exit(EXIT_FAILURE); 
}
/*-------------------------------------------------------------------------*/
#if 1
static void print_metrics_t(const metrics_t *m, const char *peer_ip, uint16_t peer_port) {
    printf("[SERVER] received metrics from %s:%u:\n", peer_ip, peer_port);
    printf("  QoS: latency=%.2f, FPS=%d\n", m->qr.latency, m->qr.FPS);
    printf("  App: id=%d, res=%dx%d, framerate=%d, codec=%d\n",
           m->ai.app_id, m->af.input_res_width, m->af.input_res_height,
           m->af.input_framerate, m->af.input_codec);
    printf("  GPU: id=%d, enc_sessions=%d, enc_util=%.1f%%, dec_util=%.1f%%\n",
           m->gr.gpu_id, m->gr.enc_sessions, m->gr.enc_util, m->gr.dec_util);
    printf("  Node: id=%d, CPU_util=%.1f%%, isGPU=%d, pod_num=%d\n",
           m->ni.node_id, m->ni.cpu_utilization, m->ni.isGPU, m->ni.pod_number);
    printf("  LB: result=%d\n", m->ls.result);
    printf("  Perf: session_id=%d, pid=%d, avg_latency=%.2f, FPS=%d\n",
           m->pi.session_id, m->pi.pid, m->pi.avg_latency, m->pi.FPS);
    printf("\n");
}
#endif
/*-------------------------------------------------------------------------*/
/* Initialize shared RDMA resources */
static void server_resources_init(struct ibv_context *verbs)
{
    g_pd = ibv_alloc_pd(verbs);
    if (!g_pd) die("ibv_alloc_pd");

    g_cc = ibv_create_comp_channel(verbs);
    if (!g_cc) die("ibv_create_comp_channel");

    /* shared CQ */
    g_cq = ibv_create_cq(verbs, 8192, NULL, g_cc, 0);
    if (!g_cq) die("ibv_create_cq");

    /* SRQ creation */
    struct ibv_srq_init_attr sattr = {0};
    sattr.attr.max_wr  = SRQ_DEPTH;
    sattr.attr.max_sge = 1;
    g_srq = ibv_create_srq(g_pd, &sattr);
    if (!g_srq) die("ibv_create_srq");

    /* register receive buffer pool + MR (4096 align) */
    void *tmp = NULL;
    size_t pool_sz = sizeof(struct recv_buf) * SRQ_DEPTH;
    if (posix_memalign(&tmp, 4096, pool_sz) != 0 || tmp == NULL) {
        die("posix_memalign g_rbuf_pool");
    }
    g_rbuf_pool = (struct recv_buf *)tmp;

    g_rbuf_mr = ibv_reg_mr(g_pd, g_rbuf_pool, pool_sz, IBV_ACCESS_LOCAL_WRITE);
    if (!g_rbuf_mr) die("ibv_reg_mr g_rbuf_pool");

    /* post lots of RECV to SRQ */
    for (int i = 0; i < SRQ_DEPTH; ++i) {
        struct ibv_sge sge = {
            .addr   = (uintptr_t)g_rbuf_pool[i].data,
            .length = SRQ_MSG_SIZE,
            .lkey   = g_rbuf_mr->lkey,
        };
        struct ibv_recv_wr wr = {0}, *bad = NULL;
        wr.wr_id   = (uintptr_t)&g_rbuf_pool[i];  // store buffer addr as wr_id
        wr.sg_list = &sge;
        wr.num_sge = 1;
        if (ibv_post_srq_recv(g_srq, &wr, &bad)) die("ibv_post_srq_recv");
    }

    /* register CQ notify once */
    if (ibv_req_notify_cq(g_cq, 0)) die("ibv_req_notify_cq");
}
/*-------------------------------------------------------------------------*/
static void handle_payload(uint8_t *buf, size_t len, struct conn_ctx *cx)
{
    if (len < sizeof(mux_hdr_t)) { fwrite(buf, 1, len, stdout); fflush(stdout); return; }

    mux_hdr_t *h = (mux_hdr_t *)buf;
    if (ntohl(h->magic) != MUX_MAGIC) { fwrite(buf, 1, len, stdout); fflush(stdout); return; }

    uint16_t type = ntohs(h->type);
    // uint32_t sid  = ntohl(h->stream_id); // use when you need
    uint32_t plen = ntohl(h->len);
    uint8_t *payload = buf + sizeof(mux_hdr_t);

    if (sizeof(mux_hdr_t) + plen > len) {
        fprintf(stderr, "[SERVER] bad frame (len=%zu plen=%u)\n", len, plen);
        return;
    }

    switch (type) {
    case MSG_METRICS:
        if (plen >= sizeof(metrics_t)) {
            metrics_t mloc; memcpy(&mloc, payload, sizeof(mloc));
            metrics_store_update(&mloc);     // update Prometheus store

			if (cx) {
				print_metrics_t(&mloc, cx->peer_ip, cx->peer_port);
			} else {
				print_metrics_t(&mloc, "unknown", 0);
			}
        }
        break;
    case MSG_TEXT:
    default:
        fwrite(payload, 1, plen, stdout);
        fflush(stdout);
        break;
    }
}
/*-------------------------------------------------------------------------*/
static void *cq_poller(void *arg)
{
    (void)arg;
    while (!g_stop && !g_stop_poll) {
        struct ibv_cq *ev_cq = NULL; void *ev_ctx = NULL;

        if (ibv_get_cq_event(g_cc, &ev_cq, &ev_ctx)) {
            if (errno == EINTR) continue;
            perror("ibv_get_cq_event");
            break;
        }
        ibv_ack_cq_events(ev_cq, 1);
        if (ibv_req_notify_cq(g_cq, 0)) { perror("ibv_req_notify_cq"); break; }

        struct ibv_wc wc[64];
        int n;
        while ((n = ibv_poll_cq(g_cq, 64, wc)) > 0) {
            for (int i = 0; i < n; ++i) {
                if (wc[i].status != IBV_WC_SUCCESS) {
                    fprintf(stderr, "[SERVER] WC error: status=%d opcode=%d\n",
                            wc[i].status, wc[i].opcode);
                    continue;
                }
                if (wc[i].opcode == IBV_WC_RECV) {
                    struct recv_buf *rb = (struct recv_buf *)wc[i].wr_id;
                    size_t len = wc[i].byte_len;

                    // connection context (when you need): wc[i].qp_num
                    uint32_t qpn = wc[i].qp_num;
                    struct conn_ctx *cx = NULL;
                    pthread_mutex_lock(&g_qp_mu);
                    if (qpn < QP_MAP_SIZE) cx = g_qp_map[qpn];
                    pthread_mutex_unlock(&g_qp_mu);

					if (cx) {
						handle_payload(rb->data, len, cx);
					} else {
						handle_payload(rb->data, len, NULL);
					}

                    /* return buffer to SRQ */
                    struct ibv_sge sge = {
                        .addr   = (uintptr_t)rb->data,
                        .length = SRQ_MSG_SIZE,
                        .lkey   = g_rbuf_mr->lkey,
                    };
                    struct ibv_recv_wr wr = {0}, *bad = NULL;
                    wr.wr_id   = (uintptr_t)rb;
                    wr.sg_list = &sge; wr.num_sge = 1;
                    if (ibv_post_srq_recv(g_srq, &wr, &bad)) perror("ibv_post_srq_recv");
                }
            }
        }
        if (n < 0) { perror("ibv_poll_cq"); break; }
    }
    return NULL;
}
/*-------------------------------------------------------------------------*/
static struct conn_ctx *build_connection(struct rdma_cm_id *id)
{
    struct conn_ctx *c = calloc(1, sizeof(*c));
    if (!c) return NULL;
    c->id = id;

	// change peer addr to string
    struct sockaddr *psa = rdma_get_peer_addr(id);
    if (psa && psa->sa_family == AF_INET) {
        struct sockaddr_in *sin = (struct sockaddr_in *)psa;
        inet_ntop(AF_INET, &sin->sin_addr, c->peer_ip, sizeof(c->peer_ip));
        c->peer_port = ntohs(sin->sin_port);
    } else {
        snprintf(c->peer_ip, sizeof(c->peer_ip), "?");
        c->peer_port = 0;
    }

    /* create QP using shared CQ/SRQ */
    struct ibv_qp_init_attr qp_attr = {0};
    qp_attr.qp_type          = IBV_QPT_RC;
    qp_attr.sq_sig_all       = 1;
    qp_attr.send_cq          = g_cq;   // shared CQ
    qp_attr.recv_cq          = g_cq;   // shared CQ
    qp_attr.cap.max_send_wr  = 1024;
    qp_attr.cap.max_send_sge = 1;
    qp_attr.cap.max_recv_wr  = 0;      // use SRQ
    qp_attr.cap.max_recv_sge = 0;
    qp_attr.srq              = g_srq;  // shared SRQ

    if (rdma_create_qp(id, g_pd, &qp_attr)) {
        perror("rdma_create_qp");
        free(c);
        return NULL;
    }
    c->qp = id->qp;

    /* register QP mapping */
    uint32_t qpn = c->qp->qp_num;
    if (qpn < QP_MAP_SIZE) {
        pthread_mutex_lock(&g_qp_mu);
        g_qp_map[qpn] = c;
        pthread_mutex_unlock(&g_qp_mu);
    }

    return c;
}
/*-------------------------------------------------------------------------*/
static void destroy_connection(struct conn_ctx *c)
{
    if (!c) return;
    if (c->qp) {
        uint32_t qpn = c->qp->qp_num;
        if (qpn < QP_MAP_SIZE) {
            pthread_mutex_lock(&g_qp_mu);
            if (g_qp_map[qpn] == c) g_qp_map[qpn] = NULL;
            pthread_mutex_unlock(&g_qp_mu);
        }
    }
    if (c->id && c->id->qp) rdma_destroy_qp(c->id);
    free(c);
}
/*-------------------------------------------------------------------------*/
int main(int argc, char **argv)
{
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

    /* Prometheus exporter: start once */
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
    addr.sin_port   = htons(port);
    addr.sin_addr.s_addr = INADDR_ANY;

    if (rdma_bind_addr(listener, (struct sockaddr *)&addr)) die("rdma_bind_addr");
    if (rdma_listen(listener, BACKLOG)) die("rdma_listen");

    printf("[SERVER] listening on port %u (BACKLOG=%d)\n", port, BACKLOG);
    fflush(stdout);

    /* CM event loop */
    while (!g_stop) {
        struct rdma_cm_event *event = NULL;
        if (rdma_get_cm_event(ec, &event)) {
            if (errno == EINTR) continue;
            perror("rdma_get_cm_event");
            break;
        }

        struct rdma_cm_event ev = *event;
        rdma_ack_cm_event(event);

        switch (ev.event) {
        case RDMA_CM_EVENT_CONNECT_REQUEST: {
			if (!g_inited) {
				server_resources_init(ev.id->verbs);
				if (pthread_create(&g_poller_thr, NULL, cq_poller, NULL)) {
					perror("pthread_create(cq_poller)");
					rdma_reject(ev.id, NULL, 0);
					break;
				}
				g_inited = 1;
			}

            struct conn_ctx *c = build_connection(ev.id);
            if (!c) {
                fprintf(stderr, "[SERVER] failed to build connection resources\n");
                rdma_reject(ev.id, NULL, 0);
                continue;
            }
            struct rdma_conn_param cp = {0};
            cp.initiator_depth     = 1;
            cp.responder_resources = 1;
            cp.rnr_retry_count     = 7; // infinite retry
            if (rdma_accept(ev.id, &cp)) {
                perror("rdma_accept");
                destroy_connection(c);
                continue;
            }
            ev.id->context = c;
            break; }

        case RDMA_CM_EVENT_ESTABLISHED: {
            struct conn_ctx *c = (struct conn_ctx *)ev.id->context;
            if (!c) {
                fprintf(stderr, "[SERVER] ESTABLISHED with null context\n");
                rdma_disconnect(ev.id);
            } else {
                printf("[SERVER] connection from %s:%u established\n",
                       c->peer_ip, c->peer_port);
                fflush(stdout);
            }
            break; }

        case RDMA_CM_EVENT_DISCONNECTED: {
            struct conn_ctx *c = (struct conn_ctx *)ev.id->context;
            if (c) {
                c->running = 0;
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

    /* clear finishing */
    g_stop_poll = 1;
    pthread_join(g_poller_thr, NULL);

    if (g_rbuf_mr) ibv_dereg_mr(g_rbuf_mr);
    free(g_rbuf_pool);
    if (g_srq) ibv_destroy_srq(g_srq);
    if (g_cq)  ibv_destroy_cq(g_cq);
    if (g_cc)  ibv_destroy_comp_channel(g_cc);
    if (g_pd)  ibv_dealloc_pd(g_pd);

    rdma_destroy_id(listener);
    rdma_destroy_event_channel(ec);

    printf("[SERVER] exiting\n");
    return 0;
}
