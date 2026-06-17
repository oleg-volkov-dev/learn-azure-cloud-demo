# learn-azure-cloud-demo

A minimal real-time fraud-scoring API built with FastAPI, containerized with Docker, and deployed through **Azure Container Registry → Azure Container Apps**. The purpose is to demonstrate a practical Azure MLOps deployment flow and the production considerations that come with it.

> No real ML model is used. The scorer is a deterministic rule-based function that mimics a versioned model artefact, which is enough to exercise the full deployment pipeline.

---

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Service liveness check and model version |
| `POST` | `/predict` | Score a transaction for fraud |

### `POST /predict` — request body

```json
{
  "amount": 350.00,
  "country": "NG",
  "card_present": false
}
```

### `POST /predict` — response

```json
{
  "fraud_score": 0.6,
  "model_version": "v1.2.0"
}
```

`fraud_score` is a probability in `[0, 1]`. Scores ≥ 0.5 would typically trigger a review queue or hard decline, depending on the business rule.

---

## Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Swagger UI: http://localhost:8000/docs

---

## Run with Docker

```bash
docker build -t fraud-api:latest .
docker run -p 8000:8000 fraud-api:latest
```

---

## Azure deployment walkthrough

> Prerequisites: [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) installed and `az login` completed.

### 1 — Create a free Azure account

Sign up at https://azure.microsoft.com/free (USD 200 credit, 12 months of free services).

### 2 — Set variables (adjust to taste)

```bash
RESOURCE_GROUP=rg-fraud-demo
LOCATION=eastus
ACR_NAME=frauddemoacr          # globally unique, alphanumeric only
IMAGE_NAME=fraud-api
IMAGE_TAG=v1.2.0
CONTAINER_APP_ENV=fraud-env
CONTAINER_APP_NAME=fraud-api
```

### 3 — Create a Resource Group

```bash
az group create --name $RESOURCE_GROUP --location $LOCATION
```

### 4 — Create Azure Container Registry (Basic SKU)

```bash
az acr create \
  --resource-group $RESOURCE_GROUP \
  --name $ACR_NAME \
  --sku Basic \
  --admin-enabled true
```

### 5 — Build and push the image to ACR

```bash
# Authenticate Docker to ACR
az acr login --name $ACR_NAME

# Build and push in one step (runs on ACR's build agents — no local Docker daemon needed)
az acr build \
  --registry $ACR_NAME \
  --image $IMAGE_NAME:$IMAGE_TAG \
  .
```

### 6 — Create an Azure Container Apps environment

```bash
az containerapp env create \
  --name $CONTAINER_APP_ENV \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION
```

### 7 — Deploy to Azure Container Apps

```bash
ACR_LOGIN_SERVER=$(az acr show --name $ACR_NAME --query loginServer -o tsv)
ACR_PASSWORD=$(az acr credential show --name $ACR_NAME --query passwords[0].value -o tsv)

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

### 8 — Get the public URL

```bash
APP_URL=$(az containerapp show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query properties.configuration.ingress.fqdn -o tsv)

echo "https://$APP_URL"
```

### 9 — Test the endpoints

```bash
# Health check
curl https://$APP_URL/health

# Predict
curl -X POST https://$APP_URL/predict \
  -H "Content-Type: application/json" \
  -d '{"amount": 850.00, "country": "NG", "card_present": false}'
