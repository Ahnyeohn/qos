#include "metrics_store.h"
#include <pthread.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <sys/socket.h>
/*-------------------------------------------------------------------------*/
typedef struct 
{
	int valid;
	app_info ai;
	node_info ni;
	lb_signal ls;
	perf_info pi;
} rec_t;
/*-------------------------------------------------------------------------*/
static rec_t *g_rec = NULL;
static int g_slots = 0;
static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
/*-------------------------------------------------------------------------*/
void metrics_store_init(int slots)
{
	pthread_mutex_lock(&g_mu);
	g_slots = slots;
	g_rec = (rec_t *)calloc(slots, sizeof(rec_t));
	pthread_mutex_unlock(&g_mu);
}
/*-------------------------------------------------------------------------*/
void metrics_store_update(int slots, const app_info *ai, const node_info *ni, const lb_signal *ls, const perf_info *pi)
{
	if (!g_rec || slots < 0 || slots >= g_slots) return;
	pthread_mutex_lock(&g_mu);
	if (ai) memcpy(&g_rec[slots].ai, ai, sizeof(*ai));
	if (ni) memcpy(&g_rec[slots].ni, ni, sizeof(*ni));
	if (ls) memcpy(&g_rec[slots].ls, ls, sizeof(*ls));
	if (pi) memcpy(&g_rec[slots].pi, pi, sizeof(*pi));
	g_rec[slots].valid = 1;
	pthread_mutex_unlock(&g_mu);
}
/*-------------------------------------------------------------------------*/
// Prometheus text exposition format으로 serialization
size_t metrics_store_render(char *out, size_t cap)
{
	size_t n = 0;
#define EMIT(fmt, ...) do { \
    int _w = snprintf(out + n, (n < cap ? cap - n : 0), fmt, ##__VA_ARGS__); \
    if (_w > 0) n += (size_t)_w; \
} while (0)

    pthread_mutex_lock(&g_mu);

    /* 지표 설명(선택) */
    EMIT("# HELP qos_latency_ms App-level QoS target latency in ms\n");
    EMIT("# TYPE qos_latency_ms gauge\n");
    EMIT("# HELP qos_fps App-level QoS target FPS\n");
    EMIT("# TYPE qos_fps gauge\n");

    EMIT("# HELP node_cpu_utilization_percent Node CPU utilization in percent\n");
    EMIT("# TYPE node_cpu_utilization_percent gauge\n");
    EMIT("# HELP gpu_encoder_sessions Active HW encoder sessions\n");
    EMIT("# TYPE gpu_encoder_sessions gauge\n");
    EMIT("# HELP gpu_encoder_utilization_percent HW encoder utilization in percent\n");
    EMIT("# TYPE gpu_encoder_utilization_percent gauge\n");
    EMIT("# HELP gpu_decoder_utilization_percent HW decoder utilization in percent\n");
    EMIT("# TYPE gpu_decoder_utilization_percent gauge\n");

    EMIT("# HELP lb_result Load balancer decision/result code\n");
    EMIT("# TYPE lb_result gauge\n");

    EMIT("# HELP perf_avg_latency_ms Measured average latency in ms\n");
    EMIT("# TYPE perf_avg_latency_ms gauge\n");
    EMIT("# HELP perf_fps Measured FPS\n");
    EMIT("# TYPE perf_fps gauge\n");

    for (int i = 0; i < g_slots; i++) {
        if (!g_rec[i].valid) continue;
        const app_info  *ai = &g_rec[i].ai;
        const node_info *ni = &g_rec[i].ni;
        const lb_signal *ls = &g_rec[i].ls;
        const perf_info *pi = &g_rec[i].pi;

        /* 공통 라벨: queue, app_id, node_id, pod_number, gpu_id */
        /* 정수 라벨은 문자열로 넣어도 무방 */
        EMIT("qos_latency_ms{queue=\"%d\",app_id=\"%u\",node_id=\"%u\",pod=\"%u\"} %.3f\n", i, ai->app_id, ni->node_id, ni->pod_number, ai->qos.latency);
        EMIT("qos_fps{queue=\"%d\",app_id=\"%u\",node_id=\"%u\",pod=\"%u\"} %u\n", i, ai->app_id, ni->node_id, ni->pod_number, ai->qos.FPS);

        EMIT("node_cpu_utilization_percent{queue=\"%d\",node_id=\"%u\",pod=\"%u\"} %.1f\n", i, ni->node_id, ni->pod_number, ni->cpu_utilization);

        EMIT("gpu_encoder_sessions{queue=\"%d\",gpu_id=\"%u\",node_id=\"%u\",pod=\"%u\"} %u\n", i, ni->gpu.gpu_id, ni->node_id, ni->pod_number, ni->gpu.enc_sessions);
        EMIT("gpu_encoder_utilization_percent{queue=\"%d\",gpu_id=\"%u\",node_id=\"%u\",pod=\"%u\"} %.1f\n", i, ni->gpu.gpu_id, ni->node_id, ni->pod_number, ni->gpu.enc_util);
        EMIT("gpu_decoder_utilization_percent{queue=\"%d\",gpu_id=\"%u\",node_id=\"%u\",pod=\"%u\"} %.1f\n", i, ni->gpu.gpu_id, ni->node_id, ni->pod_number, ni->gpu.dec_util);

        EMIT("lb_result{queue=\"%d\",node_id=\"%u\",pod=\"%u\"} %u\n", i, ni->node_id, ni->pod_number, ls->result);

        EMIT("perf_avg_latency_ms{queue=\"%d\",session_id=\"%u\",pid=\"%u\"} %.3f\n", i, pi->session_id, pi->pid, pi->avg_latency);
        EMIT("perf_fps{queue=\"%d\",session_id=\"%u\",pid=\"%u\"} %u\n", i, pi->session_id, pi->pid, pi->FPS);
    }

    pthread_mutex_unlock(&g_mu);
    return n;
    #undef EMIT
}
/*-------------------------------------------------------------------------*/
/* 아주 단순한 HTTP 서버: GET /metrics 만 응답 */
void* metrics_http_server(void *arg)
{
    int port = arg ? *(int*)arg : 9123;

    int srv = socket(AF_INET, SOCK_STREAM, 0);
    if (srv < 0) { perror("socket"); return NULL; }

    int opt = 1;
    setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in sa = {0};
    sa.sin_family = AF_INET;
    sa.sin_port   = htons(port);
    sa.sin_addr.s_addr = htonl(INADDR_ANY);

    if (bind(srv, (struct sockaddr*)&sa, sizeof(sa)) < 0) {
        perror("bind"); close(srv); return NULL;
    }
    if (listen(srv, 16) < 0) {
        perror("listen"); close(srv); return NULL;
    }
    printf("[metrics] listening on :%d (/metrics)\n", port);

    for (;;) {
        int cli = accept(srv, NULL, NULL);
        if (cli < 0) { usleep(1000); continue; }

        /* 요청을 대충 소비 (간단 구현) */
        char req[1024];
		ssize_t r1 = read(cli, req, sizeof(req) - 1);
		(void)r1;

		char method[8] = {0}, path[256] = {0};
		if (sscanf(req, "%7s %255s", method, path) != 2) {
			const char *bad = "HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n";
			write(cli, bad, strlen(bad));
			close(cli);
			continue;
		}

		int is_get = (strcmp(method, "GET") == 0);
		int is_head = (strcmp(method, "HEAD") == 0);

		int path_ok = (!strcmp(path, "/gpu_metrics"));
		if (!path_ok) {
			const char *nf = "HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n";
			write(cli, nf, strlen(nf));
			close(cli);
			continue;
		}

        /* 본문 작성 */
        char *body = (char*)malloc(128*1024);
        if (!body) { close(cli); continue; }
        size_t blen = metrics_store_render(body, 128*1024);

        char header[256];
        int hlen = snprintf(header, sizeof(header),
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/plain; version=0.0.4; charset=utf-8\r\n"
            "Content-Length: %zu\r\n"
            "Connection: close\r\n\r\n", blen);

        (void)write(cli, header, hlen);
        (void)write(cli, body, blen);

        free(body);
        close(cli);
    }
    return NULL;
}
/*-------------------------------------------------------------------------*/
