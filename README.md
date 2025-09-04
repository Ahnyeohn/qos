# QoS
## Structure
```markdown
qos/
│
├── metric-collector/
│   ├── src/
│   │   ├── metric_api.c
│   │   ├── prometheus.c
│   │   ├── server.c
│   │   └── client.c
│   │
│   ├── include/
│   │   ├── message.h
│   │   ├── prometheus.h
│   │   └── metric_api.h
│   │
│   ├── Makefile
│   ├── server_run.sh
│   └── client_run.sh
│
├── prometheus/
│   └── prometheus.yml
│
├── k8s-rdma/
│       ├── Dockerfile
│       ├── Makefile
│       ├── test-rdma-server.yaml
│       ├── test-rdma-client.yaml
│       ├── server-run.sh
│       ├── client-run.sh
│       ├── message.h
│       ├── metric_api.c
│       ├── metric_api.h
│       ├── prometheus.c
│       ├── prometheus.h
│       ├── server.c
│       └── client.c
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
