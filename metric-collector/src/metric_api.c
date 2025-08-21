#include "rdma.h"
#include "metric_api.h"
#include "message.h"
#include <stdint.h>
#include <string.h>
#include <stdio.h>

/*-------------------------------------------------------------------------*/
qos_requirement qr;
app_feat       af;
app_info       ai;
gpu_resource   gr;
node_info      ni;
lb_signal      ls;
perf_info      pi;
/*-------------------------------------------------------------------------*/

void metric_collect(void) {
    printf("Collecting metrics\n");

    /* --- dummy data --- */
    qr.latency = 50.0f;
    qr.FPS = 30;

    af.input_res_width  = 1920;
    af.input_res_height = 1080;
    af.input_framerate  = 30;
    af.input_codec      = 1;

    ai.app_id = 0;
    ai.feat   = af;
    ai.qos    = qr;

    gr.gpu_id       = 0;
    gr.enc_sessions = 0;
    gr.enc_util     = 20.0f;
    gr.dec_util     = 20.0f;

    ni.node_id         = 0;
    ni.cpu_utilization = 50.0f;
    ni.gpu             = gr;
    ni.isGPU           = 1;
    ni.pod_number      = 0;

    ls.result = 0;

    pi.session_id  = 0;
    pi.pid         = 20216;
    pi.avg_latency = 21.6f;
    pi.FPS         = 40;

    printf("Successfully collected metrics\n");
}

/* 전송 메시지 총 길이 계산 매크로(서버 Recv 길이와 동일해야 안전) */
#define LB_MSG_SIZE ( sizeof(app_info) \
                    + sizeof(node_info) \
                    + sizeof(lb_signal) \
                    + sizeof(perf_info) )

int send_lb_message(int c, int cpu) {
    (void)c; /* 현재 구현에선 의미 없음 */
    printf("Sending metrics to load balancer\n");

    struct rdma_queue *q = get_queue(cpu, /*c=*/true);
    if (!q || !q->mr || !q->buf) {
        fprintf(stderr, "send_lb_message: queue/MR/buf not ready\n");
        return -1;
    }

    /* 총 길이 산출 */
    const size_t total_len = LB_MSG_SIZE;
    if (total_len > q->buf_len) {
        fprintf(stderr, "send_lb_message: payload(%zu) > q->buf_len(%zu)\n",
                total_len, q->buf_len);
        return -1;
    }

    /* 직렬화: 큐별 버퍼(q->buf)에 순서대로 복사 */
    uint8_t *ptr = (uint8_t *)q->buf;

    memcpy(ptr, &ai, sizeof(ai));  ptr += sizeof(ai);
    memcpy(ptr, &ni, sizeof(ni));  ptr += sizeof(ni);
    memcpy(ptr, &ls, sizeof(ls));  ptr += sizeof(ls);
    memcpy(ptr, &pi, sizeof(pi));  ptr += sizeof(pi);

    /* 정확한 길이만큼 전송 */
    int ret = rdma_send_wr(true, cpu, total_len);
    if (ret) {
        fprintf(stderr, "send_lb_message: rdma_send_wr failed (%d)\n", ret);
        return ret;
    }

    printf("send_lb_message: sent %zu bytes\n", total_len);
    return 0;
}
