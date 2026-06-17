from pydantic import BaseModel, Field


class TransactionRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Transaction amount in USD")
    country: str = Field(..., min_length=2, max_length=2, description="ISO 3166-1 alpha-2 country code")
    card_present: bool = Field(..., description="Whether the physical card was present at the point of sale")


class PredictResponse(BaseModel):
    fraud_score: float = Field(..., ge=0.0, le=1.0, description="Fraud probability between 0 and 1")
    model_version: str


class HealthResponse(BaseModel):
    status: str
    model_version: str
