/*-------------------------------------------------------------------------*/
#include "rdma.h"
/*-------------------------------------------------------------------------*/
pthread_t server_thread;
pthread_t worker_thread[NUM_QUEUES];
/*-------------------------------------------------------------------------*/
struct sockaddr_in s_addr;
size_t length;
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

    int idx = 0;
    while (rdma_is_connected()) {
        printf("%d: rcv req %d!\n", cpu, idx);
        rdma_recv_wr(false, cpu, length);
        rdma_poll_cq(false, cpu, 1);
        printf("%d: rcv done %d!\n", cpu, idx++);

        if (idx >= 100) {
            break;
        }
    }

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
int main (int argc, char* argv[])
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
	while (!rdma_is_connected());

	printf("Successfully connected\n");

	int cores[NUM_QUEUES];
	for (int i = 0; i < NUM_QUEUES; i++) {
		cores[i] = i;
		pthread_create(&worker_thread[i], NULL, process_worker, &cores[i]);
	}

	pthread_join(server_thread, NULL);
	return 0;
}
/*-------------------------------------------------------------------------*/
