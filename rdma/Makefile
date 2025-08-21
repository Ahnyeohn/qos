.PHONY: clean

CFLAGS := -Wall -g -Werror
LDLIBS := ${LDLIBS} -lrdmacm -libverbs -lpthread
CC := gcc
MSG := @echo
HIDE := @

default: server client

%.o: %.c
	$(MSG) "	CC $<"
	$(HIDE) $(CC) -c $< $(CFLAGS) -o $@

server: server.o rdma.o
	$(MSG) "	LD $^"
	$(HIDE) $(CC) $^ -o $@ $(LDLIBS)

client: client.o rdma.o
	$(MSG) "	LD $^"
	$(HIDE) $(CC) $^ -o $@ $(LDLIBS)

clean:
	$(MSG) "	CLEAN server client"
	$(HIDE) rm -f server client *.o
