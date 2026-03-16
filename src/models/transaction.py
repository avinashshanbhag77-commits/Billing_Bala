from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from decimal import Decimal

@dataclass
class Transaction:
    transaction_id: Optional[int]
    customer_id: str
    source_type: str  # 'cdr', 'manual', 'subscription', 'adjustment', 'recharge'
    source_ref: Optional[str]
    idempotency_key: str
    currency: str  # 'USD' or 'CAD'
    free_used_sec: int
    wallet_debit_amount: Decimal
    amount_total: Decimal
    ratecard_id: Optional[int]
    rate_per_min: Optional[Decimal]
    billing_increment_sec: Optional[int]
    status: str  # 'pending', 'posted', 'reversed', 'failed'
    notes: Optional[str]
    created_at: datetime
    
    @classmethod
    def from_db_row(cls, row: dict):
        """Create Transaction instance from database row"""
        return cls(**row)