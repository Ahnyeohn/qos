#include "rdma.h"
#include "metric_api.h"
/*-------------------------------------------------------------------------*/
struct sockaddr_in s_addr;
struct sockaddr_in c_addr;
size_t length;
/*-------------------------------------------------------------------------*/
static void *process_client(void *arg)
{
    int ret = rdma_open_client(&s_addr, &c_addr, length);
    if (ret) {
        printf("rdma_open_client failed\n");
    }
}
/*-------------------------------------------------------------------------*/
static void process_worker(int cpu)
{
    printf("[CPU %d]: start\n", cpu);

    int idx = 0;
    while (rdma_is_connected()) {
        printf("%d: send req %d!\n", cpu, idx);
        rdma_send_wr(false, cpu, length);
        rdma_poll_cq(false, cpu, 1);
        printf("%d: send done %d!\n", cpu, idx++);

        if (idx >= 100) {
            break;
        }
    }
}
/*-------------------------------------------------------------------------*/
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
/*-------------------------------------------------------------------------*/
static void usage(void)
{
    printf("[Usage] : ");
    printf("./client [-c <client ip>] [-s <server ip>] [-p <port>] [-l <data size>]\n");
    exit(1);
}
/*-------------------------------------------------------------------------*/
int main (int argc, char* argv[])
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

	while (!rdma_is_connected());

	printf("Successfully connected\n");

	int cpu_id = 0;
	process_worker(&cpu_id);

	rdma_done();

	return 0;
}
/*-------------------------------------------------------------------------*/
