#!/bin/bash

#SERVER_IP="192.168.100.160"
SERVER_IP="10.20.1.11"
PORT=12345

./rdma_client -s "$SERVER_IP" -p "$PORT"
