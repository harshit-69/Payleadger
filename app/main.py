from pathlib import Path

from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import schemas
from .auth import hash_password, verify_password, create_token, current_user
from .database import Base, engine, get_db
from .models import User, Transaction

Base.metadata.create_all(engine)
app = FastAPI(title="PayLedger")
INDEX = Path(__file__).resolve().parent.parent / "static" / "index.html"


def _out(db: Session, txs: list[Transaction]) -> list[schemas.TxOut]:
    ids = {i for t in txs for i in (t.sender_id, t.receiver_id) if i is not None}
    emails = {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    return [
        schemas.TxOut(
            id=t.id, kind=t.kind, sender_email=emails.get(t.sender_id),
            receiver_email=emails[t.receiver_id], amount_cents=t.amount_cents, created_at=t.created_at,
        )
        for t in txs
    ]


def _existing(db: Session, user: User, key: str):
    return db.scalars(
        select(Transaction).where(Transaction.initiator_id == user.id, Transaction.idempotency_key == key)
    ).first()


def _commit(db: Session, user: User, key: str, tx: Transaction) -> schemas.TxOut:
    try:
        db.commit()
    except IntegrityError:  # same key raced in from a parallel request
        db.rollback()
        tx = _existing(db, user, key)
        if not tx:
            raise
    db.refresh(tx)
    return _out(db, [tx])[0]


@app.post("/api/register", status_code=201)
def register(body: schemas.Credentials, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalars(select(User).where(User.email == email)).first():
        raise HTTPException(409, "Email already registered")
    user = User(email=email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    return {"id": user.id, "email": user.email}


@app.post("/api/login")
def login(body: schemas.Credentials, db: Session = Depends(get_db)):
    user = db.scalars(select(User).where(User.email == body.email.lower())).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    return {"access_token": create_token(user.id), "token_type": "bearer"}


@app.get("/api/me")
def me(user: User = Depends(current_user)):
    return {"email": user.email, "balance_cents": user.balance_cents}


@app.post("/api/deposit", response_model=schemas.TxOut)
def deposit(
    body: schemas.DepositIn,
    idempotency_key: str = Header(min_length=1, max_length=64),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if (t := _existing(db, user, idempotency_key)):
        return _out(db, [t])[0]
    locked = db.scalars(
        select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True)
    ).one()
    locked.balance_cents += body.amount_cents
    tx = Transaction(
        initiator_id=user.id, sender_id=None, receiver_id=user.id,
        amount_cents=body.amount_cents, kind="deposit", idempotency_key=idempotency_key,
    )
    db.add(tx)
    return _commit(db, user, idempotency_key, tx)


@app.post("/api/transfer", response_model=schemas.TxOut)
def transfer(
    body: schemas.TransferIn,
    idempotency_key: str = Header(min_length=1, max_length=64),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if (t := _existing(db, user, idempotency_key)):
        return _out(db, [t])[0]
    receiver = db.scalars(select(User).where(User.email == body.to_email.lower())).first()
    if not receiver:
        raise HTTPException(404, "Recipient not found")
    if receiver.id == user.id:
        raise HTTPException(400, "Cannot transfer to yourself")
    # lock both rows in a fixed order (by id) to avoid deadlocks on Postgres
    rows = {
        u.id: u
        for u in db.scalars(
            select(User).where(User.id.in_([user.id, receiver.id])).order_by(User.id)
            .with_for_update().execution_options(populate_existing=True)
        )
    }
    sender, recv = rows[user.id], rows[receiver.id]
    if sender.balance_cents < body.amount_cents:
        raise HTTPException(422, "Insufficient funds")
    sender.balance_cents -= body.amount_cents
    recv.balance_cents += body.amount_cents
    tx = Transaction(
        initiator_id=user.id, sender_id=sender.id, receiver_id=recv.id,
        amount_cents=body.amount_cents, kind="transfer", idempotency_key=idempotency_key,
    )
    db.add(tx)
    return _commit(db, user, idempotency_key, tx)


@app.get("/api/transactions", response_model=list[schemas.TxOut])
def transactions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    txs = db.scalars(
        select(Transaction)
        .where(or_(Transaction.sender_id == user.id, Transaction.receiver_id == user.id))
        .order_by(Transaction.id.desc()).limit(50)
    ).all()
    return _out(db, list(txs))


@app.get("/")
def index():
    return FileResponse(INDEX)
