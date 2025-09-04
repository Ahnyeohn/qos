#pragma once
/*-------------------------------------------------------------------------*/
#include <stddef.h>
#include <stdint.h>
/*-------------------------------------------------------------------------*/
#include "message.h"
/*-------------------------------------------------------------------------*/
#ifdef __cplusplus
extern "C" {
#endif
/*-------------------------------------------------------------------------*/
void metrics_store_init(int slots);
void metrics_store_update(metrics_t *out);
size_t metrics_store_render(char *out, size_t cap);
void* metrics_http_server(void *arg);
/*-------------------------------------------------------------------------*/
#ifdef __cplusplus
}
#endif
/*-------------------------------------------------------------------------*/
