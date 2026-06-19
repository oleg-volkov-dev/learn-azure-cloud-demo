# AKS Deployment Walkthrough

Deploy the fraud-api to Azure Kubernetes Service (AKS). This tutorial assumes you already
completed `deployment.md` through Step 8 (image pushed to ACR). The same image and resource
group are reused here.

This is to explore the AKS functionality on Azure cloud.

---

## Prerequisites

- Completed `deployment.md` Steps 1–8 (ACR exists, image is pushed)
- Variables from that session still set, or re-export them:

```bash
RESOURCE_GROUP=rg-fraud-demo
LOCATION=eastus
ACR_NAME=<your-acr-name>        # the one with the random suffix, check: az acr list -o table
IMAGE_NAME=fraud-api
IMAGE_TAG=v1.2.0
ACR_LOGIN_SERVER=$(az acr show --name $ACR_NAME --query loginServer -o tsv)
```

---

## Concept map before you start

```
Internet
   │
   ▼
Ingress (front door — routes HTTP to the right Service)
   │
   ▼
Service (stable internal address for a group of Pods)
   │
   ▼
Pods (your actual containers — Deployment keeps N of them alive)
   │
   ▼
ACR (where Kubernetes pulls the image from)
```

Everything you do below builds one layer of this diagram at a time.

---

## Step 1 — Register the AKS provider

```bash
az provider register --namespace Microsoft.ContainerService

# Wait until this says "Registered"
az provider show --namespace Microsoft.ContainerService --query registrationState -o tsv
```

---

## Step 2 — Create the AKS cluster

```bash
AKS_NAME=fraud-aks

az aks create \
  --resource-group $RESOURCE_GROUP \
  --name $AKS_NAME \
  --node-count 2 \
  --node-vm-size Standard_B2s \
  --attach-acr $ACR_NAME \
  --generate-ssh-keys \
  --enable-managed-identity
```

**What just happened:**
- `--node-count 2` — two virtual machines (called "nodes") that will run your pods
- `--node-vm-size Standard_B2s` — small, cheap VMs (2 CPU, 4 GB RAM each)
- `--attach-acr` — grants the cluster permission to pull images from your registry, no password needed
- `--enable-managed-identity` — the cluster authenticates to Azure services using its own identity, not your credentials
- `--generate-ssh-keys` — creates SSH keys so you could log into a node if needed

Takes ~5 minutes. Grab a coffee.

---

## Step 3 — Connect kubectl to your cluster

`kubectl` is the command-line tool for Kubernetes — like `az` is for Azure.

```bash
az aks get-credentials --resource-group $RESOURCE_GROUP --name $AKS_NAME
```

This writes a config file (`~/.kube/config`) so `kubectl` knows which cluster to talk to.

Verify it works:
```bash
kubectl get nodes
```

You should see 2 nodes with status `Ready`.

---

## Step 4 — Create a Namespace

A namespace is a folder inside the cluster. It keeps your app's resources separate from
anything else running in the cluster (like system components).

```bash
kubectl create namespace fraud
```

Verify:
```bash
kubectl get namespaces
```

---

## Step 5 — Write the Kubernetes manifests

Create a directory for your manifests:
```bash
mkdir -p k8s
```

### 5a — Deployment (`k8s/deployment.yaml`)

A Deployment tells Kubernetes: "keep 2 copies of this container running at all times."
If a pod crashes, Kubernetes automatically starts a replacement.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fraud-api
  namespace: fraud
spec:
  replicas: 2
  selector:
    matchLabels:
      app: fraud-api
  template:
    metadata:
      labels:
        app: fraud-api
    spec:
      containers:
        - name: fraud-api
          image: PLACEHOLDER_ACR_LOGIN_SERVER/fraud-api:v1.2.0   # replaced below
          ports:
            - containerPort: 8000
          resources:
            requests:
              cpu: "250m"       # 0.25 of one CPU core
              memory: "256Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"
          livenessProbe:        # Kubernetes restarts the pod if this fails 3 times
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 15
          readinessProbe:       # Kubernetes only sends traffic once this passes
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
```

Replace the image placeholder with your actual ACR address:
```bash
sed -i '' "s|PLACEHOLDER_ACR_LOGIN_SERVER|$ACR_LOGIN_SERVER|g" k8s/deployment.yaml
```

**Key concepts in this file:**
- `replicas: 2` — always 2 pods running
- `selector` / `labels` — how Kubernetes matches a Service to these pods (think of it as a tag)
- `resources.requests` — the minimum resources Kubernetes reserves for this pod on a node
- `resources.limits` — the maximum it can use before being throttled/killed
- `livenessProbe` — Kubernetes hits `/health` every 15 seconds; 3 failures = pod restart
- `readinessProbe` — pod won't receive traffic until `/health` returns 200

### 5b — Service (`k8s/service.yaml`)

Pods come and go — they get new IP addresses every time they restart. A Service gives them
a stable address that never changes.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: fraud-api
  namespace: fraud
spec:
  selector:
    app: fraud-api        # targets any pod with this label
  ports:
    - protocol: TCP
      port: 80            # the port the Service listens on inside the cluster
      targetPort: 8000    # forwarded to this port on the pod
  type: ClusterIP         # internal only — Ingress will expose it to the internet
```

