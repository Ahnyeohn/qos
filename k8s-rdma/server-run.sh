#!/bin/bash

SERVER_IP="192.168.100.160"
PORT=12345

echo "Server IP: $SERVER_IP"

./rdma_server -p "$PORT"
