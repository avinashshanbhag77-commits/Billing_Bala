from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional
import hashlib
import math
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class BillingService:
    """
    Core billing calculation engine.
    Handles rate lookup, increment calculation, free seconds deduction, and transaction prep.
    """
    
    def generate_idempotency_key(self, call_uuid: str) -> str:
        """
        Generate SHA256 hash for idempotency.
        Based on call_uuid to prevent duplicate charges.
        """
        data = f"cdr-{call_uuid}"
        return hashlib.sha256(data.encode()).hexdigest()
    
    def get_rate_card(self, customer_id: str, customer_ratecards: Dict, rate_cards: Dict) -> Optional[Dict]:
        """
        Lookup rate card for customer.
        
        Args:
            customer_id: Customer identifier
            customer_ratecards: {customer_id → {ratecard_id, ...}}
            rate_cards: {ratecard_id → rate card details}
        
        Returns:
            Rate card dict or None if not found
        """
        if customer_id not in customer_ratecards:
            logger.warning(f"Customer {customer_id} not in ratecard mapping")
            return None
        
        ratecard_id = customer_ratecards[customer_id]['ratecard_id']
        
        if ratecard_id not in rate_cards:
            logger.warning(f"Ratecard {ratecard_id} not in rate cards cache")
            return None
        
        return rate_cards[ratecard_id]
    
    def calculate_billable_seconds(
        self,
        duration_sec: int,
        initial_increment_sec: int,
        increment_sec: int
    ) -> int:
        """
        Calculate billable seconds with increment logic.
        
        Formula:
        - If duration <= initial_increment: bill for initial_increment
        - Else: bill for initial + ceil((duration - initial) / increment) * increment
        
        Args:
            duration_sec: Actual call duration in seconds
            initial_increment_sec: First billing pulse (e.g., 60s minimum)
            increment_sec: Subsequent billing pulses (e.g., 60s blocks)
        
        Returns:
            Billable seconds after applying increments
        """
        if duration_sec <= initial_increment_sec:
            return initial_increment_sec
        
        remaining = duration_sec - initial_increment_sec
        increments_needed = math.ceil(remaining / increment_sec)
        billable_sec = initial_increment_sec + (increments_needed * increment_sec)
        
        return billable_sec
    
    def calculate_billing(
        self,
        cdr: Dict,
        rate_cards: Dict,
        customer_ratecards: Dict,
        wallet: Dict,
        batch_timestamp: datetime
    ) -> Tuple[Optional[Dict], Optional[Dict]]:
        """
        Calculate complete billing for a single CDR.
        
        Process:
        1. Get rate card for customer
        2. Select rate by direction (inbound/outbound)
        3. Calculate billable seconds (apply increments)
        4. Deduct free seconds first
        5. Calculate fiat charge for remaining seconds
        6. Prepare transaction and CDR update records
        
        Args:
            cdr: CDR record {cdr_id, call_uuid, customer_id, direction, duration_sec, ...}
            rate_cards: {ratecard_id → {in_rate_per_sec, ob_rate_per_sec, ...}}
            customer_ratecards: {customer_id → {ratecard_id, ...}}
            wallet: {fiat_balance, free_seconds, ...}
            batch_timestamp: Timestamp for this batch
        
        Returns:
            (transaction_dict, cdr_update_dict) or (None, None) if error
        """
        try:
            # STEP 1: Get rate card
            ratecard = self.get_rate_card(cdr['customer_id'], customer_ratecards, rate_cards)
            if not ratecard:
                logger.warning(f"Skipping CDR {cdr['cdr_id']}: no rate card found")
                return None, None
            
            # STEP 2: Select rate based on direction
            if cdr['direction'] == 'inbound':
                rate_per_sec = Decimal(str(ratecard['in_rate_per_sec']))
                rate_per_min = Decimal(str(ratecard['in_rate_per_min']))
                initial_increment = ratecard['in_initial_increment_sec']
                increment = ratecard['in_increment_sec']
            elif cdr['direction'] == 'outbound':
                rate_per_sec = Decimal(str(ratecard['ob_rate_per_sec']))
                rate_per_min = Decimal(str(ratecard['ob_rate_per_min']))
                initial_increment = ratecard['ob_initial_increment_sec']
                increment = ratecard['ob_increment_sec']
            else:
                logger.error(f"Invalid direction {cdr['direction']} for CDR {cdr['cdr_id']}")
                return None, None
            
            # STEP 3: Calculate billable seconds
            billable_sec = self.calculate_billable_seconds(
                cdr['duration_sec'],
                initial_increment,
                increment
            )
            
            # STEP 4: Deduct free seconds first
            free_used_sec = min(wallet['free_seconds'], billable_sec)
            wallet['free_seconds'] -= free_used_sec
            remaining_sec = billable_sec - free_used_sec
            
            # STEP 5: Calculate fiat charge
            if remaining_sec > 0:
                fiat_charge = Decimal(remaining_sec) * rate_per_sec
                wallet['fiat_balance'] -= fiat_charge
            else:
                fiat_charge = Decimal('0')
            
            # Full rated value (for reference)
            total_amount = Decimal(billable_sec) * rate_per_sec
            # Store wallet balance after this charge in amount_total for audit visibility
            wallet_balance_after = wallet['fiat_balance']
            
            # STEP 6: Prepare transaction record
            idempotency_key = self.generate_idempotency_key(cdr['call_uuid'])
            
            transaction = {
                'customer_id': cdr['customer_id'],
                'source_type': 'cdr',
                'source_ref': str(cdr['cdr_id']),
                'idempotency_key': idempotency_key,
                'currency': wallet['currency'],
                'free_used_sec': free_used_sec,
                'wallet_debit_amount': float(fiat_charge),
                'amount_total': float(wallet_balance_after),
                'ratecard_id': ratecard['ratecard_id'],
                'rate_per_min': float(rate_per_min),
                'billing_increment_sec': increment,
                'status': 'posted',
                'notes': f"Call billing: {cdr['call_uuid']}",
                'created_at': batch_timestamp
            }
            
            # STEP 7: Prepare CDR update
            cdr_update = {
                'cdr_id': cdr['cdr_id'],
                'billsec': billable_sec,
                'currency': wallet['currency'],
                'ratecard_id': ratecard['ratecard_id'],
                'billed_amount': float(total_amount),
                'is_rated': True,
                'rated_at': batch_timestamp
                # transaction_id will be added after bulk insert
            }
            
            logger.debug(
                f"CDR {cdr['cdr_id']}: {cdr['direction']} {cdr['duration_sec']}s → "
                f"bill {billable_sec}s, free {free_used_sec}s, charge ${fiat_charge}"
            )
            
            return transaction, cdr_update
            
        except Exception as e:
            logger.error(f"Error calculating billing for CDR {cdr['cdr_id']}: {e}", exc_info=True)
            return None, None