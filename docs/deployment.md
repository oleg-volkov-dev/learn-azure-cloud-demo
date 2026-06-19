# Azure Deployment Walkthrough

End-to-end guide: local dev → Docker → Azure Container Registry → Azure Container Apps.

## Prerequisites

- Python 3.11+
- Docker Desktop
- An Azure account (free tier works)
- Azure CLI installed into a venv (see Step 1)

---

## Step 1 — Environment setup

```bash
python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install azure-cli
pip install -r requirements.txt
```

Verify:
```bash
az --version
docker --version
```

---

## Step 2 — Run and test locally

```bash
uvicorn app.main:app --port 8000 &
sleep 2

curl http://localhost:8000/health

curl -s -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"amount": 850, "country": "NG", "card_present": false}'

kill %1
```

Swagger UI: http://localhost:8000/docs

---

## Step 3 — Log in to Azure

```bash
az login
```

---

## Step 4 — Set variables

```bash
RESOURCE_GROUP=rg-fraud-demo
LOCATION=westus2
ACR_NAME=frauddemoacr$RANDOM
IMAGE_NAME=fraud-api
IMAGE_TAG=v1.2.0
CONTAINER_APP_ENV=fraud-env
CONTAINER_APP_NAME=fraud-api
```

Note the printed `ACR_NAME` — you'll need it if you open a new terminal session:
```bash
echo $ACR_NAME
```

---

## Step 5 — Register Azure providers (first-time only)

New accounts need these enabled before use:

```bash
az provider register --namespace Microsoft.ContainerRegistry
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
az provider register --namespace Microsoft.ContainerService
```

Check until all say `Registered` (takes ~1 minute each):

```bash
az provider show --namespace Microsoft.ContainerRegistry --query registrationState -o tsv
az provider show --namespace Microsoft.App --query registrationState -o tsv
az provider show --namespace Microsoft.OperationalInsights --query registrationState -o tsv
```

---

## Step 6 — Create Resource Group

```bash
az group create --name $RESOURCE_GROUP --location $LOCATION
```

---

## Step 7 — Create Azure Container Registry

```bash
az acr create \
  --resource-group $RESOURCE_GROUP \
  --name $ACR_NAME \
  --sku Basic \
  --admin-enabled true
```

---

## Step 8 — Build and push image

> Note: `az acr build` (remote build) is disabled on free-tier subscriptions. Build locally instead.

```bash
# Authenticate Docker to ACR
az acr login --name $ACR_NAME

# Get the registry address
ACR_LOGIN_SERVER=$(az acr show --name $ACR_NAME --query loginServer -o tsv)

# Build for linux/amd64 (required — Azure runs on AMD64, not ARM)
docker buildx build \
  --platform linux/amd64 \
  -t $ACR_LOGIN_SERVER/$IMAGE_NAME:$IMAGE_TAG \
  --push \
  .
```

Verify the image landed:
```bash
az acr repository show-tags --name $ACR_NAME --repository $IMAGE_NAME -o tsv
```

---

## Step 9 — Create Container Apps environment

```bash
az extension add --name containerapp --upgrade

az containerapp env create \
  --name $CONTAINER_APP_ENV \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION
```

Takes ~2 minutes. Azure auto-creates a Log Analytics workspace for logs.

---

## Step 10 — Deploy

```bash
ACR_LOGIN_SERVER=$(az acr show --name $ACR_NAME --query loginServer -o tsv)
ACR_PASSWORD=$(az acr credential show --name $ACR_NAME --query "passwords[0].value" -o tsv)

az containerapp create \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --environment $CONTAINER_APP_ENV \
  --image $ACR_LOGIN_SERVER/$IMAGE_NAME:$IMAGE_TAG \
  --registry-server $ACR_LOGIN_SERVER \
  --registry-username $ACR_NAME \
  --registry-password $ACR_PASSWORD \
  --target-port 8000 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 3 \
  --cpu 0.5 \
  --memory 1.0Gi
```

---

## Step 11 — Get the public URL

```bash
APP_URL=$(az containerapp show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query properties.configuration.ingress.fqdn -o tsv)

echo "https://$APP_URL"
```

---

## Step 12 — Test live endpoints

