"""
Deterministic fake fraud scorer — no real ML model.
Mimics a model artefact with a version string so the deployment flow
(versioned images, rollback, canary) can be demonstrated realistically.
"""

MODEL_VERSION = "v1.2.0"

# Countries associated with elevated card-not-present fraud in public datasets.
_HIGH_RISK_COUNTRIES = {"NG", "RO", "UA", "VN", "PK"}


def score(amount: float, country: str, card_present: bool) -> float:
    """Return a deterministic fraud probability in [0, 1]."""
    risk = 0.05

    if not card_present:
        risk += 0.30

    if country.upper() in _HIGH_RISK_COUNTRIES:
        risk += 0.25

    # Large amounts carry more risk when card is absent.
    if amount > 500:
        risk += 0.15
    elif amount > 200:
        risk += 0.08

    return round(min(risk, 1.0), 4)
