#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <time.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <signal.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <rdma/rdma_cma.h>
#include <infiniband/verbs.h>
/*-------------------------------------------------------------------------*/
#include "metric_api.h"   // metric_collect(metrics_t*)
#include "message.h"      // metrics_t, mux_hdr_t, MUX_MAGIC, MSG_METRICS 등
/*-------------------------------------------------------------------------*/
#define MSG_SIZE    4096
#define MAX_SEND_WR 128
#define MAX_RECV_WR 1
#define MAX_SGE     1
/*-------------------------------------------------------------------------*/
struct cli_ctx {
    struct rdma_cm_id *id;
    struct ibv_pd *pd;
    struct ibv_comp_channel *comp_ch;
    struct ibv_cq *cq;
    struct ibv_qp *qp;
    uint8_t *send_buf;
    struct ibv_mr *send_mr;
};
/*-------------------------------------------------------------------------*/
static volatile sig_atomic_t g_stop = 0;
static void on_sigint(int signo) { (void)signo; g_stop = 1; }

static void die(const char *msg) { perror(msg); exit(EXIT_FAILURE); }
/*-------------------------------------------------------------------------*/
static void wait_event(struct rdma_event_channel *ec, enum rdma_cm_event_type expect) {
    struct rdma_cm_event *event = NULL;
    if (rdma_get_cm_event(ec, &event)) die("rdma_get_cm_event");
    enum rdma_cm_event_type got = event->event;
    rdma_ack_cm_event(event);
    if (got != expect) {
        fprintf(stderr, "Expected CM event %d, got %d\n", expect, got);
        exit(EXIT_FAILURE);
    }
}
/*-------------------------------------------------------------------------*/
/* 멀티플렉싱 헤더 붙여 전송 */
static int send_mux(struct cli_ctx *c, uint16_t type, uint32_t sid,
                    const void *payload, uint32_t plen)
{
    mux_hdr_t h = {
        .magic     = htonl(MUX_MAGIC),
        .type      = htons(type),
        .reserved  = 0,
        .stream_id = htonl(sid),
        .len       = htonl(plen),
    };
    if (sizeof(h) + plen > MSG_SIZE) {
        errno = EMSGSIZE;
        return -1;
    }

    memcpy(c->send_buf, &h, sizeof(h));
    memcpy(c->send_buf + sizeof(h), payload, plen);

    struct ibv_sge sge = {
        .addr   = (uintptr_t)c->send_buf,
        .length = (uint32_t)(sizeof(h) + plen),
        .lkey   = c->send_mr->lkey,
    };
    struct ibv_send_wr wr = {0}, *bad = NULL;
    wr.sg_list   = &sge;
    wr.num_sge   = 1;
    wr.opcode    = IBV_WR_SEND;
    wr.send_flags = IBV_SEND_SIGNALED;

    return ibv_post_send(c->qp, &wr, &bad);
}
/*-------------------------------------------------------------------------*/
static void wait_for_send_comp(struct cli_ctx *c) {
    if (ibv_req_notify_cq(c->cq, 0)) die("ibv_req_notify_cq");

    struct ibv_cq *ev_cq = NULL; void *ev_ctx = NULL;
    if (ibv_get_cq_event(c->comp_ch, &ev_cq, &ev_ctx)) die("ibv_get_cq_event");
    ibv_ack_cq_events(ev_cq, 1);

    struct ibv_wc wc;
    int n;
    while ((n = ibv_poll_cq(c->cq, 1, &wc)) == 0) { /* spin */ }
    if (n < 0) die("ibv_poll_cq");
    if (wc.status != IBV_WC_SUCCESS || wc.opcode != IBV_WC_SEND) {
        fprintf(stderr, "[CLIENT] send WC error: status=%d opcode=%d\n", wc.status, wc.opcode);
        exit(EXIT_FAILURE);
    }
}
/*-------------------------------------------------------------------------*/
int main(int argc, char **argv) {
    srand((unsigned)time(NULL));

    const char *server_ip = NULL;
    uint16_t port = 7471;

    int opt;
    while ((opt = getopt(argc, argv, "s:p:")) != -1) {
        switch (opt) {
        case 's': server_ip = optarg; break;
        case 'p': port = (uint16_t)atoi(optarg); break;
        default:
            fprintf(stderr, "Usage: %s -s <server_ip> [-p port]\n", argv[0]);
            return EXIT_FAILURE;
        }
    }
    if (!server_ip) {
        fprintf(stderr, "Usage: %s -s <server_ip> [-p port]\n", argv[0]);
        return EXIT_FAILURE;
    }

    signal(SIGINT, on_sigint);

    struct rdma_event_channel *ec = rdma_create_event_channel();
    if (!ec) die("rdma_create_event_channel");

    struct rdma_cm_id *id = NULL;
    if (rdma_create_id(ec, &id, NULL, RDMA_PS_TCP)) die("rdma_create_id");

    struct sockaddr_in dst = {0};
    dst.sin_family = AF_INET;
    dst.sin_port   = htons(port);
    if (inet_pton(AF_INET, server_ip, &dst.sin_addr) != 1) die("inet_pton");

    if (rdma_resolve_addr(id, NULL, (struct sockaddr *)&dst, 2000)) die("rdma_resolve_addr");
    wait_event(ec, RDMA_CM_EVENT_ADDR_RESOLVED);

    if (rdma_resolve_route(id, 2000)) die("rdma_resolve_route");
    wait_event(ec, RDMA_CM_EVENT_ROUTE_RESOLVED);

    /* 리소스 구성 */
    struct cli_ctx c = {0};
    c.id = id;

    c.pd = ibv_alloc_pd(id->verbs);
    if (!c.pd) die("ibv_alloc_pd");

    c.comp_ch = ibv_create_comp_channel(id->verbs);
    if (!c.comp_ch) die("ibv_create_comp_channel");

    c.cq = ibv_create_cq(id->verbs, MAX_SEND_WR + MAX_RECV_WR, NULL, c.comp_ch, 0);
    if (!c.cq) die("ibv_create_cq");

    struct ibv_qp_init_attr qp_attr = {0};
    qp_attr.qp_type        = IBV_QPT_RC;
    qp_attr.sq_sig_all     = 1;
    qp_attr.send_cq        = c.cq;
    qp_attr.recv_cq        = c.cq;
    qp_attr.cap.max_send_wr  = MAX_SEND_WR;
    qp_attr.cap.max_recv_wr  = MAX_RECV_WR;
    qp_attr.cap.max_send_sge = MAX_SGE;
    qp_attr.cap.max_recv_sge = MAX_SGE;

    if (rdma_create_qp(id, c.pd, &qp_attr)) die("rdma_create_qp");
    c.qp = id->qp;

    c.send_buf = aligned_alloc(4096, MSG_SIZE);
    if (!c.send_buf) die("aligned_alloc");
    c.send_mr = ibv_reg_mr(c.pd, c.send_buf, MSG_SIZE, 0);
    if (!c.send_mr) die("ibv_reg_mr");

    struct rdma_conn_param cp = {0};
    cp.initiator_depth     = 1;
    cp.responder_resources = 1;
    cp.rnr_retry_count     = 7; // infinite retry

    if (rdma_connect(id, &cp)) die("rdma_connect");
    wait_event(ec, RDMA_CM_EVENT_ESTABLISHED);

    /* 주기적으로 메트릭 수집 후 MUX 헤더와 함께 전송 */
    while (!g_stop) {
        metrics_t m;
        metric_collect(&m);  // 랜덤/실측 값 채움 (네가 정의한 함수)

        if (send_mux(&c, MSG_METRICS, /*stream_id*/ 1, &m, sizeof(m)) != 0) {
            die("send_mux");
        }
        wait_for_send_comp(&c);

        /* 너무 빡세지 않게 텀을 둠 (원하는 주기로 바꿔도 됨) */
//		usleep(200 * 1000); // 200 ms
		struct timespec ts = {
			.tv_sec = 0,
			.tv_nsec = 200 * 1000 * 1000L
		};
		nanosleep(&ts, NULL);
    }

    rdma_disconnect(id);
    wait_event(ec, RDMA_CM_EVENT_DISCONNECTED);

    /* 정리 */
    if (c.qp) rdma_destroy_qp(id);
    if (c.cq) ibv_destroy_cq(c.cq);
    if (c.comp_ch) ibv_destroy_comp_channel(c.comp_ch);
    if (c.send_mr) ibv_dereg_mr(c.send_mr);
    free(c.send_buf);
    if (c.pd) ibv_dealloc_pd(c.pd);

    rdma_destroy_id(id);
    rdma_destroy_event_channel(ec);
    return 0;
}
