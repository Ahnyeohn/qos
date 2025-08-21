#include "rdma.h"

pthread_t client_thread;
pthread_t worker_thread[NUM_QUEUES];

struct sockaddr_in c_addr;
struct sockaddr_in s_addr;
size_t length;

static void *process_client(void *arg)
{
    int ret = rdma_open_client(&s_addr, &c_addr, length);
    if (ret) {
        printf("rdma_open_client failed\n");
    }
    pthread_exit(NULL);
}

static void *process_worker(void *arg)
{
    int cpu = *(int *)arg;
    printf("[CPU %d]: start\n", cpu);

    int idx = 0;
    while (rdma_is_connected()) {
		printf("idx = %d\n", idx);
        
		metric_collect();

		if (send_lb_message(true, 0) == 0) {
			rdma_poll_cq(true, 0, 1);
		}

		idx++;
		if (idx >= 100) {
            break;
        }
    }

    pthread_exit(NULL);
}

static void get_addr(char *dst, struct sockaddr_in *addr)
{
    struct addrinfo *res;

    int ret = getaddrinfo(dst, NULL, NULL, &res);
    if (ret) {
        printf("getaddrinfo failed\n");
        exit(1);
    }

    if (res->ai_family == PF_INET) {
        memcpy(addr, res->ai_addr, sizeof(struct sockaddr_in));
    } else if (res->ai_family == PF_INET6) {
        memcpy(addr, res->ai_addr, sizeof(struct sockaddr_in6));
    } else {
        exit(1);
    }

    freeaddrinfo(res);
}

static void usage(void)
{
    printf("[Usage] : ");
    printf("./client [-c <client ip>] [-s <server ip>] [-p <port>] [-l <data size>]\n");
    exit(1);
}

int main(int argc, char* argv[])
{
    int option;

    while ((option = getopt(argc, argv, "c:s:p:l:")) != -1) {
        switch (option) {
            case 'c':
                get_addr(optarg, &c_addr);
                break;
            case 's':
                get_addr(optarg, &s_addr);
                break;
            case 'p':
                s_addr.sin_port = htons(strtol(optarg, NULL, 0));
                break;
            case 'l':
                length = strtol(optarg, NULL, 0);
                break;
            default:
                usage();
        }
    }

    if (!s_addr.sin_port || !s_addr.sin_addr.s_addr) {
        usage();
    }
    s_addr.sin_family = AF_INET;

    pthread_create(&client_thread, NULL, process_client, NULL);

    while (!rdma_is_connected()) { usleep(1000); }
    printf("Successfully connected\n");

    int cores[NUM_QUEUES];
    for (int i = 0; i < NUM_QUEUES; i++) {
        cores[i] = i;
        pthread_create(&worker_thread[i], NULL, process_worker, &cores[i]);
    }

    for (int i = 0; i < NUM_QUEUES; i++) {
        pthread_join(worker_thread[i], NULL);
    }

    rdma_done();
    pthread_join(client_thread, NULL);
    return 0;
}