```bash
curl https://$APP_URL/health

curl -s -X POST https://$APP_URL/predict \
  -H "Content-Type: application/json" \
  -d '{"amount": 25.00, "country": "US", "card_present": true}'

curl -s -X POST https://$APP_URL/predict \
  -H "Content-Type: application/json" \
  -d '{"amount": 850.00, "country": "NG", "card_present": false}'
```

Swagger UI: `https://$APP_URL/docs`

---

## Step 13 — Check logs

```bash
az containerapp logs show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --follow
```

---

## Step 14 — Tear down (avoid charges)

```bash
az group delete --name $RESOURCE_GROUP --yes --no-wait
```

This deletes the Resource Group and everything inside it (ACR, Container App, Log Analytics workspace).

---

## Gotchas encountered

| Issue | Fix |
|-------|-----|
| `MissingSubscriptionRegistration` on ACR create | Register the provider first: `az provider register --namespace Microsoft.ContainerRegistry` |
| `TasksOperationsNotAllowed` on `az acr build` | Free-tier restriction — build locally with `docker buildx build --platform linux/amd64 --push` instead |
| `zsh: no matches found: passwords[0].value` | Zsh glob expansion — always quote the JMESPath query: `--query "passwords[0].value"` |
| `no child with platform linux/amd64 in index` | Mac is ARM — must pass `--platform linux/amd64` to buildx |
| curl fires before uvicorn is ready | Add `sleep 2` between starting uvicorn in the background and the first curl |

---

## Production hardening notes

### Identity & secrets

| Topic | Approach |
|-------|----------|
| **Managed Identity** | Assign a system-assigned managed identity to the Container App. Replace `--registry-username/--registry-password` with an `AcrPull` role grant on the identity. No credentials stored anywhere. |
| **Azure Key Vault** | Store thresholds, model URIs, and third-party API keys in Key Vault. Access at runtime via the Key Vault SDK using the managed identity. |
| **RBAC** | `AcrPull` for the app identity, `AcrPush` only for the CI service principal. Minimum scope, always. |

### Observability

| Topic | Approach |
|-------|----------|
| **Structured logging** | Emit JSON log lines (use `python-json-logger`) so Log Analytics can parse fields without regex. Never log raw request bodies or PII. |
| **Azure Monitor / Log Analytics** | Container Apps environment auto-wires to Log Analytics. Query with KQL against `ContainerAppConsoleLogs_CL`. |
| **OpenTelemetry** | Instrument with `opentelemetry-sdk` + Azure Monitor exporter. Emit traces per request and a `fraud_score` histogram. Wire to Application Insights. |
| **p95 / p99 latency** | Application Insights metric alert: if p99 > 200 ms for 5 minutes, page on-call. Fraud scoring SLAs are tight. |

### CI/CD

```
GitHub push → GitHub Actions:
  1. pytest
  2. Trivy image scan
  3. docker buildx build --platform linux/amd64 --push (tagged with Git SHA)
  4. az containerapp update --image ...:$SHA
  5. Smoke-test /health on the new revision
  6. If failed → az containerapp revision deactivate (instant rollback)
```

### Deployment safety

| Topic | Approach |
|-------|----------|
| **Canary** | Container Apps supports per-revision traffic weights. Deploy new image as a second revision, send 10% traffic, monitor for 10 min, then promote or roll back. |
| **Rollback** | Every image tagged with Git SHA. Roll back with `az containerapp update --image ...<previous-SHA>`. |
| **Image scanning** | Trivy in CI (`--exit-code 1 --severity HIGH,CRITICAL`). Defender for Containers on the registry for continuous assessment. |
| **Autoscaling** | KEDA HTTP scaler: scale out when concurrent requests > 50, scale in after 5 min idle. |

### Model artifact versioning

| Topic | Approach |
|-------|----------|
| **Registry** | Register each model version in Azure ML model registry. Bake version into image at build time. |
| **Image tag strategy** | `<image>:<model-version>-<git-sha>` (e.g. `fraud-api:v1.2.0-a3f9c2b`). Unambiguous which model is running and enables exact rollback. |
| **Feature drift** | Weekly batch job computing PSI/KS statistics on live traffic. Alert when drift exceeds threshold. |
