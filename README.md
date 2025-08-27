# QoS
## Structure
```markdown
qos/
│
├── rdma/
│   ├── rdma.c
│   └── rdma.h
│
├── metric-collector/
│   ├── src/
│   │   ├── metric_api.c
│   │   ├── server.c
│   │   └── client.c
│   │
│   ├── include/
│   │   ├── message.h
│   │   └── metric_api.h
│   │
│   ├── server_run.sh
│   └── client_run.sh
│
├── prometheus/
│   └── prometheus.yml
│
└── README.md
```
## Run Server
- You need to modify server's IP address.
```
./server_run.sh
```
## Run Client
- You need to modify client's IP address.
```
./client_run.sh
```
## Prometheus
- You need to modify `prometheus.yml` to set the correct target address.
- Run Prometheus
```
curl http://<your prometheus ip>:9123/gpu_metrics
```
