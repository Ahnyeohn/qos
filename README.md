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
