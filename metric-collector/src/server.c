#include "rdma.h"
#include "metric_api.h"
#include "message.h"
/*-------------------------------------------------------------------------*/
struct sockaddr_in s_addr;
size_t length;
/*-------------------------------------------------------------------------*/
static void process_server()
{
	int ret = rdma_open_server(&s_addr, length);
	if (ret) {
		printf("rdma_open_server failed\n");
	}
}
/*-------------------------------------------------------------------------*/
static void process_worker()
{
	while (rdma_is_connected()) {
		rdma_recv_wr(false, 0, length);
		rdma_poll_cq(false, 0, 1);

		struct rdma_queue *q = get_queue(0, 0);
		uint8_t *buf = (uint8_t *)q->rdma_dev->buf;
	
		app_info *recv_ai = (app_info *)buf;
		buf += sizeof(app_info);

		node_info *recv_ni = (node_info *)buf;
		buf += sizeof(node_info);

		lb_signal *recv_ls = (lb_signal *)buf;
		buf += sizeof(lb_signal);

		perf_info *recv_pi = (perf_info *)buf;
		buf += sizeof(perf_info);

		// print
		printf("===== Received Metrics =====\n");
		printf("[app info]\n");
		printf("- app_id: %u\n", recv_ai->app_id);
		printf("- resolution: %ux%u @ %u fps\n", recv_ai->feat.input_res_width, recv_ai->feat.input_res_height, recv_ai->feat.input_framerate);
		printf("- codec: %u\n", recv_ai->feat.input_codec);
		printf("- qos: latency = %.2f ms, FPS = %u\n", recv_ai->qos.latency, recv_ai->qos.FPS);

		printf("\n[node info]\n");
		printf("- node_id: %u\n", recv_ni->node_id);
		printf("- cpu_util: %.1f%%\n", recv_ni->cpu_utilization);
		printf("- gpu_id: %u, enc_sessions: %u\n", recv_ni->gpu.gpu_id, recv_ni->gpu.enc_sessions);
		printf("- enc_util: %.1f, dec_util: %.1f\n", recv_ni->gpu.enc_util, recv_ni->gpu.dec_util);
		printf("- isGPU: %u, pod_number: %u\n", recv_ni->isGPU, recv_ni->pod_number);

		printf("\n[lb_signal]\n");
		printf("- result: %u\n", recv_ls->result);

		printf("\n[perf_info]\n");
        printf("- session_id: %u, pid: %u\n", recv_pi->session_id, recv_pi->pid);
        printf("- avg_latency: %.2f ms, FPS: %u\n", recv_pi->avg_latency, recv_pi->FPS);
        printf("============================\n");
	}
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

	process_server();
	while (!rdma_is_connected());

	printf("Successfully conntected\n");

	process_worker();

	return 0;
}
/*-------------------------------------------------------------------------*/
