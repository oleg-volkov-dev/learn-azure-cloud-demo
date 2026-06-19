# Learn Azure Cloud Demo

Exploring Azure Cloud through a small but complete MLOps deployment. The app is a real-time fraud-scoring REST API built with FastAPI, containerized with Docker, and deployed two ways: via **Azure Container Apps** and **Azure Kubernetes Service (AKS)**.

No real ML model — the scorer is a deterministic rule-based function that mimics a versioned model artefact, which is enough to exercise the full deployment pipeline.

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check and model version |
| `POST` | `/predict` | Score a transaction for fraud |

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
# Swagger UI at http://localhost:8000/docs
```

## Structure

```
app/
├── main.py         # FastAPI app, middleware, routes
├── model.py        # Deterministic fraud scorer
└── schemas.py      # Pydantic request/response models
k8s/
├── deployment.yaml
├── service.yaml
├── ingress.yaml
└── hpa.yaml
docs/
├── deployment.md   # Container Apps walkthrough
└── aks-deployment.md  # AKS walkthrough
```

## Deployment

Two paths documented:

- **Container Apps** — [docs/deployment.md](docs/deployment.md) — simpler, managed, less to configure
- **AKS** — [docs/aks-deployment.md](docs/aks-deployment.md) — full Kubernetes, more visibility into how orchestration works
