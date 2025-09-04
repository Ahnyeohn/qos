#!/bin/bash

MY_IP=$(ip -4 addr show net1 | grep -oP '(?<=inet\s)\d+(\.\d+){3}')

SERVER_IP="192.168.100.160"
PORT=12345

echo "Client IP: $MY_IP"
echo "Server IP: $SERVER_IP"

#for i in $(seq 1 100); do
#	echo "msg $i from client($MY_IP)" | ./rdma_client -s "$SERVER_IP" -p "$PORT"
#	sleep 1
#done

./rdma_client -s "$SERVER_IP" -p "$PORT"
