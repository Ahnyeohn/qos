#include "rdma.h"

struct rdma_device *rdma_dev = NULL;

static int rdma_open_device(int is_server)
{
    int i, ret;

    rdma_dev = (struct rdma_device *)calloc(1, sizeof(struct rdma_device));
    if (!rdma_dev) {
        printf("calloc failed\n");
        return -1;
    }
    pthread_mutex_init(&rdma_dev->lock, NULL);

    for (i = 0; i < NUM_QUEUES; i++) {
        rdma_dev->queues[i] = (struct rdma_queue *)calloc(1, sizeof(struct rdma_queue));
        if (!rdma_dev->queues[i]) {
            printf("calloc failed\n");
            goto clean_dev;
        }
        rdma_dev->queues[i]->rdma_dev = rdma_dev;
        rdma_dev->queues[i]->connected = 0;
    }

    /* event channel: 서버 1개, 클라 큐별 */
    int nr_channel = (is_server == true) ? 1 : NUM_QUEUES;
    for (i = 0; i < nr_channel; i++) {
        rdma_dev->ec[i] = rdma_create_event_channel();
        if (!rdma_dev->ec[i]) {
            printf("rdma_create_event_channel failed\n");
            goto clean_queues;
        }
    }

    /* cm id 생성: 서버는 1개(listen), 클라는 큐별 */
    for (i = 0; i < nr_channel; i++) {
        ret = rdma_create_id(rdma_dev->ec[i], &rdma_dev->cm_id[i], NULL, RDMA_PS_TCP);
        if (ret) {
            printf("rdma_create_id failed\n");
            goto close_ec;
        }
    }

    return 0;

close_ec:
    for (i = 0; i < nr_channel; i++)
        rdma_destroy_event_channel(rdma_dev->ec[i]);
clean_queues:
    for (i = 0; i < NUM_QUEUES; i++)
        if (rdma_dev->queues[i]) free(rdma_dev->queues[i]);
clean_dev:
    pthread_mutex_destroy(&rdma_dev->lock);
    free(rdma_dev);
    rdma_dev = NULL;
    return -1;
}

static int rdma_create_device(struct rdma_queue *q)
{
    if (q->rdma_dev->pd) {
        return 0;
    }

    q->rdma_dev->verbs = q->cm_id->verbs;
    q->rdma_dev->pd = ibv_alloc_pd(q->rdma_dev->verbs);
    if (!q->rdma_dev->pd) {
        printf("ibv_alloc_pd failed\n");
        return -1;
    }
    return 0;
}

void rdma_close_device(void)
{
    if (!rdma_dev) return;

    for (int i = 0; i < NUM_QUEUES; i++) {
        struct rdma_queue *q = rdma_dev->queues[i];
        if (!q) continue;

        if (q->qp) rdma_destroy_qp(q->cm_id);
        if (q->cq) ibv_destroy_cq(q->cq);

        if (q->mr) ibv_dereg_mr(q->mr);
        if (q->buf) free(q->buf);

        if (rdma_dev->cm_id[i]) rdma_destroy_id(rdma_dev->cm_id[i]);
        if (rdma_dev->ec[i]) rdma_destroy_event_channel(rdma_dev->ec[i]);

        free(q);
    }

    if (rdma_dev->pd) ibv_dealloc_pd(rdma_dev->pd);

    pthread_mutex_destroy(&rdma_dev->lock);
    free(rdma_dev);
    rdma_dev = NULL;
}

static int rdma_create_queue(struct rdma_queue *q,
                             struct ibv_comp_channel *cc, int c)
{
    int ret;

    if (!cc) {
        /* completion channel */
        cc = ibv_create_comp_channel(q->cm_id->verbs);
        if (!cc) {
            printf("ibv_create_comp_channel failed\n");
            return -1;
        }
    }

    /* completion queue */
    q->cq = ibv_create_cq(q->cm_id->verbs, CQ_CAPACITY, NULL, cc, 0);
    if (!q->cq) {
        printf("ibv_create_cq failed\n");
        ibv_destroy_comp_channel(cc);
        return -1;
    }

    ret = ibv_req_notify_cq(q->cq, 0);
    if (ret) {
        printf("ibv_req_notify_cq failed\n");
        ibv_destroy_cq(q->cq);
        ibv_destroy_comp_channel(cc);
        return ret;
    }

    /* queue pair */
    struct ibv_qp_init_attr qp_attr = {};
    qp_attr.send_cq = q->cq;
    qp_attr.recv_cq = q->cq;
    qp_attr.qp_type = IBV_QPT_RC;