```

### 10 — Check logs

```bash
az containerapp logs show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --follow
```

### 11 — Tear down (avoid charges)

```bash
az group delete --name $RESOURCE_GROUP --yes --no-wait
```

---

## Production hardening notes

The following is what this demo would need before handling real transaction data.

### Identity & secrets

| Topic | Approach |
|-------|----------|
| **Managed Identity** | Assign a system-assigned managed identity to the Container App. Remove `--registry-username / --registry-password` flags; grant the identity `AcrPull` on the registry instead. No credentials stored anywhere. |
| **Azure Key Vault** | Store feature-flag thresholds, model endpoint URIs, and any third-party API keys in Key Vault. Access them at runtime via the Key Vault SDK using the managed identity — zero secrets in environment variables or image layers. |
| **RBAC** | Scope roles to the minimum: `AcrPull` for the app identity, `AcrPush` only for the CI pipeline service principal. Use Azure AD conditional access to restrict Key Vault access to specific managed identities. |

### Observability

| Topic | Approach |
|-------|----------|
| **Structured logging** | Emit JSON-formatted log lines (add `python-json-logger`) so Log Analytics can parse fields without regex. Never log raw request bodies, card numbers, or PII. |
| **Azure Monitor / Log Analytics** | Link the Container Apps environment to a Log Analytics workspace. Use KQL to query `ContainerAppConsoleLogs_CL` for error rates and latency distributions. |
| **OpenTelemetry** | Instrument with `opentelemetry-sdk` + the Azure Monitor exporter (`azure-monitor-opentelemetry`). Emit traces per request and a `fraud_score` histogram metric. Wire to Application Insights for distributed tracing across services. |
| **p95 / p99 latency** | Create an Application Insights metric alert: if `requests/duration` p99 > 200 ms for 5 minutes, page on-call. Fraud scoring SLAs are typically tight (< 300 ms end-to-end). |
| **Audit logs** | Enable Azure Activity Log and Diagnostic Settings on the Container App and ACR. Retain for 90 days minimum for compliance. |

### CI/CD

```
GitHub push → GitHub Actions workflow:
  1. Run tests (pytest)
  2. Scan image (Trivy or Microsoft Defender for Containers)
  3. az acr build → push image:$SHA tag
  4. az containerapp update --image …:$SHA (rolling update, zero downtime)
  5. Smoke-test /health on the new revision
  6. If smoke test fails → az containerapp revision deactivate (instant rollback)
```

Azure DevOps is a drop-in alternative for the CI/CD layer; the ACR and Container Apps steps are identical.

### Deployment safety

| Topic | Approach |
|-------|----------|
| **Canary / traffic splitting** | Container Apps supports traffic weights per revision. Deploy the new image as a second revision, send 10 % of traffic to it, monitor error rate and latency for 10 minutes, then promote to 100 % or roll back. |
| **Rollback** | Every image is tagged with the Git SHA and pushed to ACR. Roll back with `az containerapp update --image …:<previous-SHA>` — takes effect in seconds. |
| **Image scanning** | Run Trivy in CI (`trivy image --exit-code 1 --severity HIGH,CRITICAL`) before pushing to ACR. Enable Microsoft Defender for Containers on the registry for continuous vulnerability assessment. |
| **Autoscaling** | Set KEDA HTTP scaler rules on the Container App: scale out when concurrent requests > 50, scale back to 1 replica after 5 minutes of inactivity. |

### Networking

| Topic | Approach |
|-------|----------|
| **Private networking** | Deploy the Container Apps environment into a customer-managed VNet. Set `--ingress internal` and front it with Azure API Management or an Application Gateway (WAF_v2 SKU) for TLS termination, rate limiting, and IP allowlisting. |
| **TLS** | Container Apps provisions a managed TLS certificate automatically for the `*.azurecontainerapps.io` domain. For a custom domain, bring your own cert or use the managed cert feature. |

### Model artifact versioning

| Topic | Approach |
|-------|----------|
| **MLflow / Azure ML** | Register each model version in Azure Machine Learning's model registry. Bake the model URI and version into the image at build time (or load dynamically from blob storage at startup). |
| **Image tag strategy** | Tag images as `<image>:<model-version>-<git-sha>` (e.g., `fraud-api:v1.2.0-a3f9c2b`). This makes it unambiguous which model version a running container is serving, and enables exact rollback to any prior model. |
| **Feature drift** | Schedule a batch job (Azure ML Pipelines or a cron Container Job) to compute PSI/KS statistics on live traffic features weekly and alert when drift exceeds threshold. |

---

## Project structure

```
learn-azure-cloud-demo/
├── app/
│   ├── __init__.py
│   ├── main.py        # FastAPI app, middleware, routes
│   ├── model.py       # Deterministic fraud scorer + MODEL_VERSION
│   └── schemas.py     # Pydantic request/response models
├── Dockerfile
├── .dockerignore
├── requirements.txt
└── README.md
```
