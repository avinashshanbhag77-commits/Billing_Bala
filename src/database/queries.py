import psycopg
from psycopg.rows import dict_row
from typing import List, Dict, Optional
from datetime import datetime
from decimal import Decimal

from src.database.connection import db
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class CDRQueries:
    """CDR-related database operations"""
    
    @staticmethod
    def get_unrated_cdrs(limit: int = 100) -> List[Dict]:
        """
        Fetch unrated CDRs for processing.
        Uses FOR UPDATE SKIP LOCKED for safe parallel processing.
        
        Only fetches CDRs with duration > 0 (answered calls).
        Unanswered calls (duration=0) are skipped.
        
        Args:
            limit: Maximum number of CDRs to fetch
        
        Returns:
            List of CDR dicts
        """
        query = """
            SELECT 
                cdr_id, call_uuid, customer_id, direction, duration_sec,
                currency, ratecard_id, start_time, end_time, billsec
            FROM cdr
            WHERE is_rated = false AND duration_sec > 0
            ORDER BY cdr_id ASC
            LIMIT %s
            FOR UPDATE SKIP LOCKED
        """
        
        with db.get_cursor() as cursor:
            cursor.execute(query, (limit,))
            rows = cursor.fetchall()
        
        return [dict(row) for row in rows]


class TransactionQueries:
    """Transaction-related database operations"""
    
    @staticmethod
    def create_transaction(transaction: Dict) -> int:
        """
        Insert a single transaction and return its ID.
        
        Args:
            transaction: Transaction dict
        
        Returns:
            transaction_id
        """
        query = """
            INSERT INTO transactions (
                customer_id, source_type, source_ref, idempotency_key,
                currency, free_used_sec, wallet_debit_amount, amount_total,
                ratecard_id, rate_per_min, billing_increment_sec, status, notes, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING transaction_id
        """
        
        with db.get_cursor() as cursor:
            cursor.execute(query, (
                transaction['customer_id'],
                transaction['source_type'],
                transaction['source_ref'],
                transaction['idempotency_key'],
                transaction['currency'],
                transaction['free_used_sec'],
                transaction['wallet_debit_amount'],
                transaction['amount_total'],
                transaction['ratecard_id'],
                transaction['rate_per_min'],
                transaction['billing_increment_sec'],
                transaction['status'],
                transaction['notes'],
                transaction['created_at']
            ))
            result = cursor.fetchone()
            return result['transaction_id']


class WalletQueries:
    """Customer wallet-related database operations"""
    
    @staticmethod
    def fetch_and_lock_wallets(customer_ids: List[str]) -> Dict[str, Dict]:
        """
        Fetch and lock customer wallets for update.
        Uses FOR UPDATE to prevent concurrent modifications.
        
        Args:
            customer_ids: List of customer IDs
        
        Returns:
            {customer_id → {currency, fiat_balance, free_seconds, version}}
        """
        if not customer_ids:
            return {}
        
        query = """
            SELECT 
                customer_id, currency, fiat_balance, free_seconds, version
            FROM customer_wallets
            WHERE customer_id = ANY(%s)
            ORDER BY customer_id
            FOR UPDATE
        """
        
        with db.get_cursor() as cursor:
            cursor.execute(query, (customer_ids,))
            rows = cursor.fetchall()
        
        wallets = {}
        for row in rows:
            wallets[row['customer_id']] = dict(row)
        
        logger.debug(f"Locked {len(wallets)} customer wallets")
        
        return wallets