#include "rdma.h"
#include "metric_api.h"
#include "message.h"
#include "metrics_store.h"
#include <stdint.h>
#include <string.h>
/*-------------------------------------------------------------------------*/
pthread_t server_thread;
pthread_t worker_thread[NUM_QUEUES];
pthread_t metrics_thread;
/*-------------------------------------------------------------------------*/
struct sockaddr_in s_addr;
size_t length;
/*-------------------------------------------------------------------------*/
static int parse_update_and_print(int cpu, const uint8_t *buf, size_t len)
{
    size_t off = 0;
    app_info  ai;
    node_info ni;
    lb_signal ls;
    perf_info pi;

    if (len < off + sizeof(app_info))  return -1;
    memcpy(&ai, buf + off, sizeof(app_info));  off += sizeof(app_info);

    if (len < off + sizeof(node_info)) return -1;
    memcpy(&ni, buf + off, sizeof(node_info)); off += sizeof(node_info);

    if (len < off + sizeof(lb_signal)) return -1;
    memcpy(&ls, buf + off, sizeof(lb_signal)); off += sizeof(lb_signal);

    if (len < off + sizeof(perf_info)) return -1;
    memcpy(&pi, buf + off, sizeof(perf_info)); off += sizeof(perf_info);

    /* Prometheus 저장소 갱신 */
    metrics_store_update(cpu, &ai, &ni, &ls, &pi);

    /* (원하면) 로그 */
    printf("===== Received Metrics (CPU %d) =====\n", cpu);
    printf("[app info]\n");
    printf("- app_id: %u\n", ai.app_id);
    printf("- resolution: %ux%u @ %u fps\n",
           ai.feat.input_res_width, ai.feat.input_res_height, ai.feat.input_framerate);
    printf("- codec: %u\n", ai.feat.input_codec);
    printf("- qos: latency = %.2f ms, FPS = %u\n", ai.qos.latency, ai.qos.FPS);

    printf("\n[node info]\n");
    printf("- node_id: %u\n", ni.node_id);
    printf("- cpu_util: %.1f%%\n", ni.cpu_utilization);
    printf("- gpu_id: %u, enc_sessions: %u\n", ni.gpu.gpu_id, ni.gpu.enc_sessions);
    printf("- enc_util: %.1f, dec_util: %.1f\n", ni.gpu.enc_util, ni.gpu.dec_util);
    printf("- isGPU: %u, pod_number: %u\n", ni.isGPU, ni.pod_number);

    printf("\n[lb_signal]\n");
    printf("- result: %u\n", ls.result);

    printf("\n[perf_info]\n");
    printf("- session_id: %u, pid: %u\n", pi.session_id, pi.pid);
    printf("- avg_latency: %.2f ms, FPS: %u\n", pi.avg_latency, pi.FPS);
    printf("=====================================\n");

    return 0;
}
/*-------------------------------------------------------------------------*/
static void *process_server(void *arg)
{
    int ret = rdma_open_server(&s_addr, length);
    if (ret) {
        printf("rdma_open_server failed\n");
    }
    pthread_exit(NULL);
}
/*-------------------------------------------------------------------------*/
static void *process_worker(void *arg)
{
    int cpu = *(int *)arg;
    printf("[CPU %d]: start\n", cpu);

    /* 무한 서비스: 서버는 영원히 수신 */
    for (;;) {
        struct rdma_queue *q = get_queue(cpu, false);
        if (!q || !q->connected || !q->mr || !q->qp) {
            /* 해당 슬롯에 연결이 없으면 잠깐 쉼 */
            usleep(1000);
            continue;
        }

        /* Recv 등록 → 완료 대기 → 데이터 소비 */
        if (rdma_recv_wr(false, cpu, length) == 0) {
            if (rdma_poll_cq(false, cpu, 1) == 0) {
				(void)parse_update_and_print(cpu, (const uint8_t *)q->buf, length);
			}
        }
        /* 바로 다음 수신 준비 (루프 반복) */
    }

    /* 도달하지 않음 */
    pthread_exit(NULL);
}
/*-------------------------------------------------------------------------*/
static void get_addr(char *dst)
{
    struct addrinfo *res;

    int ret = getaddrinfo(dst, NULL, NULL, &res);
    if (ret) {
        printf("getaddrinfo failed\n");
        exit(1);
    }

    if (res->ai_family == PF_INET) {
        memcpy(&s_addr, res->ai_addr, sizeof(struct sockaddr_in));
    } else if (res->ai_family == PF_INET6) {
        memcpy(&s_addr, res->ai_addr, sizeof(struct sockaddr_in6));
    } else {
        exit(1);
    }

    freeaddrinfo(res);
}
/*-------------------------------------------------------------------------*/
static void usage(void)
{
    printf("[Usage] : ");
    printf("./server [-s <server ip>] [-p <port>] [-l <data size>]\n");
    exit(1);
}
/*-------------------------------------------------------------------------*/
int main(int argc, char* argv[])
{
    int option;

    while ((option = getopt(argc, argv, "s:p:l:")) != -1) {
        switch (option) {
            case 's':
                get_addr(optarg);
                break;
            case 'p':
                s_addr.sin_port = htons(strtol(optarg, NULL, 0));
                printf("Listening on port %s.\n", optarg);
                break;
            case 'l':
                length = strtol(optarg, NULL, 0);
                break;
            default:
                usage();
        }
    }

    if (!s_addr.sin_port) {
        usage();
    }
    s_addr.sin_family = AF_INET;

    pthread_create(&server_thread, NULL, process_server, NULL);

    /* 최소 1개 연결 성립 대기 (그 후에도 서버는 계속 수락) */
    while (!rdma_is_connected()) { usleep(1000); }
    printf("Successfully connected at least one client\n");

	metrics_store_init(NUM_QUEUES);
	int metrics_port = 9100;
	pthread_create(&metrics_thread, NULL, metrics_http_server, &metrics_port);

    int cores[NUM_QUEUES];
    for (int i = 0; i < NUM_QUEUES; i++) {
        cores[i] = i;
        pthread_create(&worker_thread[i], NULL, process_worker, &cores[i]);
    }

    /* 서버 스레드는 영원히 이벤트 루프 → 여기서 block */
    pthread_join(server_thread, NULL);
    return 0;
}
/*-------------------------------------------------------------------------*/
