# learn-azure-cloud-demo

A minimal real-time fraud-scoring REST API built with FastAPI, containerized with Docker, and deployed to **Azure Container Apps** via **Azure Container Registry**. Built to demonstrate a practical Azure MLOps deployment flow for real-time model serving.

No real ML model — the scorer is a deterministic rule-based function that mimics a versioned model artefact, which is enough to exercise the full cloud deployment pipeline.

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check and model version |
| `POST` | `/predict` | Score a transaction for fraud |

```bash
# Run locally
pip install -r requirements.txt
uvicorn app.main:app --reload
# Swagger UI at http://localhost:8000/docs
```

## Project structure

```
app/
├── main.py       # FastAPI app, middleware, routes
├── model.py      # Deterministic fraud scorer + MODEL_VERSION
└── schemas.py    # Pydantic request/response models
Dockerfile
docs/
└── deployment.md # Full Azure deployment walkthrough
```

## Deployment

See [docs/deployment.md](docs/deployment.md) for the full step-by-step Azure deployment guide including production hardening notes.
