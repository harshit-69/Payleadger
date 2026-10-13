from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint, CheckConstraint
from .database import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    balance_cents = Column(Integer, nullable=False, default=0)  # money as integer cents, never floats
    __table_args__ = (CheckConstraint("balance_cents >= 0"),)


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    initiator_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # None for deposits
    receiver_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount_cents = Column(Integer, nullable=False)
    kind = Column(String, nullable=False)  # "deposit" | "transfer"
    idempotency_key = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint("initiator_id", "idempotency_key"),
        CheckConstraint("amount_cents > 0"),
    )
