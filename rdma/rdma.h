#ifndef RDMA_H
#define RDMA_H

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <getopt.h>
#include <pthread.h>

#include <netdb.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <sys/socket.h>

#include <rdma/rdma_cma.h>
#include <infiniband/verbs.h>

#define true 1
#define false 0

#define NUM_QUEUES 1

#define CONNECTION_TIMEOUT_MS 2000
#define CQ_CAPACITY 128
#define MAX_SGE 32       /* SGE 개수 */
#define MAX_WR  64       /* WR 개수  */

#define PAGE_SIZE 4096

/* (선택) 원격 접근용 정보가 필요할 때 사용 가능 (지금 예제에선 사용 안 함) */
struct rdma_buffer {
    uint64_t addr;
    uint64_t length;
    uint32_t rkey;
};

struct rdma_device;

struct rdma_queue {
    struct rdma_cm_id *cm_id; /* connection id (queue id) */
    struct ibv_qp *qp;
    struct ibv_cq *cq;

    /* 큐 별 MR/버퍼 (공유 금지) */
    struct ibv_mr *mr;
    char *buf;
    size_t buf_len;

    int connected; /* ESTABLISHED 이후 1, DISCONNECTED 시 0 */

    struct rdma_device *rdma_dev;
};

struct rdma_device {
    /* 클라이언트: 큐별 이벤트 채널 / 서버: ec[0]만 사용 */
    struct rdma_event_channel *ec[NUM_QUEUES];
    /* 서버: cm_id[0]는 listen id, 클라: 큐별 cm_id */
    struct rdma_cm_id *cm_id[NUM_QUEUES];
    struct ibv_comp_channel *cc[NUM_QUEUES];

    struct ibv_pd *pd;
    struct ibv_context *verbs;
    int status; /* 1이면 최소 한 연결이 성립됨 */

    struct rdma_queue *queues[NUM_QUEUES];
    int queue_ctr; /* 다음 연결을 넣을 후보 인덱스(서버/클라 공통 단순관리용) */

    size_t default_buf_len; /* 큐별 MR 생성 시 기본 길이 */

    pthread_mutex_t lock; /* 큐/상태 보호용 */
};
extern struct rdma_device *rdma_dev;

int rdma_open_server(struct sockaddr_in *, size_t);
int rdma_open_client(struct sockaddr_in *, struct sockaddr_in *, size_t);
void rdma_close_device(void);

int rdma_is_connected(void);
void rdma_done(void);

int rdma_poll_cq(int, int, int);
int rdma_recv_wr(int, int, size_t);
int rdma_send_wr(int, int, size_t);

struct rdma_queue *get_queue(int, int);

#endif
