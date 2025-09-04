CC = gcc
CFLAGS = -O2 -Wall -Wextra -pthread
LDFLAGS = -lrdmacm -libverbs -pthread

INC = -I.

SERVER_SRCS = server.c metric_api.c prometheus.c
CLIENT_SRCS = client.c metric_api.c
SERVER_OBJS = $(SERVER_SRCS:.c=.o)
CLIENT_OBJS = $(CLIENT_SRCS:.c=.o)

all: rdma_server rdma_client

rdma_server: $(SERVER_OBJS)
	$(CC) -o $@ $^ $(LDFLAGS)

rdma_client: $(CLIENT_OBJS)
	$(CC) -o $@ $^ $(LDFLAGS)

%.o: %.c
	$(CC) $(CFLAGS) $(INC) -c $< -o $@

clean:
	rm -f rdma_server rdma_client *.o
