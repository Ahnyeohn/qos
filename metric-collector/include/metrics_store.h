#pragma once

#include <stddef.h>
#include <stdint.h>
#include <stdint.h>
#include "message.h"

#ifdef __cplusplus
extern "C" {
#endif

void metrics_store_init(int slots);
void metrics_store_update(int slot, const app_info* ai, const node_info* ni, const lb_signal* ls, const perf_info* pi);
size_t metrics_store_render(char *out, size_t cap); // prometheus 텍스트 출력
void* metrics_http_server(void *arg); // (int*) arg = 포트 번호

#ifdef __cplusplus
}
#endif