### 5c — Ingress (`k8s/ingress.yaml`)

The Ingress is the front door. It receives HTTP traffic from outside the cluster and routes
it to the right Service.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: fraud-api
  namespace: fraud
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  ingressClassName: nginx
  rules:
    - http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: fraud-api
                port:
                  number: 80
```

### 5d — Horizontal Pod Autoscaler (`k8s/hpa.yaml`)

Automatically adds pods when CPU usage is high, removes them when load drops.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: fraud-api
  namespace: fraud
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: fraud-api
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60    # scale out when average CPU > 60%
```

---

## Step 6 — Install the NGINX Ingress Controller

The Ingress manifest above is just a config file. Something needs to actually run and
act on it — that's the Ingress Controller. NGINX is the most common one.

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.1/deploy/static/provider/cloud/deploy.yaml
```

Wait for it to be ready:
```bash
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s
```

---

## Step 7 — Apply all manifests

```bash
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml
kubectl apply -f k8s/hpa.yaml
```

Check everything is coming up:
```bash
kubectl get pods -n fraud
kubectl get service -n fraud
kubectl get ingress -n fraud
```

Pods should reach `Running` state within ~30 seconds.

---

## Step 8 — Get the public IP

The NGINX Ingress Controller gets a public Load Balancer IP from Azure. It takes ~1 minute
to provision.

```bash
kubectl get service -n ingress-nginx ingress-nginx-controller
```

Wait until `EXTERNAL-IP` shows an actual IP address (not `<pending>`), then:

```bash
INGRESS_IP=$(kubectl get service -n ingress-nginx ingress-nginx-controller \
  --output jsonpath='{.status.loadBalancer.ingress[0].ip}')

echo $INGRESS_IP
```

---

## Step 9 — Test the live endpoints

```bash
curl http://$INGRESS_IP/health

curl -s -X POST http://$INGRESS_IP/predict \
  -H "Content-Type: application/json" \
  -d '{"amount": 25.00, "country": "US", "card_present": true}'

curl -s -X POST http://$INGRESS_IP/predict \
  -H "Content-Type: application/json" \
  -d '{"amount": 850.00, "country": "NG", "card_present": false}'
```

Swagger UI: `http://$INGRESS_IP/docs`

---

## Step 10 — Observe the cluster

These are the commands you'll use constantly when operating Kubernetes:

```bash
# See all pods and which node they're on
kubectl get pods -n fraud -o wide

# Tail logs from all fraud-api pods at once
kubectl logs -n fraud -l app=fraud-api -f

# See resource usage per pod (requires metrics-server — installed by default on AKS)
kubectl top pods -n fraud

# Describe a pod (events, image, probes, resource limits)
kubectl describe pod -n fraud <pod-name>

# See HPA status — current vs target replicas
kubectl get hpa -n fraud

# See all events in the namespace (useful for debugging)
kubectl get events -n fraud --sort-by='.lastTimestamp'
```

---

## Step 11 — Perform a rolling update

Change the image tag to simulate deploying a new version. Kubernetes replaces pods one at a
time so there is no downtime.

```bash
kubectl set image deployment/fraud-api \
  fraud-api=$ACR_LOGIN_SERVER/$IMAGE_NAME:v1.2.0 \
  -n fraud

# Watch the rollout happen live
kubectl rollout status deployment/fraud-api -n fraud
```

Roll back if something goes wrong:
```bash
kubectl rollout undo deployment/fraud-api -n fraud
```

---

## Step 12 — Tear down (avoid charges)

AKS clusters cost money even when idle. Delete when done:

```bash
az group delete --name $RESOURCE_GROUP --yes --no-wait
```

This deletes the cluster, nodes, load balancer, and ACR — everything in the resource group.

---

## What you practiced

| Kubernetes concept | Where you used it |
|---|---|
| Namespace | Step 4 — isolated your app from cluster internals |
| Deployment | Step 5a — declared desired state (2 replicas, health probes) |
| Service | Step 5b — gave pods a stable internal address |
| Ingress | Step 5c — exposed the app to the internet |
| HPA | Step 5d — automatic scaling based on CPU |
| kubectl | Steps 7–11 — applied manifests, checked status, tailed logs |
| Rolling update | Step 11 — zero-downtime deploy |
| Rollback | Step 11 — instant revert to last working version |

---

## AKS vs Container Apps — when to use which

| | Container Apps | AKS |
|---|---|---|
| Setup time | ~2 min | ~10 min |
| You manage nodes | No | Yes |
| Full Kubernetes API | No | Yes |
| Custom Ingress rules | Limited | Full control |
| Learning value | Low | High |
| Good for | Simple services, quick deploys | Learning K8s, complex routing, multi-team clusters |
