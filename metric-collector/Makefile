CC = gcc
CFLAGS = -O2 -g -Wall -Wextra
LDFLAGS = -lrdmacm -libverbs -lpthread

# include
INC = -I./include -I../rdma

SERVER_SRCS = src/server.c src/metric_api.c src/metrics_store.c ../rdma/rdma.c
CLIENT_SRCS = src/client.c src/metric_api.c src/metrics_store.c ../rdma/rdma.c
SERVER_OBJS = $(SERVER_SRCS:.c=.o)
CLIENT_OBJS = $(CLIENT_SRCS:.c=.o)
TARGET = server client

.PHONY: all clean

all: $(TARGET)

server: $(SERVER_OBJS)
	$(CC) -o $@ $^ $(LDFLAGS)

client: $(CLIENT_OBJS)
	$(CC) -o $@ $^ $(LDFLAGS)

%.o: %.c
	$(CC) $(CFLAGS) $(INC) -c $< -o $@

clean:
	rm -rf $(TARGET) src/*.o ../rdma/*.o