    /* (원래 코드의 혼동 수정) WR 개수와 SGE 개수 올바르게 설정 */
    qp_attr.cap.max_send_wr  = c ? MAX_WR  : 64;
    qp_attr.cap.max_recv_wr  = c ? MAX_WR  : 64;
    qp_attr.cap.max_send_sge = c ? MAX_SGE : 32;
    qp_attr.cap.max_recv_sge = c ? MAX_SGE : 32;

    ret = rdma_create_qp(q->cm_id, q->rdma_dev->pd, &qp_attr);
    if (ret) {
        printf("rdma_create_qp failed\n");
        ibv_destroy_cq(q->cq);
        ibv_destroy_comp_channel(cc);
        return ret;
    }
    q->qp = q->cm_id->qp;

    return 0;
}

static int rdma_create_queue_mr(struct rdma_queue *q, size_t length)
{
    if (q->mr) return 0; /* 이미 있음 */

    q->buf_len = length;
    q->buf = (char *)calloc(1, length);
    if (!q->buf) {
        printf("calloc failed\n");
        return -1;
    }

    q->mr = ibv_reg_mr(q->rdma_dev->pd, q->buf, length,
                       IBV_ACCESS_LOCAL_WRITE |
                       IBV_ACCESS_REMOTE_READ |
                       IBV_ACCESS_REMOTE_WRITE);
    if (!q->mr) {
        printf("ibv_reg_mr failed\n");
        free(q->buf);
        q->buf = NULL;
        return -1;
    }
    return 0;
}

static int rdma_modify_qp(struct rdma_queue *q)
{
    struct ibv_qp_attr attr;
    memset(&attr, 0, sizeof(struct ibv_qp_attr));
    attr.pkey_index = 0;

    if (ibv_modify_qp(q->qp, &attr, IBV_QP_PKEY_INDEX)) {
        printf("ibv_modify_qp failed\n");
        return 1;
    }
    return 0;
}

static int on_addr_resolved(struct rdma_cm_id *id)
{
    /* 클라이언트 측에서 호출됨 (주소 해석 완료) */
    struct rdma_queue *q = rdma_dev->queues[rdma_dev->queue_ctr];

    printf("%s\n", __func__);

    id->context = q;
    q->cm_id = id;
    q->rdma_dev = rdma_dev;

    int ret = rdma_create_device(q);
    if (ret) {
        printf("rdma_create_device failed\n");
        return ret;
    }

    ret = rdma_create_queue(q, rdma_dev->cc[rdma_dev->queue_ctr++], true);
    if (ret) {
        printf("rdma_create_queue failed\n");
        return ret;
    }

    ret = rdma_modify_qp(q);
    if (ret) {
        printf("rdma_modify_qp failed\n");
        return ret;
    }

    ret = rdma_resolve_route(q->cm_id, CONNECTION_TIMEOUT_MS);
    if (ret) {
        printf("rdma_resolve_route failed\n");
        return ret;
    }

    return 0;
}

static int on_route_resolved(struct rdma_queue *q)
{
    printf("%s\n", __func__);

    struct rdma_conn_param param = {};
    param.qp_num = q->qp->qp_num;
    param.initiator_depth = 16;
    param.responder_resources = 16;
    param.retry_count = 7;
    param.rnr_retry_count = 7;

    int ret = rdma_connect(q->cm_id, &param);
    if (ret) {
        printf("rdma_connect failed\n");
        return ret;
    }
    return 0;
}

static int find_free_queue_slot(void)
{
    for (int i = 0; i < NUM_QUEUES; i++) {
        if (!rdma_dev->queues[i]->connected && rdma_dev->queues[i]->qp == NULL) {
            return i;
        }
    }
    /* 여유가 없으면 0으로 덮어쓰기 (간단 정책) */
    return 0;
}

static int on_connect_request(struct rdma_cm_id *id,
                              struct rdma_conn_param *param)
{
    /* 서버 측: 새로운 클라이언트 연결 요청 수락 */
    printf("%s\n", __func__);

    pthread_mutex_lock(&rdma_dev->lock);
    int slot = find_free_queue_slot();
    struct rdma_queue *q = rdma_dev->queues[slot];
    pthread_mutex_unlock(&rdma_dev->lock);

    id->context = q;
    q->cm_id = id;
    q->rdma_dev = rdma_dev;

    int ret = rdma_create_device(q);
    if (ret) {
        printf("rdma_create_device failed\n");
        return ret;
    }

    ret = rdma_create_queue(q, rdma_dev->cc[0], false);
    if (ret) {
        printf("rdma_create_queue failed\n");
        return ret;
    }

    /* 큐별 MR 생성 (서버 수신 버퍼) */
    ret = rdma_create_queue_mr(q, rdma_dev->default_buf_len);
    if (ret) {
        printf("rdma_create_queue_mr failed\n");
        return ret;
    }

