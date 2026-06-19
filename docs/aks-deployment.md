# AKS Deployment

Deploying the fraud-api to Azure Kubernetes Service as a follow-up to the Container Apps deployment in `deployment.md`. Same image and resource group, different orchestration layer — the goal here was to get hands-on with real Kubernetes rather than the managed abstraction Container Apps provides.

Manifests are in [`k8s/`](../k8s/).

---

## How it fits together

```
Internet
   │
   ▼
Ingress  (NGINX — routes HTTP into the cluster)
   │
   ▼
Service  (stable internal address, load balances across pods)
   │
   ▼
Pods     (the actual containers, managed by a Deployment)
   │
   ▼
ACR      (where Kubernetes pulls the image from)
```

---

## Setup

Re-export variables if starting a new session:

```bash
RESOURCE_GROUP=rg-fraud-demo
LOCATION=eastus
AKS_NAME=fraud-aks
ACR_NAME=<your-acr-name>
IMAGE_NAME=fraud-api
IMAGE_TAG=v1.2.0
ACR_LOGIN_SERVER=$(az acr show --name $ACR_NAME --query loginServer -o tsv)
```

Check the ACR name if you forgot it:
```bash
az acr list -o table
```

---

## Cluster

Register the provider if not already done:
```bash
az provider register --namespace Microsoft.ContainerService
az provider show --namespace Microsoft.ContainerService --query registrationState -o tsv
```

Create the cluster:
```bash
az aks create \
  --resource-group $RESOURCE_GROUP \
  --name $AKS_NAME \
  --node-count 1 \
  --node-vm-size Standard_D2ds_v7 \
  --attach-acr $ACR_NAME \
  --generate-ssh-keys \
  --enable-managed-identity
```

Takes about 5 minutes. `--attach-acr` grants the cluster permission to pull from the registry without credentials. `--enable-managed-identity` means the cluster authenticates to Azure as itself rather than using your account.

Connect kubectl:
```bash
az aks get-credentials --resource-group $RESOURCE_GROUP --name $AKS_NAME
kubectl get nodes
```

---

## Namespace

```bash
kubectl create namespace fraud
kubectl get namespaces
```

---

## Manifests

Apply everything from the `k8s/` directory. Before applying `deployment.yaml`, replace the image placeholder with your actual ACR address:

```bash
sed -i '' "s|PLACEHOLDER_ACR_LOGIN_SERVER|$ACR_LOGIN_SERVER|g" k8s/deployment.yaml
```

Install the NGINX ingress controller first:
```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.1/deploy/static/provider/cloud/deploy.yaml

kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s
```

Then apply the app manifests:
```bash
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml
kubectl apply -f k8s/hpa.yaml
```

Check status:
```bash
kubectl get pods -n fraud
kubectl get service -n fraud
kubectl get ingress -n fraud
```

---

## Getting the public IP

The ingress controller provisions an Azure Load Balancer. Takes about a minute for `EXTERNAL-IP` to stop showing `<pending>`:

```bash
kubectl get service -n ingress-nginx ingress-nginx-controller

INGRESS_IP=$(kubectl get service -n ingress-nginx ingress-nginx-controller \
  --output jsonpath='{.status.loadBalancer.ingress[0].ip}')
```

Test it:
```bash
curl http://$INGRESS_IP/health

curl -s -X POST http://$INGRESS_IP/predict \
  -H "Content-Type: application/json" \
  -d '{"amount": 850.00, "country": "NG", "card_present": false}'
```

---

## Useful kubectl commands

```bash
kubectl get pods -n fraud -o wide
kubectl logs -n fraud -l app=fraud-api -f
kubectl top pods -n fraud
kubectl describe pod -n fraud <pod-name>
kubectl get hpa -n fraud
kubectl get events -n fraud --sort-by='.lastTimestamp'
```

Rolling update and rollback:
```bash
kubectl set image deployment/fraud-api fraud-api=$ACR_LOGIN_SERVER/$IMAGE_NAME:v1.2.0 -n fraud
kubectl rollout status deployment/fraud-api -n fraud
kubectl rollout undo deployment/fraud-api -n fraud
```

---

## Tear down

```bash
az group delete --name $RESOURCE_GROUP --yes --no-wait
```

AKS also creates a second resource group (`MC_rg-fraud-demo_fraud-aks_eastus`) for the actual VM infrastructure. Deleting the main resource group takes it down too, but the whole process takes 15-20 minutes.

---

## Gotchas

**`Standard_B2s` not available on free-tier subscriptions in eastus**
The tutorial originally used `Standard_B2s` but that VM size is restricted on free subscriptions. Had to switch to `Standard_D2ds_v7` — slightly more expensive (2 vCPU, 8 GB RAM) but the smallest available option that worked.

**1 node is enough for learning**
Originally planned 2 nodes but 1 is fine for a single-app learning setup. Spreading pods across nodes is a production concern, not needed here.

**`eastus` capacity issues**
Ran into `AKSCapacityHeavyUsage` errors during the Container Apps part of this project. For AKS the cluster came up fine in eastus, but if it fails try `westus2` or `eastus2`.

**AKS creates a hidden resource group**
When you create a cluster, Azure auto-creates an `MC_<rg>_<cluster>_<region>` resource group containing the actual VMs, disks, network interfaces, and load balancer. You don't manage it directly but it's good to know it exists — it shows up in the portal and contributes to the bill.

**`--no-wait` on delete doesn't mean instant**
Deleting the resource group with `--no-wait` returns the terminal immediately but Azure still takes 15-20 minutes to fully tear everything down. The `MC_` group has to go first.

**Ctrl+C on a long `az` command doesn't cancel the Azure operation**
The CLI process stops locally but Azure keeps executing the request server-side. Ran into this during Container Apps setup — the environment stayed in a locked `InProgress` state and had to wait it out before retrying.
