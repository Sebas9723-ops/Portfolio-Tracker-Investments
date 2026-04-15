from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime
from enum import Enum


class TransactionAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    SPLIT = "SPLIT"
    FEE = "FEE"
    ADJUSTMENT = "ADJUSTMENT"


class TransactionCreate(BaseModel):
    ticker: str
    date: date
    action: TransactionAction
    quantity: float
    price_native: float
    fee_native: float = 0.0
    currency: str
    comment: Optional[str] = None


class Transaction(TransactionCreate):
    id: str
    user_id: str
    created_at: datetime


class CashBalanceUpdate(BaseModel):
    currency: str
    amount: float
    account_name: Optional[str] = None
