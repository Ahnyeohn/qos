#!/bin/bash

SERVER_IP="192.168.100.160"
PORT=12345

./rdma_client -s "$SERVER_IP" -p "$PORT"