    /* 디바이스 속성 조회(선택) */
    struct ibv_device_attr attrs = {};
    ret = ibv_query_device(q->rdma_dev->verbs, &attrs);
    if (ret) {
        printf("ibv_query_device failed\n");
        return ret;
    }

    struct rdma_conn_param cm_params = {};
    cm_params.initiator_depth = param->initiator_depth;
    cm_params.responder_resources = param->responder_resources;
    cm_params.rnr_retry_count = param->rnr_retry_count;
    cm_params.flow_control = param->flow_control;

    ret = rdma_accept(q->cm_id, &cm_params);
    if (ret) {
        printf("rdma_accept failed\n");
        return ret;
    }

    return 0;
}

static int on_connection(struct rdma_queue *q)
{
    /* 연결 성립 (서버/클라이언트 공통) */
    printf("%s (qp=%u)\n", __func__, q->qp ? q->qp->qp_num : 0);

    /* 클라이언트 쪽도 큐별 MR이 필요하므로 여기서 생성해 둠 */
    if (!q->mr && rdma_dev->default_buf_len) {
        if (rdma_create_queue_mr(q, rdma_dev->default_buf_len)) {
            printf("rdma_create_queue_mr (on_connection) failed\n");
            return 0; /* 계속 루프는 돌게 함 */
        }
    }

    q->connected = 1;
    rdma_dev->status = 1; /* 최소 1개 연결 성립 */
    return 0; /* 0을 반환해서 이벤트 루프를 계속 돌게 함 */
}

static int on_disconnect(struct rdma_queue *q)
{
    /* 특정 큐의 연결만 정리 (서버 계속 동작) */
    printf("%s\n", __func__);

    q->connected = 0;

    if (q->cm_id) rdma_disconnect(q->cm_id);
    if (q->qp) { rdma_destroy_qp(q->cm_id); q->qp = NULL; }
    if (q->cq) { ibv_destroy_cq(q->cq);     q->cq = NULL; }

    if (q->mr) { ibv_dereg_mr(q->mr);        q->mr = NULL; }
    if (q->buf){ free(q->buf);               q->buf = NULL; q->buf_len = 0; }

    if (q->cm_id) { rdma_destroy_id(q->cm_id); q->cm_id = NULL; }

    /* PD, event_channel, rdma_dev는 유지 (서버 계속 수락) */
    return 0;
}

static int on_event(struct rdma_cm_event *event)
{
    struct rdma_queue *q = (struct rdma_queue *) event->id->context;
    printf("%s: %s\n", __func__, rdma_event_str(event->event));

    switch (event->event) {
        case RDMA_CM_EVENT_ADDR_RESOLVED:
            return on_addr_resolved(event->id);
        case RDMA_CM_EVENT_ROUTE_RESOLVED:
            return on_route_resolved(q);
        case RDMA_CM_EVENT_CONNECT_REQUEST:
            return on_connect_request(event->id, &event->param.conn);
        case RDMA_CM_EVENT_ESTABLISHED:
            return on_connection(q);
        case RDMA_CM_EVENT_DISCONNECTED:
            return on_disconnect(q);
        case RDMA_CM_EVENT_REJECTED:
            printf("connect rejected\n");
            return 0;
        default:
            printf("unknown event: %s\n", rdma_event_str(event->event));
            return 0;
    }
}

int rdma_open_server(struct sockaddr_in *s_addr, size_t length)
{
    int ret = rdma_open_device(true);
    if (ret) {
        printf("rdma_open_device failed\n");
        return ret;
    }

    rdma_dev->default_buf_len = length;

    /* Listen 소켓 바인딩 */
    ret = rdma_bind_addr(rdma_dev->cm_id[0], (struct sockaddr *) s_addr);
    if (ret) {
        printf("rdma_bind_addr failed\n");
        return ret;
    }

    ret = rdma_listen(rdma_dev->cm_id[0], NUM_QUEUES + 1);
    if (ret) {
        printf("rdma_listen failed\n");
        return ret;
    }

    /* 이벤트 무한 루프: 서버는 죽지 않음 */
    struct rdma_cm_event *event;
    for (;;) {
        if (rdma_get_cm_event(rdma_dev->ec[0], &event)) {
            /* 에러 시 잠깐 쉬고 계속 */
            usleep(1000);
            continue;
        }
        struct rdma_cm_event event_copy;
        memcpy(&event_copy, event, sizeof(*event));
        rdma_ack_cm_event(event);

        (void)on_event(&event_copy); /* 계속 루프 */
    }
    /* 도달하지 않음 */
    return 0;
}

