#pragma once
/*-------------------------------------------------------------------------*/
#include <stdint.h>
#include <string.h>
#include <arpa/inet.h>   
/*-------------------------------------------------------------------------*/
// qos_requirement
typedef struct {
    float latency;					// 4 B
    uint32_t FPS;					// 4 B
} qos_requirement;
/*-------------------------------------------------------------------------*/
// app_feat
typedef struct {
    uint32_t input_res_width;		// 4 B
    uint32_t input_res_height;		// 4 B
    uint32_t input_framerate;		// 4 B
    uint32_t input_codec;			// 4 B
} app_feat;
/*-------------------------------------------------------------------------*/
// app_info
typedef struct {
    uint32_t app_id;				// 4 B
    app_feat feat;
    qos_requirement qos;
} app_info;
/*-------------------------------------------------------------------------*/
// gpu_resource
typedef struct {
    uint32_t gpu_id;				// 4 B
    uint32_t enc_sessions;			// 4 B
    float enc_util;
    float dec_util;
} gpu_resource;
/*-------------------------------------------------------------------------*/
// node_info
typedef struct {
    uint32_t node_id;				// 4 B
    float cpu_utilization;			// 4 B
    gpu_resource gpu;
    uint8_t node_ready;
    uint8_t isGPU;
    uint32_t pod_number;
} node_info;
/*-------------------------------------------------------------------------*/
// lb_signal
typedef struct {
    uint8_t result;
} lb_signal;
/*-------------------------------------------------------------------------*/
// perf_info
typedef struct {
    uint32_t session_id;    
    uint32_t pid;    
    float avg_latency;     
    uint32_t FPS;     
} perf_info;
/*-------------------------------------------------------------------------*/
typedef struct {
	qos_requirement qr;
	app_feat af;
	app_info ai;
	gpu_resource gr;
	node_info ni;
	lb_signal ls;
	perf_info pi;
} metrics_t;
/*-------------------------------------------------------------------------*/
#pragma pack(push, 1)
typedef struct {
    uint32_t magic;      // "MUXL" = 0x4D55584C
    uint16_t type;       // 1=TEXT, 2=METRICS
    uint16_t reserved;
    uint32_t stream_id;  // logical stream/session/tenant id
    uint32_t len;        // payload length
} mux_hdr_t;
#pragma pack(pop)

#define MUX_MAGIC   0x4D55584Cu
#define MSG_TEXT    1
#define MSG_METRICS 2
/*-------------------------------------------------------------------------*/
