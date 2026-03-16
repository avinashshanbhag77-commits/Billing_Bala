import time
import json
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal
import psycopg
from psycopg.rows import dict_row

from src.services.billing_service import BillingService
from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class CDRProcessor:
    """
    Main batch processing orchestrator.
    Handles 11-step billing flow: fetch → lock → process → commit
    """
    
    def __init__(self):
        self.billing_service = BillingService()
        self.batch_size = config.BILLING_BATCH_SIZE
        self.cache_dir = Path('src/cache')
    
    def load_rate_cards_cache(self) -> dict:
        """
        Load rate cards from JSON cache file.
        Cache should be refreshed via refresh_cache.py when rates change.
        
        Returns:
            {ratecard_id → {name, in_rate_per_sec, ob_rate_per_sec, ...}}
        """
        cache_file = self.cache_dir / 'rate_cards.json'
        
        try:
            with open(cache_file) as f:
                data = json.load(f)
            
            # Convert list to dict keyed by ratecard_id
            rate_cards = {}
            for rc in data.get('rate_cards', []):
                rate_cards[rc['ratecard_id']] = rc
            
            logger.debug(f"Loaded {len(rate_cards)} rate cards from cache")
            return rate_cards
            
        except Exception as e:
            logger.error(f"Failed to load rate cards cache: {e}")
            return {}
    
    def load_customer_ratecard_cache(self) -> dict:
        """
        Load customer→ratecard mappings from JSON cache file.
        Cache should be refreshed via refresh_cache.py when mappings change.
        
        Returns:
            {customer_id → {ratecard_id, effective_from, ...}}
        """
        cache_file = self.cache_dir / 'customer_ratecard.json'
        
        try:
            with open(cache_file) as f:
                data = json.load(f)
            
            # Convert list to dict keyed by customer_id
            customer_ratecards = {}
            for cr in data.get('customer_ratecard', []):
                customer_ratecards[cr['customer_id']] = cr
            
            logger.debug(f"Loaded {len(customer_ratecards)} customer ratecards from cache")
            return customer_ratecards
            
        except Exception as e:
            logger.error(f"Failed to load customer ratecard cache: {e}")
            return {}
    
    def process_batch(self) -> int:
        """
        Process one batch of unrated CDRs.
        Implements the complete 11-step billing flow.
        
        Steps:
        1. Fetch unrated CDRs
        2. Load caches (only if CDRs exist)
        3. Extract unique customer IDs
        4. BEGIN transaction
        5. Lock customer wallets
        6. Process each CDR in memory
        7. Bulk insert transactions
        8. Bulk update CDRs
        9. Bulk update wallets
        10. COMMIT
        11. Return count
        
        Returns:
            Number of CDRs successfully processed
        """
        conn = None
        cursor = None
        
        try:
            # Establish DB connection with retry + exponential backoff
            conn = None
            last_exc = None
            retries = getattr(config, 'DB_CONNECT_RETRIES', 3)
            backoff = getattr(config, 'DB_CONNECT_BACKOFF_SEC', 2)

            for attempt in range(1, retries + 1):
                try:
                    conn = psycopg.connect(
                        host=config.DB_HOST,
                        port=config.DB_PORT,
                        dbname=config.DB_NAME,
                        user=config.DB_USER,
                        password=config.DB_PASSWORD
                    )
                    break
                except Exception as e:
                    last_exc = e
                    logger.warning(f"DB connect attempt {attempt}/{retries} failed: {e}")
                    if attempt < retries:
                        sleep_for = backoff * (2 ** (attempt - 1))
                        logger.info(f"Retrying DB connect in {sleep_for}s...")
                        time.sleep(sleep_for)
                    else:
                        # re-raise to be handled by outer except and logged
                        raise
            cursor = conn.cursor(row_factory=dict_row)
            
            # STEP 1: Fetch unrated CDRs
            logger.info(f"Fetching up to {self.batch_size} unrated CDRs...")
            
            query = """
                SELECT 
                    cdr_id, call_uuid, customer_id, direction, duration_sec,
                    currency, ratecard_id, start_time
                FROM cdr
                WHERE is_rated = false AND duration_sec > 0
                ORDER BY cdr_id ASC
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            """
            cursor.execute(query, (self.batch_size,))
            cdrs = cursor.fetchall()

            def _to_str(val):
                if isinstance(val, (bytes, bytearray, memoryview)):
                    try:
                        return bytes(val).decode('utf-8')
                    except Exception:
                        return str(val)
                return val
            
            if not cdrs:
                logger.info("No unrated CDRs found")
                cursor.close()
                conn.close()
                return 0
            
            logger.info(f"Found {len(cdrs)} CDRs to process")
            
            # STEP 2: Load caches (only if CDRs exist)
            rate_cards = self.load_rate_cards_cache()
            customer_ratecards = self.load_customer_ratecard_cache()
            batch_timestamp = datetime.now(timezone.utc)
            
            if not rate_cards or not customer_ratecards:
                logger.error("Rate cards or customer ratecards cache is empty")
                cursor.close()
                conn.close()
                return 0
            
            # STEP 3: Extract unique customer IDs
            # Normalize CDR fields that may come back as bytes
            for cdr in cdrs:
                cdr['customer_id'] = _to_str(cdr['customer_id'])
                cdr['direction'] = _to_str(cdr['direction'])
                cdr['currency'] = _to_str(cdr['currency'])
            customer_ids = list(set([cdr['customer_id'] for cdr in cdrs]))
            logger.info(f"Customer IDs for batch: {customer_ids} | types={[type(x).__name__ for x in customer_ids]}")
            logger.debug(f"Processing {len(customer_ids)} unique customers")
            
            # STEP 5: Lock customer wallets
            logger.debug(f"Locking {len(customer_ids)} customer wallets...")
            # Build a safe IN (...) list to avoid array type issues
            placeholders = ','.join(['%s'] * len(customer_ids)) if customer_ids else ''
            wallet_query = f"""
                SELECT 
                    customer_id, currency, fiat_balance, free_seconds, version
                FROM customer_wallets
                WHERE customer_id IN ({placeholders})
                ORDER BY customer_id
                FOR UPDATE
            """
            logger.info(f"Locking wallets for: {customer_ids} | param types={[type(x).__name__ for x in customer_ids]}")
            cursor.execute(wallet_query, tuple(customer_ids))
            wallet_rows = cursor.fetchall()
            
            # Convert to dict
            wallets = {}
            for row in wallet_rows:
                cust_id = _to_str(row['customer_id'])
                currency = _to_str(row['currency'])
                wallets[cust_id] = {
                    'currency': currency,
                    'fiat_balance': Decimal(str(row['fiat_balance'])),
                    'free_seconds': row['free_seconds'],
                    'version': row['version']
                }
            logger.info(f"Locked {len(wallets)} wallets for customers: {list(wallets.keys())}")
            if not wallets:
                logger.warning("No wallets locked. Skipping processing for this batch.")
            else:
                missing = sorted(set(customer_ids) - set(wallets.keys()))
                if missing:
                    logger.warning(f"Wallets missing for customers: {missing}")
            
            # STEP 6: Process each CDR in memory
            transactions_to_insert = []
            cdrs_to_update = []
            skipped_no_wallet = 0
            calc_failed = 0
            
            for cdr in cdrs:
                # Skip if customer doesn't have wallet
                if cdr['customer_id'] not in wallets:
                    logger.warning(f"Skipping CDR {cdr['cdr_id']}: no wallet found for {cdr['customer_id']}")
                    skipped_no_wallet += 1
                    continue
                
                # Calculate billing
                transaction, cdr_update = self.billing_service.calculate_billing(
                    cdr,
                    rate_cards,
                    customer_ratecards,
                    wallets[cdr['customer_id']],
                    batch_timestamp
                )
                
                if transaction and cdr_update:
                    transactions_to_insert.append(transaction)
                    cdrs_to_update.append(cdr_update)
                else:
                    calc_failed += 1
            
            if not transactions_to_insert:
                logger.info(
                    f"No transactions to insert after processing. "
                    f"CDRs: {len(cdrs)}, skipped_no_wallet={skipped_no_wallet}, calc_failed={calc_failed}"
                )
                cursor.close()
                conn.close()
                return 0
            
            logger.info(f"Processing {len(transactions_to_insert)} transactions...")
            
            # STEP 7: Bulk insert transactions
            tx_insert_query = """
                INSERT INTO transactions (
                    customer_id, source_type, source_ref, idempotency_key,
                    currency, free_used_sec, wallet_debit_amount, amount_total,
                    ratecard_id, rate_per_min, billing_increment_sec, status, notes, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING transaction_id
            """
            
            transaction_ids = []
            for txn in transactions_to_insert:
                cursor.execute(tx_insert_query, (
                    txn['customer_id'],
                    txn['source_type'],
                    txn['source_ref'],
                    txn['idempotency_key'],
                    txn['currency'],
                    txn['free_used_sec'],
                    txn['wallet_debit_amount'],
                    txn['amount_total'],
                    txn['ratecard_id'],
                    txn['rate_per_min'],
                    txn['billing_increment_sec'],
                    txn['status'],
                    txn['notes'],
                    txn['created_at']
                ))
                result = cursor.fetchone()
                transaction_ids.append(result['transaction_id'])
            
            logger.debug(f"Inserted {len(transaction_ids)} transactions")
            
            # Link transaction IDs to CDR updates
            for i, cdr_update in enumerate(cdrs_to_update):
                cdr_update['transaction_id'] = transaction_ids[i]
            
            # STEP 8: Bulk update CDRs
            cdr_update_query = """
                UPDATE cdr
                SET 
                    transaction_id = %s,
                    billsec = %s,
                    currency = %s,
                    ratecard_id = %s,
                    billed_amount = %s,
                    is_rated = true,
                    rated_at = %s
                WHERE cdr_id = %s
            """
            
            for cdr_update in cdrs_to_update:
                cursor.execute(cdr_update_query, (
                    cdr_update['transaction_id'],
                    cdr_update['billsec'],
                    cdr_update['currency'],
                    cdr_update['ratecard_id'],
                    cdr_update['billed_amount'],
                    cdr_update['rated_at'],
                    cdr_update['cdr_id']
                ))
            
            logger.debug(f"Updated {len(cdrs_to_update)} CDRs")
            
            # STEP 9: Bulk update wallets
            wallet_update_query = """
                UPDATE customer_wallets
                SET 
                    fiat_balance = %s,
                    free_seconds = %s,
                    last_updated = %s,
                    version = version + 1
                WHERE customer_id = %s
            """
            
            processed_customer_ids = {txn['customer_id'] for txn in transactions_to_insert}
            updated_wallets = 0
            for customer_id, wallet in wallets.items():
                # Only update wallets that had CDRs processed
                if customer_id in processed_customer_ids:
                    cursor.execute(wallet_update_query, (
                        float(wallet['fiat_balance']),
                        wallet['free_seconds'],
                        batch_timestamp,
                        customer_id
                    ))
                    updated_wallets += 1
            
            logger.debug(f"Updated {updated_wallets} wallets")
            
            # STEP 10: Commit
            conn.commit()
            logger.info(f"Successfully committed batch: {len(cdrs_to_update)} CDRs processed")
            
            return len(cdrs_to_update)
        
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Batch processing failed: {e}", exc_info=True)
            return 0
        
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    
    def run_continuous(self):
        """
        Run continuous processing loop.
        
        Sleep pattern:
        - 1 second after processing (check again quickly)
        - 60 seconds if no CDRs found (wait longer)
        - 5 seconds on error (retry)
        """
        logger.info("=" * 60)
        logger.info("Starting CDR processor in continuous mode...")
        logger.info(f"Batch size: {self.batch_size}, Interval: {config.PROCESSING_INTERVAL_SEC}s")
        logger.info("=" * 60)
        
        while True:
            try:
                processed = self.process_batch()
                
                if processed > 0:
                    # CDRs processed, check again soon
                    logger.debug(f"Sleeping 1s before next batch...")
                    time.sleep(1)
                else:
                    # No CDRs, wait longer
                    logger.info(f"Waiting {config.PROCESSING_INTERVAL_SEC}s for new CDRs...")
                    time.sleep(config.PROCESSING_INTERVAL_SEC)
            
            except KeyboardInterrupt:
                logger.info("Shutting down CDR processor...")
                break
            
            except Exception as e:
                logger.error(f"Error in processing loop: {e}", exc_info=True)
                time.sleep(5)  # Wait before retrying on error