int rdma_open_client(struct sockaddr_in *s_addr,
                     struct sockaddr_in *c_addr, size_t length)
{
    int ret = rdma_open_device(false);
    if (ret) {
        printf("rdma_open_device failed\n");
        goto failed;
    }
    rdma_dev->default_buf_len = length;

    struct rdma_cm_event *event;
    for (unsigned int i = 0; i < NUM_QUEUES; i++) {
        ret = rdma_resolve_addr(rdma_dev->cm_id[i],
                                NULL, (struct sockaddr *) s_addr, CONNECTION_TIMEOUT_MS);
        if (ret) {
            printf("rdma_resolve_addr failed\n");
            return ret;
        }

        /* 각 큐별 이벤트 드레인 (addr→route→established 등) */
        for (;;) {
            if (rdma_get_cm_event(rdma_dev->ec[i], &event)) {
                usleep(1000);
                continue;
            }
            struct rdma_cm_event event_copy;
            memcpy(&event_copy, event, sizeof(*event));
            rdma_ack_cm_event(event);

            (void)on_event(&event_copy);

            if (rdma_dev->queues[i]->connected)
                break; /* 이 큐 연결 성립 */
        }
    }

    /* 클라: 최소 하나 연결되면 status=1 (on_connection에서 이미 셋업됨) */
    return 0;

failed:
    rdma_done();
    return ret;
}

struct rdma_queue *get_queue(int idx, int c)
{
    (void)c; /* 현재 구현에선 동일 */
    if (!rdma_dev) return NULL;
    if (idx < 0 || idx >= NUM_QUEUES) return NULL;
    return rdma_dev->queues[idx];
}

int rdma_is_connected(void)
{
    if (!rdma_dev) return 0;
    return rdma_dev->status;
}

void rdma_done(void)
{
    if (!rdma_dev) return;
    rdma_dev->status = -1;
}

int rdma_poll_cq(int c, int cpu, int total) {
    (void)c;
    struct rdma_queue *q = get_queue(cpu, c);
    if (!q || !q->cq) return -1;

    struct ibv_wc wc_stack[1];
    struct ibv_wc *wc = wc_stack;
    if (total != 1) {
        wc = (struct ibv_wc *)calloc(total, sizeof(struct ibv_wc));
        if (!wc) return -1;
    }

    int cnt = 0, ret;
    while (cnt < total) {
        ret = ibv_poll_cq(q->cq, total - cnt, wc + cnt);
        if (ret < 0) {
            if (wc != wc_stack) free(wc);
            return -1;
        }
        if (ret == 0) {
            /* 바쁜 대기: 필요시 usleep 등 */
            continue;
        }
        cnt += ret;
    }

    for (int i = 0; i < total; i++) {
        if (wc[i].status != IBV_WC_SUCCESS) {
            printf("[%d]: %s at %d\n", cpu, ibv_wc_status_str(wc[i].status), i);
            if (wc != wc_stack) free(wc);
            return -1;
        }
    }

    if (wc != wc_stack) free(wc);
    return 0;
}

int rdma_recv_wr(int c, int cpu, size_t length)
{
    (void)c;
    struct rdma_queue *q = get_queue(cpu, c);
    if (!q || !q->qp || !q->mr) return -1;

    struct ibv_sge sge = {};
    sge.addr   = (uint64_t)(uintptr_t)q->buf;
    sge.length = (uint32_t)length;
    sge.lkey   = q->mr->lkey;

    struct ibv_recv_wr wr = {};
    wr.sg_list = &sge;
    wr.num_sge = 1;

    struct ibv_recv_wr *bad_wr = NULL;
    int ret = ibv_post_recv(q->qp, &wr, &bad_wr);
    if (ret) {
        printf("ibv_post_recv failed\n");
        return ret;
    }
    return 0;
}

int rdma_send_wr(int c, int cpu, size_t length)
{
    (void)c;
    struct rdma_queue *q = get_queue(cpu, c);
    if (!q || !q->qp || !q->mr) return -1;

    struct ibv_sge sge = {};
    sge.addr   = (uint64_t)(uintptr_t)q->buf;
    sge.length = (uint32_t)length;
    sge.lkey   = q->mr->lkey;

    struct ibv_send_wr wr = {};
    wr.sg_list = &sge;
    wr.num_sge = 1;
    wr.opcode  = IBV_WR_SEND;
    wr.send_flags = IBV_SEND_SIGNALED;

    struct ibv_send_wr *bad_wr = NULL;
    int ret = ibv_post_send(q->qp, &wr, &bad_wr);
    if (ret) {
        printf("ibv_post_send failed\n");
        return ret;
    }
    return 0;
}
