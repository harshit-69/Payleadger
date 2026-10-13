from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class Credentials(BaseModel):
    email: str = Field(pattern=EMAIL)
    password: str = Field(min_length=8, max_length=128)


class DepositIn(BaseModel):
    amount_cents: int = Field(gt=0, le=10_000_000)


class TransferIn(BaseModel):
    to_email: str = Field(pattern=EMAIL)
    amount_cents: int = Field(gt=0, le=10_000_000)


class TxOut(BaseModel):
    id: int
    kind: str
    sender_email: Optional[str]
    receiver_email: str
    amount_cents: int
    created_at: datetime
