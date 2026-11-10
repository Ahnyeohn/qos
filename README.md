this directory covers mediasoup with k8s setting

mediasoup is consist of mediasoup and mediasoup-demo

mediasoup demo has 2 parts, mediasoup-server and mediasoup-app
mediasoup-server: WebRTC SFU
mediasoup-app: client web server to connect SFU

In mediasoup-server and app, there is a configuration file that sets the mode of the SFU you want to operate.
server: mediasoup-demo/server/mode_config.json
app: mediasoup-demo/app/public/config.js

# mediasoup Docker / Kubernetes Commands

## Edge Server

```bash
cd ~/yeon/qos/network

docker build \
  -f mediasoup-demo/server/Dockerfile \
  -t ghcr.io/ahnyeohn/mediasoup-server-edge:v2 \
  .

docker push ghcr.io/ahnyeohn/mediasoup-server-edge:v2

kubectl -n qos rollout restart statefulset mediasoup-edge
kubectl -n qos rollout status statefulset mediasoup-edge

kubectl -n qos get pods -o wide
```

---

## Edge App

```bash
cd ~/yeon/qos/network

docker build \
  -f mediasoup-demo/app/Dockerfile \
  -t ghcr.io/ahnyeohn/mediasoup-app-edge:v2 \
  .

docker push ghcr.io/ahnyeohn/mediasoup-app-edge:v2

kubectl -n qos rollout restart statefulset mediasoup-edge
kubectl -n qos rollout status statefulset mediasoup-edge

kubectl -n qos get pods -o wide
```

---

## Origin Server

```bash
cd ~/yeon/qos/network

docker build --network=host \
  -f mediasoup-demo/server/Dockerfile \
  -t ghcr.io/ahnyeohn/mediasoup-server-origin:v2 \
  .

docker push ghcr.io/ahnyeohn/mediasoup-server-origin:v2

kubectl -n qos rollout restart deployment mediasoup-origin
kubectl -n qos rollout status deployment mediasoup-origin

kubectl -n qos get pods -o wide
```

---

## Origin App

```bash
cd ~/yeon/qos/network

docker build --network=host \
  -f mediasoup-demo/app/Dockerfile \
  -t ghcr.io/ahnyeohn/mediasoup-app-origin:v2 \
  .

docker push ghcr.io/ahnyeohn/mediasoup-app-origin:v2

kubectl -n qos rollout restart deployment mediasoup-origin
kubectl -n qos rollout status deployment mediasoup-origin

kubectl -n qos get pods -o wide
```

---

## Edge Server + App

```bash
cd ~/yeon/qos/network

docker build \
  -f mediasoup-demo/server/Dockerfile \
  -t ghcr.io/ahnyeohn/mediasoup-server-edge:v2 \
  .

docker build \
  -f mediasoup-demo/app/Dockerfile \
  -t ghcr.io/ahnyeohn/mediasoup-app-edge:v2 \
  .

docker push ghcr.io/ahnyeohn/mediasoup-server-edge:v2
docker push ghcr.io/ahnyeohn/mediasoup-app-edge:v2

kubectl -n qos rollout restart statefulset mediasoup-edge
kubectl -n qos rollout status statefulset mediasoup-edge

kubectl -n qos get pods -o wide
```

---

## Origin Server + App

```bash
cd ~/yeon/qos/network

docker build --network=host \
  -f mediasoup-demo/server/Dockerfile \
  -t ghcr.io/ahnyeohn/mediasoup-server-origin:v2 \
  .

docker build --network=host \
  -f mediasoup-demo/app/Dockerfile \
  -t ghcr.io/ahnyeohn/mediasoup-app-origin:v2 \
  .

docker push ghcr.io/ahnyeohn/mediasoup-server-origin:v2
docker push ghcr.io/ahnyeohn/mediasoup-app-origin:v2

kubectl -n qos rollout restart deployment mediasoup-origin
kubectl -n qos rollout status deployment mediasoup-origin

kubectl -n qos get pods -o wide
```

---

## Pod Logs

### Edge Server

```bash
kubectl -n qos logs mediasoup-edge-0 -c mediasoup-server -f
```

### Edge App

```bash
kubectl -n qos logs mediasoup-edge-0 -c mediasoup-app -f
```

### Pod List

```bash
kubectl -n qos get pods -o wide
```

---

## Edge Replica Scale

### 2 Replicas

```bash
kubectl -n qos scale statefulset mediasoup-edge --replicas=2
```

### 4 Replicas

```bash
kubectl -n qos scale statefulset mediasoup-edge --replicas=4
```

### Status

```bash
kubectl -n qos get statefulset mediasoup-edge
```

---

## Image Check

### Edge

```bash
kubectl -n qos get statefulset mediasoup-edge \
  -o jsonpath='{range .spec.template.spec.containers[*]}{.name}{" => "}{.image}{"\n"}{end}'
```

### Origin

```bash
kubectl -n qos get deployment mediasoup-origin \
  -o jsonpath='{range .spec.template.spec.containers[*]}{.name}{" => "}{.image}{"\n"}{end}'
```
