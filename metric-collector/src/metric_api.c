#include "rdma.h"
#include "metric_api.h"
#include "message.h"
/*-------------------------------------------------------------------------*/
qos_requirement qr;
app_feat af;
app_info ai;
gpu_resource gr;
node_info ni;
lb_signal ls;
perf_info pi;
/*-------------------------------------------------------------------------*/
void metric_collect() {
	printf("Collecting metrics\n");

	/* --- dummy data --- */
	// qos requirement
	qr.latency = 50.0f;
	qr.FPS = 30;

	// app_feat
	af.input_res_width = 1920;
	af.input_res_height = 1080;
	af.input_framerate = 30;
	af.input_codec = 1;

	// app_info
	ai.app_id = 0;
	ai.feat = af;
	ai.qos = qr;

	// gpu_resource
	gr.gpu_id = 0;
	gr.enc_sessions = 0;
	gr.enc_util = 20.0f;
	gr.dec_util = 20.0f;

	// node_info
	ni.node_id = 0;
	ni.cpu_utilization = 50.0f;
	ni.gpu = gr;
	ni.isGPU = 1;
	ni.pod_number = 0;

	// lb_signal
	ls.result = 0;

	// perf_info
	pi.session_id = 0;
	pi.pid = 20216;
	pi.avg_latency = 21.6f;
	pi.FPS = 40;
	/* ------------------ */
	
	printf("Successfully collected metrics\n");
} // 지표를 수집하는 함수
/*-------------------------------------------------------------------------*/
void send_lb_message(int c, int cpu) {
	printf("Sending metrics to load balancer\n");	

	struct rdma_queue *q = get_queue(cpu, c);
	void *buf = q->rdma_dev->rbuf->addr;
	
	uint8_t *ptr = (uint8_t *)buf;
	memcpy(ptr, &ai, sizeof(ai));
	ptr += sizeof(ai);
	memcpy(ptr, &ni, sizeof(ni));
	ptr += sizeof(ni);
	memcpy(ptr, &ls, sizeof(ls));
	ptr += sizeof(ls);
	memcpy(ptr, &pi, sizeof(pi));
	ptr += sizeof(pi);

	size_t total_len = ptr - (uint8_t *)buf;

	int ret = rdma_send_wr(c, cpu, total_len);
	if (ret) {
		fprintf(stderr, "send_lb_message: rdma_send_wr failed (%d)\n", ret);
	} else {
		printf("send_lb_message: sent %zu bytes\n", total_len);
	}
}
// 로드밸런싱을 위해 메트릭 콜렉터에서 메세지를 보내는 함수
// node information, performance information
// 기본적인 로직은 1초 주기로 데이터를 수집하여, 콜렉터에게 전송
// 콜렉터는 이를 기반으로 노드를 선택
// 지금 우선적으로 구현해야 할 것은 규칙 기반(휴리스틱) 초기 컨트롤 => not use db, and model
/*-------------------------------------------------------------------------*/
