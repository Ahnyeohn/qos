#include "metric_api.h"
#include "message.h"
/*-------------------------------------------------------------------------*/
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
/*-------------------------------------------------------------------------*/
void metric_collect(metrics_t *out) {
    printf("Collecting metrics\n");

    /* --- dummy data --- */
    out->qr.latency = (float)(rand() % 200);
	out->qr.FPS = 20 + (rand() % 60);

	out->af.input_res_width  = (rand() % 2) ? 1920 : 1280;
    out->af.input_res_height = (rand() % 2) ? 1080 : 720;
    out->af.input_framerate  = 15 + (rand() % 45);
    out->af.input_codec      = rand() % 4;

    out->ai.app_id = rand() % 1000;
    out->ai.feat   = out->af;
    out->ai.qos    = out->qr;

    out->gr.gpu_id       = rand() % 8;
    out->gr.enc_sessions = rand() % 16;
    out->gr.enc_util     = (float)(rand() % 101);
    out->gr.dec_util     = (float)(rand() % 101);

    out->ni.node_id         = rand() % 100;
    out->ni.cpu_utilization = (float)(rand() % 101);
    out->ni.gpu             = out->gr;
    out->ni.isGPU           = rand() % 2;
    out->ni.pod_number      = rand() % 50;

	out->ls.result = rand() % 2;

    out->pi.session_id  = rand() % 10000;
    out->pi.pid         = rand() % 50000;
    out->pi.avg_latency = (float)(rand() % 100);
    out->pi.FPS         = 20 + (rand() % 60);

    printf("Successfully collected metrics\n");
}
/*-------------------------------------------------------------------------*/
