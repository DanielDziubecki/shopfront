"""Payment service: validates cards and charges them through an internal provider."""

import datetime as dt
import logging
import os
import uuid

from fastapi import HTTPException
from opentelemetry import metrics, trace
from pydantic import BaseModel, Field

from payment.cards import expired, luhn_valid
from payment.tokens import InvalidTokenError, TokenCache, verify
from shopkit.service import create_app
from shopkit.service import run as run_app

log = logging.getLogger("payment")

app = create_app("payment")
tokens = TokenCache(mode=os.environ.get("PAYMENT_TOKEN_CACHE", "v1"))
charges = metrics.get_meter("payment").create_counter(
    "payment.charges", description="Charge attempts by result"
)


class Card(BaseModel):
    number: str = Field(min_length=12, max_length=19)
    cvv: str = Field(min_length=3, max_length=4)
    exp_month: int = Field(ge=1, le=12)
    exp_year: int = Field(ge=2000, le=2100)


class ChargeRequest(BaseModel):
    amount_cents: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    card: Card


class ChargeResult(BaseModel):
    transaction_id: str
    amount_cents: int
    currency: str


@app.post("/charges")
async def charge(req: ChargeRequest) -> ChargeResult:
    span = trace.get_current_span()
    card = req.card
    span.set_attribute("payment.amount_cents", req.amount_cents)
    span.set_attribute("payment.card_last4", card.number[-4:])

    if not luhn_valid(card.number):
        charges.add(1, {"result": "declined", "reason": "invalid_number"})
        raise HTTPException(status_code=400, detail="invalid card number")
    if expired(card.exp_month, card.exp_year, dt.date.today()):
        charges.add(1, {"result": "declined", "reason": "expired"})
        raise HTTPException(status_code=400, detail="card expired")

    token = tokens.token_for(card.number)
    try:
        verify(token, card.number)
    except InvalidTokenError as exc:
        charges.add(1, {"result": "error", "reason": "invalid_token"})
        log.error("charge failed: %s", exc)
        raise HTTPException(status_code=500, detail="payment provider rejected token") from exc

    transaction_id = f"txn_{uuid.uuid4().hex[:20]}"
    charges.add(1, {"result": "approved"})
    log.info("charged %d %s, transaction %s", req.amount_cents, req.currency, transaction_id)
    return ChargeResult(
        transaction_id=transaction_id, amount_cents=req.amount_cents, currency=req.currency
    )


def run() -> None:
    run_app(app)
