import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.model import MODEL_VERSION, score
from app.schemas import HealthResponse, PredictResponse, TransactionRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("fraud_api")

app = FastAPI(
    title="Fraud Scoring API",
    description="Real-time fraud scoring demo for Azure MLOps.",
    version=MODEL_VERSION,
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "method=%s path=%s status=%s latency_ms=%.1f",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


@app.get("/health", response_model=HealthResponse, tags=["ops"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", model_version=MODEL_VERSION)


@app.post("/predict", response_model=PredictResponse, tags=["scoring"])
def predict(tx: TransactionRequest) -> PredictResponse:
    fraud_score = score(
        amount=tx.amount,
        country=tx.country,
        card_present=tx.card_present,
    )
    logger.info(
        "predict amount=%.2f country=%s card_present=%s fraud_score=%s",
        tx.amount,
        tx.country,
        tx.card_present,
        fraud_score,
    )
    return PredictResponse(fraud_score=fraud_score, model_version=MODEL_VERSION)
