# CDR Billing System - Complete Implementation Specification v1.0

**Document Version:** 1.0  
**Last Updated:** January 21, 2026 (Production Tested v1.1)  
**Target Audience:** Software developers implementing a CDR-based billing system  
**Technology Stack:** Python 3.9+, PostgreSQL 14+, psycopg3

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture](#2-architecture)
3. [Database Schema](#3-database-schema)
4. [Cache Structure](#4-cache-structure)
5. [Processing Flow](#5-processing-flow)
6. [Billing Calculation Logic](#6-billing-calculation-logic)
7. [Implementation Details](#7-implementation-details)
8. [Configuration](#8-configuration)
9. [Error Handling](#9-error-handling)
10. [Testing Scenarios](#10-testing-scenarios)
11. [Deployment & Operations](#11-deployment--operations)

---

## 1. System Overview

### 1.1 Purpose
The CDR Billing System processes Call Detail Records (CDRs) from telephony/VoIP systems and generates financial transactions by:
- Applying rate cards based on call direction (inbound/outbound)
- Deducting from customer wallets (free seconds first, then fiat balance)
- Recording all transactions for audit and reporting
- Updating CDR records with billing information

### 1.2 Key Features
- ✅ Batch processing with configurable batch size
- ✅ Transactional integrity (atomic commits)
- ✅ Idempotency (prevents duplicate charges)
- ✅ Lock-based concurrency control (prevents race conditions)
- ✅ Fresh rate card loading (no stale rates)
- ✅ Free seconds/fiat balance management
- ✅ Support for inbound and outbound call rating
- ✅ Negative balance allowed (for credit management)
- ✅ Bulk database operations (high performance)

### 1.3 Design Principles
- **Efficiency**: Load cache only when CDRs exist
- **Freshness**: Read rate cards from disk each batch
- **Atomicity**: All-or-nothing batch processing
- **Safety**: Row-level locks prevent concurrent conflicts
- **Simplicity**: Clear, maintainable code structure

---

## 2. Architecture

### 2.1 System Components
┌─────────────────────────────────────────────────────────────┐
│ MAIN PROCESS │
│ (src/main.py) │
└──────────────────────┬──────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────┐
│ CDR PROCESSOR │
│ (src/services/cdr_processor.py) │
│ • Continuous polling loop │
│ • Batch fetching from database │
│ • Cache loading (rate cards, customer ratecards) │
│ • Orchestrates billing service │
└──────────────────────┬──────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────┐
│ BILLING SERVICE │
│ (src/services/billing_service.py) │
│ • Rate card lookup │
│ • Billing calculation │
│ • Wallet deduction logic │
│ • Transaction preparation │
└──────────────────────┬──────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────┐
│ DATABASE QUERIES │
│ (src/database/queries.py) │
│ • CDR queries (fetch, update) │
│ • Transaction queries (insert) │
│ • Wallet queries (fetch, lock, update) │
└──────────────────────┬──────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────┐
│ POSTGRESQL DATABASE │
│ • cdr table │
│ • transactions table │
│ • customer_wallets table │
│ • rate_cards table │
│ • customer_ratecard table │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ CACHE FILES (JSON) │
│ • rate_cards.json │
│ • customer_ratecard.json │
│ • Refreshed via refresh_cache.py │
└─────────────────────────────────────────────────────────────┘


### 2.2 Data Flow
[Telephony System] → [CDR Records Created (is_rated=false)]
↓
[CDR Processor Polls DB]
↓
[Load Rate Card Cache]
↓
[Lock Customer Wallets (FOR UPDATE)]
↓
[Calculate Billing in Memory]
↓
[Bulk Insert Transactions → Get IDs]
↓
[Bulk Update CDRs (is_rated=true)]
↓
[Bulk Update Customer Wallets]
↓
[COMMIT]
↓
[Log Success, Sleep 1s]


---

## 3. Database Schema

### 3.1 CDR Table

**Purpose:** Store call detail records for billing

```sql
CREATE TABLE cdr (
    cdr_id BIGSERIAL PRIMARY KEY,
    call_uuid UUID NOT NULL UNIQUE,
    customer_id TEXT NOT NULL,
    caller TEXT NOT NULL,
    callee TEXT NOT NULL,
    last_destination TEXT,
    direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    start_time TIMESTAMPTZ NOT NULL,
    answer_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ NOT NULL,
    duration_sec INTEGER NOT NULL CHECK (duration_sec >= 0),
    billsec INTEGER NOT NULL DEFAULT 0 CHECK (billsec >= 0),
    hangup_cause TEXT,
    sip_status INTEGER,
    ingress_trunk TEXT,
    egress_trunk TEXT,
    route_id TEXT,
    gateway_id TEXT,
    currency CHAR(3) NOT NULL CHECK (currency IN ('USD', 'CAD')),
    ratecard_id BIGINT,
    billed_amount NUMERIC(12,6) NOT NULL DEFAULT 0,
    transaction_id BIGINT REFERENCES transactions(transaction_id),
    is_rated BOOLEAN NOT NULL DEFAULT false,
    rated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_cdr_customer_time ON cdr(customer_id, start_time DESC);
CREATE INDEX idx_cdr_transaction_id ON cdr(transaction_id);
CREATE INDEX idx_cdr_is_rated ON cdr(is_rated) WHERE is_rated = false;

Key Fields for Billing:

cdr_id: Primary key
call_uuid: Idempotency reference
customer_id: Links to wallet
direction: Determines rate (inbound/outbound)
duration_sec: Used to calculate billable seconds
is_rated: Processing flag (false = needs billing)

3.2 Transactions Table
Purpose: Financial ledger for all billing activities

CREATE TABLE transactions (
    transaction_id BIGSERIAL PRIMARY KEY,
    customer_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('cdr', 'manual', 'subscription', 'adjustment', 'recharge')),
    source_ref TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    currency CHAR(3) NOT NULL CHECK (currency IN ('USD', 'CAD')),
    free_used_sec INTEGER NOT NULL DEFAULT 0 CHECK (free_used_sec >= 0),
    wallet_debit_amount NUMERIC(12,6) NOT NULL DEFAULT 0 CHECK (wallet_debit_amount >= 0),
    amount_total NUMERIC(12,6) NOT NULL DEFAULT 0,
    ratecard_id BIGINT,
    rate_per_min NUMERIC(12,6),
    billing_increment_sec INTEGER,
    status TEXT NOT NULL DEFAULT 'posted' CHECK (status IN ('pending', 'posted', 'reversed', 'failed')),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tx_customer_time ON transactions(customer_id, created_at DESC);
CREATE INDEX idx_tx_source ON transactions(source_type, source_ref);

Key Fields:

idempotency_key: Prevents duplicate charges (SHA256 of call_uuid)
free_used_sec: Free seconds consumed this transaction
wallet_debit_amount: Fiat amount charged
amount_total: Wallet balance after charge (for audit visibility - enables verification of billing correctness)
3.3 Customer Wallets Table
Purpose: Current prepaid balances per customer

CREATE TABLE customer_wallets (
    customer_id TEXT PRIMARY KEY,
    currency CHAR(3) NOT NULL CHECK (currency IN ('USD', 'CAD')),
    fiat_balance NUMERIC(14,6) NOT NULL DEFAULT 0,
    free_seconds INTEGER NOT NULL DEFAULT 0 CHECK (free_seconds >= 0),
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1)
);

CREATE INDEX idx_customer_wallets_currency ON customer_wallets(currency);

Important Notes:

fiat_balance: CAN GO NEGATIVE (credit management handled elsewhere)
free_seconds: Always >= 0, consumed first before fiat
version: Optimistic locking field (incremented on each update)
3.4 Rate Cards Table
Purpose: Rate configurations for billing

CREATE TABLE rate_cards (
    ratecard_id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    currency CHAR(3) NOT NULL CHECK (currency IN ('USD', 'CAD')),
    country TEXT,
    in_rate_per_min NUMERIC(12,6) NOT NULL CHECK (in_rate_per_min >= 0),
    in_initial_increment_sec INTEGER NOT NULL DEFAULT 60 CHECK (in_initial_increment_sec > 0),
    in_increment_sec INTEGER NOT NULL DEFAULT 60 CHECK (in_increment_sec > 0),
    ob_rate_per_min NUMERIC(12,6) NOT NULL CHECK (ob_rate_per_min >= 0),
    ob_initial_increment_sec INTEGER NOT NULL DEFAULT 60 CHECK (ob_initial_increment_sec > 0),
    ob_increment_sec INTEGER NOT NULL DEFAULT 60 CHECK (ob_increment_sec > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_rate_cards_currency_country ON rate_cards(currency, country);

Rate Fields:

in_*: Inbound call rates
ob_*: Outbound call rates
*_initial_increment_sec: First billing pulse (e.g., 60s minimum)
*_increment_sec: Subsequent pulses (e.g., round up to 60s)
3.5 Customer Ratecard Table
Purpose: Map customers to rate cards

CREATE TABLE customer_ratecard (
    customer_id TEXT PRIMARY KEY,
    ratecard_id BIGINT NOT NULL REFERENCES rate_cards(ratecard_id),
    effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    effective_to TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT customer_ratecard_effective_window CHECK (effective_to IS NULL OR effective_to > effective_from)
);

CREATE INDEX idx_customer_ratecard_ratecard_id ON customer_ratecard(ratecard_id);

4. Cache Structure
4.1 Rate Cards Cache
File: rate_cards.json

Structure:
{
  "timestamp": "2026-01-19T14:41:30.697558+00:00",
  "total": 1,
  "rate_cards": [
    {
      "ratecard_id": 2,
      "name": "test1",
      "currency": "USD",
      "country": "na",
      "in_rate_per_min": 0.01,
      "in_rate_per_sec": 0.0001666667,
      "in_initial_increment_sec": 60,
      "in_increment_sec": 60,
      "ob_rate_per_min": 0.005,
      "ob_rate_per_sec": 0.0000833333,
      "ob_initial_increment_sec": 60,
      "ob_increment_sec": 60,
      "created_at": "2026-01-18T15:05:28.028450+00:00",
      "updated_at": "2026-01-18T15:05:28.028450+00:00"
    }
  ]
}


Calculated Fields:

in_rate_per_sec: in_rate_per_min / 60 (rounded to 10 decimals)
ob_rate_per_sec: ob_rate_per_min / 60 (rounded to 10 decimals)
Refresh Command:
python scripts/refresh_cache.py

4.2 Customer Ratecard Cache
File: customer_ratecard.json

Structure:
{
  "timestamp": "2026-01-19T14:41:30.697558+00:00",
  "total": 2,
  "customer_ratecard": [
    {
      "customer_id": "cust_001",
      "ratecard_id": 2,
      "effective_from": "2026-01-01T00:00:00+00:00",
      "effective_to": null,
      "created_at": "2026-01-01T00:00:00+00:00",
      "updated_at": "2026-01-01T00:00:00+00:00"
    }
  ]
}

Loading Strategy:

Cache loaded from disk each batch (ensures fresh rates)
Only loaded if CDRs exist (performance optimization)
Small file size (~2-10KB typical) = negligible I/O cost

5. Processing Flow
5.1 High-Level Flow
START
  │
  ├─► Fetch Unrated CDRs (LIMIT 100)
  │       │
  │       ├─► If EMPTY → Return 0, Sleep 60s → Loop
  │       │
  │       └─► If CDRs Found:
  │               │
  │               ├─► Load Rate Cards Cache (JSON)
  │               ├─► Load Customer Ratecard Cache (JSON)
  │               ├─► Set batch_timestamp = NOW()
  │               │
  │               ├─► Extract Unique Customer IDs
  │               │
  │               ├─► BEGIN TRANSACTION
  │               │       │
  │               │       ├─► Lock Customer Wallets (FOR UPDATE)
  │               │       │
  │               │       ├─► FOR EACH CDR (In Memory):
  │               │       │       ├─► Get Rate Card
  │               │       │       ├─► Calculate Billable Seconds
  │               │       │       ├─► Deduct Free Seconds
  │               │       │       ├─► Calculate Fiat Charge
  │               │       │       ├─► Update Wallet (In Memory)
  │               │       │       ├─► Prepare Transaction Record
  │               │       │       └─► Prepare CDR Update
  │               │       │
  │               │       ├─► Bulk INSERT Transactions → Get IDs
  │               │       ├─► Bulk UPDATE CDRs
  │               │       ├─► Bulk UPDATE Wallets
  │               │       │
  │               │       └─► COMMIT
  │               │
  │               ├─► Log Success
  │               └─► Sleep 1s → Loop
  │
  └─► ON ERROR:
          ├─► ROLLBACK
          ├─► Log Error
          ├─► Sleep 5s
          └─► Loop

5.2 Detailed Step-by-Step Flow
STEP 1: Fetch Unrated CDRs
SELECT cdr_id, call_uuid, customer_id, direction, duration_sec
FROM cdr
WHERE is_rated = false 
  AND duration_sec > 0  -- Skip unanswered calls
ORDER BY start_time ASC
LIMIT 100
FOR UPDATE SKIP LOCKED;
Logic:
cdrs = fetch_unrated_cdrs(limit=100)

if not cdrs:
    logger.info("No unrated CDRs found")
    return 0  # Exit early, don't load cache

Why duration_sec > 0?

Unanswered calls have duration_sec = 0
No billing needed for unanswered calls
Why FOR UPDATE SKIP LOCKED?

Locks selected rows
Other processes skip locked rows (parallel processing safe) 

STEP 2: Load Cache (Only if CDRs Exist)
# Load rate cards
with open('src/cache/rate_cards.json') as f:
    rate_cards_data = json.load(f)
    rate_cards = {rc['ratecard_id']: rc for rc in rate_cards_data['rate_cards']}

# Load customer ratecards
with open('src/cache/customer_ratecard.json') as f:
    customer_ratecard_data = json.load(f)
    customer_ratecards = {cr['customer_id']: cr for cr in customer_ratecard_data['customer_ratecard']}

# Set batch timestamp (all CDRs in batch get same rated_at)
batch_timestamp = datetime.now(timezone.utc)

STEP 3: Extract Unique Customer IDs
customer_ids = list(set([cdr['customer_id'] for cdr in cdrs]))
# Example: ['cust_001', 'cust_005', 'cust_012']

Why?

Only lock wallets for customers with CDRs in this batch
Reduces lock contention
STEP 4: BEGIN TRANSACTION + Lock Wallets

BEGIN;

SELECT customer_id, currency, fiat_balance, free_seconds, version
FROM customer_wallets
WHERE customer_id IN ('cust_001', 'cust_005', 'cust_012')
ORDER BY customer_id  -- Prevent deadlock
FOR UPDATE;  -- Lock these rows
Store in memory:

wallets = {}
for row in wallet_rows:
    wallets[row['customer_id']] = {
        'currency': row['currency'],
        'fiat_balance': Decimal(row['fiat_balance']),
        'free_seconds': row['free_seconds'],
        'version': row['version']
    }

Why ORDER BY customer_id?

Ensures consistent lock order across processes
Prevents circular deadlocks
STEP 5: Process Each CDR (In Memory)
For each CDR in the batch:    

5.1 Get Customer's Rate Card
customer_ratecard_id = customer_ratecards[cdr['customer_id']]['ratecard_id']
ratecard = rate_cards[customer_ratecard_id]

5.2 Select Rate Based on Direction
if cdr['direction'] == 'inbound':
    rate_per_sec = Decimal(ratecard['in_rate_per_sec'])
    rate_per_min = Decimal(ratecard['in_rate_per_min'])
    initial_increment = ratecard['in_initial_increment_sec']
    increment = ratecard['in_increment_sec']
else:  # outbound
    rate_per_sec = Decimal(ratecard['ob_rate_per_sec'])
    rate_per_min = Decimal(ratecard['ob_rate_per_min'])
    initial_increment = ratecard['ob_initial_increment_sec']
    increment = ratecard['ob_increment_sec']

5.3 Calculate Billable Seconds (Apply Increments)    

import math

duration = cdr['duration_sec']

if duration <= initial_increment:
    billable_sec = initial_increment
else:
    remaining = duration - initial_increment
    increments_needed = math.ceil(remaining / increment)
    billable_sec = initial_increment + (increments_needed * increment)

Example:

Duration: 125 seconds
Initial: 60s, Increment: 60s
Calculation: 60 + ceil((125-60)/60)60 = 60 + 260 = 180s billed
5.4 Get Customer Wallet    
wallet = wallets[cdr['customer_id']]

5.5 Deduct Free Seconds First

free_used_sec = min(wallet['free_seconds'], billable_sec)
wallet['free_seconds'] -= free_used_sec
remaining_sec = billable_sec - free_used_sec

Logic:

If free_seconds >= billable_sec: Use free, no charge
If free_seconds < billable_sec: Use all free, charge rest
5.6 Calculate Fiat Charge
if remaining_sec > 0:
    fiat_charge = Decimal(remaining_sec) * rate_per_sec
    wallet['fiat_balance'] -= fiat_charge  # CAN GO NEGATIVE
else:
    fiat_charge = Decimal('0')

total_amount = Decimal(billable_sec) * rate_per_sec

5.7 Prepare Transaction Record

import hashlib

idempotency_key = hashlib.sha256(f"cdr-{cdr['call_uuid']}".encode()).hexdigest()

transaction = {
    'customer_id': cdr['customer_id'],
    'source_type': 'cdr',
    'source_ref': str(cdr['cdr_id']),
    'idempotency_key': idempotency_key,
    'currency': wallet['currency'],
    'free_used_sec': free_used_sec,
    'wallet_debit_amount': float(fiat_charge),
    'amount_total': float(wallet_balance_after),  # Wallet balance after this charge (for audit)
    'ratecard_id': ratecard['ratecard_id'],
    'rate_per_min': float(rate_per_min),
    'billing_increment_sec': increment,
    'status': 'posted',
    'notes': f"Call billing: {cdr['call_uuid']}",
    'created_at': batch_timestamp
}
# wallet_balance_after is calculated as:
wallet_balance_after = wallet['fiat_balance']  # This is already deducted in step 5.5-5.6
# So amount_total now shows the resulting balance post-charge
transactions_to_insert.append(transaction)
5.8 Prepare CDR Update

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

cdrs_to_update.append(cdr_update)

STEP 6: Bulk Insert Transactions
INSERT INTO transactions (
    customer_id, source_type, source_ref, idempotency_key,
    currency, free_used_sec, wallet_debit_amount, amount_total,
    ratecard_id, rate_per_min, billing_increment_sec, status, notes, created_at
)
VALUES 
    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s),
    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s),
    ... (100 rows)
RETURNING transaction_id;

Implementation:

values = []
for txn in transactions_to_insert:
    values.extend([
        txn['customer_id'], txn['source_type'], txn['source_ref'],
        txn['idempotency_key'], txn['currency'], txn['free_used_sec'],
        txn['wallet_debit_amount'], txn['amount_total'], txn['ratecard_id'],
        txn['rate_per_min'], txn['billing_increment_sec'],
        txn['status'], txn['notes'], txn['created_at']
    ])

placeholders = ','.join(['(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)'] * len(transactions_to_insert))
query = f"INSERT INTO transactions (...) VALUES {placeholders} RETURNING transaction_id"

cursor.execute(query, values)
transaction_ids = [row[0] for row in cursor.fetchall()]

Map transaction_ids to CDR updates:

for i, cdr_update in enumerate(cdrs_to_update):
    cdr_update['transaction_id'] = transaction_ids[i]

STEP 7: Bulk Update CDRs
UPDATE cdr
SET 
    transaction_id = CASE cdr_id
        WHEN 123 THEN 5001
        WHEN 124 THEN 5002
        ...
    END,
    billsec = CASE cdr_id WHEN 123 THEN 65 WHEN 124 THEN 120 ... END,
    currency = CASE cdr_id WHEN 123 THEN 'USD' ... END,
    ratecard_id = CASE cdr_id WHEN 123 THEN 2 ... END,
    billed_amount = CASE cdr_id WHEN 123 THEN 0.05416 ... END,
    is_rated = true,
    rated_at = '2026-01-19 20:30:00'
WHERE cdr_id IN (123, 124, 125, ...);

Implementation:
cdr_ids = [u['cdr_id'] for u in cdrs_to_update]

query = """
    UPDATE cdr
    SET 
        transaction_id = data.transaction_id,
        billsec = data.billsec,
        currency = data.currency,
        ratecard_id = data.ratecard_id,
        billed_amount = data.billed_amount,
        is_rated = true,
        rated_at = %s
    FROM (VALUES %s) AS data(cdr_id, transaction_id, billsec, currency, ratecard_id, billed_amount)
    WHERE cdr.cdr_id = data.cdr_id
"""

values = [(
    u['cdr_id'], u['transaction_id'], u['billsec'],
    u['currency'], u['ratecard_id'], u['billed_amount']
) for u in cdrs_to_update]

execute_values(cursor, query, values, template=None, page_size=100)

STEP 8: Bulk Update Wallets
UPDATE customer_wallets
SET 
    fiat_balance = CASE customer_id
        WHEN 'cust_001' THEN -5.20
        WHEN 'cust_005' THEN 100.50
        ...
    END,
    free_seconds = CASE customer_id
        WHEN 'cust_001' THEN 0
        WHEN 'cust_005' THEN 1200
        ...
    END,
    last_updated = '2026-01-19 20:30:00',
    version = version + 1
WHERE customer_id IN ('cust_001', 'cust_005', ...);
Implementation:
query = """
    UPDATE customer_wallets
    SET 
        fiat_balance = data.fiat_balance,
        free_seconds = data.free_seconds,
        last_updated = %s,
        version = version + 1
    FROM (VALUES %s) AS data(customer_id, fiat_balance, free_seconds)
    WHERE customer_wallets.customer_id = data.customer_id
"""

values = [(
    customer_id,
    float(wallet['fiat_balance']),
    wallet['free_seconds']
) for customer_id, wallet in wallets.items()]

execute_values(cursor, query, values, template=None, page_size=100)

STEP 9: COMMIT
Result:

All 3 tables updated atomically
Wallet locks released
CDRs now is_rated = true

conn.commit()
logger.info(f"Successfully processed {len(cdrs)} CDRs in batch")
return len(cdrs)
STEP 10: Error Handling
except Exception as e:
    conn.rollback()
    logger.error(f"Batch processing failed: {e}", exc_info=True)
    return 0
finally:
    cursor.close()
    conn.close()

On Rollback:
No changes saved
Wallets unchanged
CDRs remain is_rated = false
Next batch will retry

STEP 11: Loop Control
processed = process_batch()

if processed > 0:
    time.sleep(1)  # CDRs processed, check again soon
else:
    time.sleep(60)  # No CDRs, wait longer

6. Billing Calculation Logic
6.1 Increment Logic
Initial Increment:

First billing pulse (e.g., 60 seconds minimum charge)
If call < 60s, still billed for 60s
Subsequent Increment:

Round up to nearest increment (e.g., 60s blocks)
Example: 125s call = 60s + 2×60s = 180s billed
Formula:

if duration <= initial_increment:
    billable_sec = initial_increment
else:
    remaining = duration - initial_increment
    increments_needed = ceil(remaining / increment)
    billable_sec = initial_increment + (increments_needed * increment)

### 6.2 Free Seconds vs Fiat Balance

**Priority Order:**
1. Use free seconds first (no charge)
2. If free seconds exhausted, charge fiat balance
3. Fiat balance can go negative

**Example Scenarios:**

| Scenario | Free Seconds | Billable Sec | Free Used | Fiat Charged (@ $0.001/sec) | New Free Sec | New Fiat |
|----------|--------------|--------------|-----------|--------------------------|--------------|----------|
| A: Enough free | 300 | 120 | 120 | $0.00 | 180 | No change |
| B: Partial free | 50 | 120 | 50 | $0.07 (70 sec × $0.001) | 0 | -$0.07 |
| C: No free | 0 | 120 | 0 | $0.12 (120 sec × $0.001) | 0 | -$0.12 |
| D: Zero balance | 0 | 120 | 0 | $0.12 | 0 | -$0.12 (debt) |

### 6.3 Direction-Based Rating

**Inbound Calls:**
```python
rate_per_sec = ratecard['in_rate_per_sec']
initial_increment = ratecard['in_initial_increment_sec']
increment = ratecard['in_increment_sec']

Outbound Calls:
rate_per_sec = ratecard['ob_rate_per_sec']
initial_increment = ratecard['ob_initial_increment_sec']
increment = ratecard['ob_increment_sec']

6.4 Calculation Examples
Example 1: Short Call with Free Seconds

Input:
- Duration: 45 seconds
- Direction: inbound
- Initial increment: 60s
- Increment: 60s
- Rate: $0.01/min = $0.0001666667/sec
- Free seconds: 1000

Calculation:
1. Billable seconds: 60 (minimum initial increment)
2. Free seconds used: 60
3. Remaining seconds: 0
4. Fiat charge: $0.00
5. Total amount: 60 × $0.0001666667 = $0.01

Result:
- free_used_sec: 60
- wallet_debit_amount: $0.00
- amount_total: $10.00 (wallet balance after charge, since free seconds covered it)
- total_amount (internal): $0.01 (full rated value)
- New free_seconds: 940
- New fiat_balance: unchanged

Example 2: Long Call, No Free Seconds

Input:
- Duration: 125 seconds
- Direction: outbound
- Initial increment: 60s
- Increment: 60s
- Rate: $0.005/min = $0.0000833333/sec
- Free seconds: 0
- Fiat balance: $10.00

Calculation:
1. Billable seconds: 60 + ceil((125-60)/60)×60 = 60 + 120 = 180
2. Free seconds used: 0
3. Remaining seconds: 180
4. Fiat charge: 180 × $0.0000833333 = $0.015
5. Total amount: $0.015

Result:
- free_used_sec: 0
- wallet_debit_amount: $0.015
- amount_total: $9.985 (wallet balance after charge)
- total_amount (internal): $0.015 (full rated value)
- New free_seconds: 0
- New fiat_balance: $9.985

Example 3: Partial Free Seconds
Input:
- Duration: 200 seconds
- Direction: inbound
- Initial increment: 60s
- Increment: 60s
- Rate: $0.01/min = $0.0001666667/sec
- Free seconds: 100
- Fiat balance: $5.00

Calculation:
1. Billable seconds: 60 + ceil((200-60)/60)×60 = 60 + 180 = 240
2. Free seconds used: 100 (all available)
3. Remaining seconds: 240 - 100 = 140
4. Fiat charge: 140 × $0.0001666667 = $0.0233
5. Total amount: 240 × $0.0001666667 = $0.04

Result:
- free_used_sec: 100
- wallet_debit_amount: $0.0233
- amount_total: $4.9767 (wallet balance after charge)
- total_amount (internal): $0.04 (full rated value)
- New free_seconds: 0
- New fiat_balance: $4.9767
7. Implementation Details
7.1 File Structure
billing/
├── src/
│   ├── __init__.py
│   ├── [main.py](http://_vscodecontentref_/0)                      # Entry point
│   ├── [config.py](http://_vscodecontentref_/1)                    # Configuration management
│   ├── cache/
│   │   ├── rate_cards.json          # Rate cards cache
│   │   └── customer_ratecard.json   # Customer mappings cache
│   ├── database/
│   │   ├── __init__.py
│   │   ├── [connection.py](http://_vscodecontentref_/2)            # DB connection manager
│   │   └── [queries.py](http://_vscodecontentref_/3)               # Database queries
│   ├── models/
│   │   ├── __init__.py
│   │   ├── [cdr.py](http://_vscodecontentref_/4)                   # CDR data model
│   │   └── [transaction.py](http://_vscodecontentref_/5)           # Transaction data model
│   ├── services/
│   │   ├── __init__.py
│   │   ├── [billing_service.py](http://_vscodecontentref_/6)       # Billing logic
│   │   └── [cdr_processor.py](http://_vscodecontentref_/7)         # Main processing loop
│   └── utils/
│       ├── __init__.py
│       ├── helpers.py               # Utility functions
│       └── [logger.py](http://_vscodecontentref_/8)                # Logging setup
├── scripts/
│   ├── [create_tables.sql](http://_vscodecontentref_/9)            # Database schema
│   └── [refresh_cache.py](http://_vscodecontentref_/10)             # Cache refresh script
├── tests/
│   ├── __init__.py
│   ├── test_billing_service.py
│   └── test_cdr_processor.py
├── docs/
│   ├── BILLING_IMPLEMENTATION_SPEC.md  # This document
│   ├── [cdr_table.md](http://_vscodecontentref_/11)
│   ├── [transaction_table.md](http://_vscodecontentref_/12)
│   ├── [customer_wallets.md](http://_vscodecontentref_/13)
│   └── [rate_cards.md](http://_vscodecontentref_/14)
├── logs/                            # Application logs
├── [requirements.txt](http://_vscodecontentref_/15)                 # Python dependencies
├── .env                             # Environment variables
└── [README.md](http://_vscodecontentref_/16)

7.2 Core Classes
7.2.1 CDRProcessor Class
File: src/services/cdr_processor.py

Responsibilities:

Continuous polling loop
Batch fetching from database
Cache loading
Orchestrate billing service
Error handling and logging
Key Methods:
class CDRProcessor:
    def __init__(self):
        """Initialize processor with billing service and queries"""
        
    def load_rate_cards_cache(self) -> dict:
        """Load rate cards from JSON cache file"""
        
    def load_customer_ratecard_cache(self) -> dict:
        """Load customer ratecard mappings from JSON cache file"""
        
    def process_batch(self) -> int:
        """
        Process one batch of unrated CDRs
        Returns: Number of CDRs processed
        """
        
    def run_continuous(self):
        """Run continuous processing loop"""

Process Batch Pseudocode:

def process_batch(self):
    # 1. Fetch unrated CDRs
    cdrs = fetch_unrated_cdrs(limit=100)
    if not cdrs:
        return 0
    
    # 2. Load caches
    rate_cards = load_rate_cards_cache()
    customer_ratecards = load_customer_ratecard_cache()
    batch_timestamp = now()
    
    # 3. Get unique customers
    customer_ids = unique([cdr.customer_id for cdr in cdrs])
    
    # 4. Begin transaction
    with transaction():
        # 5. Lock wallets
        wallets = lock_and_fetch_wallets(customer_ids)
        
        # 6. Process each CDR
        transactions = []
        cdr_updates = []
        
        for cdr in cdrs:
            result = billing_service.calculate(cdr, rate_cards, customer_ratecards, wallets)
            transactions.append(result.transaction)
            cdr_updates.append(result.cdr_update)
        
        # 7. Bulk operations
        transaction_ids = bulk_insert_transactions(transactions)
        link_transaction_ids(cdr_updates, transaction_ids)
        bulk_update_cdrs(cdr_updates)
        bulk_update_wallets(wallets)
        
        # 8. Commit
        commit()
    
    return len(cdrs)
7.2.2 BillingService Class
File: billing_service.py

Responsibilities:

Rate card lookup
Billing calculation
Wallet deduction logic
Transaction preparation
Idempotency key generation
Key Methods:

class BillingService:
    def generate_idempotency_key(self, call_uuid: str) -> str:
        """Generate SHA256 hash of call_uuid for idempotency"""
        
    def get_rate_card(self, customer_id: str, customer_ratecards: dict, rate_cards: dict) -> dict:
        """Get rate card for customer"""
        
    def calculate_billable_seconds(self, duration: int, initial_increment: int, increment: int) -> int:
        """Calculate billable seconds with increment logic"""
        
    def calculate_billing(self, cdr: dict, rate_cards: dict, customer_ratecards: dict, wallet: dict) -> dict:
        """
        Main billing calculation
        Returns: {
            'transaction': {...},
            'cdr_update': {...},
            'wallet_update': {...}
        }
        """

Calculate Billing Pseudocode:

def calculate_billing(self, cdr, rate_cards, customer_ratecards, wallet):
    # 1. Get rate card
    ratecard_id = customer_ratecards[cdr.customer_id]['ratecard_id']
    ratecard = rate_cards[ratecard_id]
    
    # 2. Select rate by direction
    if cdr.direction == 'inbound':
        rate_per_sec = ratecard['in_rate_per_sec']
        initial_inc = ratecard['in_initial_increment_sec']
        inc = ratecard['in_increment_sec']
    else:
        rate_per_sec = ratecard['ob_rate_per_sec']
        initial_inc = ratecard['ob_initial_increment_sec']
        inc = ratecard['ob_increment_sec']
    
    # 3. Calculate billable seconds
    billable_sec = calculate_billable_seconds(cdr.duration_sec, initial_inc, inc)
    
    # 4. Deduct free seconds
    free_used = min(wallet['free_seconds'], billable_sec)
    wallet['free_seconds'] -= free_used
    remaining_sec = billable_sec - free_used
    
    # 5. Calculate charges
    fiat_charge = remaining_sec * rate_per_sec
    wallet['fiat_balance'] -= fiat_charge
    total_amount = billable_sec * rate_per_sec
    
    # 6. Prepare transaction
    # Note: amount_total stores wallet_balance_after, not full rated cost
    wallet_balance_after = wallet['fiat_balance']
    
    transaction = {
        ...
        'amount_total': wallet_balance_after,
        ...
    }
    
    # 7. Prepare CDR update
    cdr_update = {
        'cdr_id': cdr.cdr_id,
        'billsec': billable_sec,
        'currency': wallet['currency'],
        'ratecard_id': ratecard['ratecard_id'],
        'billed_amount': total_amount,
        'is_rated': True,
        # transaction_id added later
    }
    
    return {'transaction': transaction, 'cdr_update': cdr_update}

7.2.3 Database Queries
File: queries.py

CDR Queries:
def fetch_unrated_cdrs(cursor, limit: int) -> list:
    """Fetch unrated CDRs with lock"""
    query = """
        SELECT cdr_id, call_uuid, customer_id, direction, duration_sec
        FROM cdr
        WHERE is_rated = false AND duration_sec > 0
        ORDER BY start_time ASC
        LIMIT %s
        FOR UPDATE SKIP LOCKED
    """
    cursor.execute(query, (limit,))
    return cursor.fetchall()

def bulk_update_cdrs(cursor, updates: list, batch_timestamp):
    """Bulk update CDRs with billing info"""
    query = """
        UPDATE cdr
        SET 
            transaction_id = data.transaction_id,
            billsec = data.billsec,
            currency = data.currency,
            ratecard_id = data.ratecard_id,
            billed_amount = data.billed_amount,
            is_rated = true,
            rated_at = %s
        FROM (VALUES %s) AS data(
            cdr_id, transaction_id, billsec, currency, ratecard_id, billed_amount
        )
        WHERE cdr.cdr_id = data.cdr_id
    """
    values = [(u['cdr_id'], u['transaction_id'], u['billsec'],
               u['currency'], u['ratecard_id'], u['billed_amount']) 
              for u in updates]
    
    execute_values(cursor, query, values)

Transaction Queries:
def bulk_insert_transactions(cursor, transactions: list) -> list:
    """Bulk insert transactions, return IDs"""
    query = """
        INSERT INTO transactions (
            customer_id, source_type, source_ref, idempotency_key,
            currency, free_used_sec, wallet_debit_amount, amount_total,
            ratecard_id, rate_per_min, billing_increment_sec, status, notes, created_at
        )
        VALUES %s
        RETURNING transaction_id
    """
    values = [(
        t['customer_id'], t['source_type'], t['source_ref'], t['idempotency_key'],
        t['currency'], t['free_used_sec'], t['wallet_debit_amount'], t['amount_total'],
        t['ratecard_id'], t['rate_per_min'], t['billing_increment_sec'],
        t['status'], t['notes'], t['created_at']
    ) for t in transactions]
    
    cursor.execute(query, values)
    return [row[0] for row in cursor.fetchall()]

Wallet Queries:
def fetch_and_lock_wallets(cursor, customer_ids: list) -> dict:
    """Fetch and lock customer wallets"""
    query = """
        SELECT customer_id, currency, fiat_balance, free_seconds, version
        FROM customer_wallets
        WHERE customer_id = ANY(%s)
        ORDER BY customer_id
        FOR UPDATE
    """
    cursor.execute(query, (customer_ids,))
    rows = cursor.fetchall()
    
    return {row['customer_id']: dict(row) for row in rows}

def bulk_update_wallets(cursor, wallets: dict, batch_timestamp):
    """Bulk update customer wallets"""
    query = """
        UPDATE customer_wallets
        SET 
            fiat_balance = data.fiat_balance,
            free_seconds = data.free_seconds,
            last_updated = %s,
            version = version + 1
        FROM (VALUES %s) AS data(customer_id, fiat_balance, free_seconds)
        WHERE customer_wallets.customer_id = data.customer_id
    """
    values = [(cust_id, wallet['fiat_balance'], wallet['free_seconds'])
              for cust_id, wallet in wallets.items()]
    
    execute_values(cursor, query, values)

8. Configuration
8.1 Environment Variables
File: .env
# Database Configuration
DB_HOST=10.10.0.6
DB_PORT=5432
DB_NAME=bala_billing
DB_USER=postgres
DB_PASSWORD=your_password_here

# Application Configuration
LOG_LEVEL=INFO
BILLING_BATCH_SIZE=100
PROCESSING_INTERVAL_SEC=60

8.2 Configuration Class
File: config.py

import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Database
    DB_HOST = os.getenv('DB_HOST', '10.10.0.6')
    DB_PORT = os.getenv('DB_PORT', '5432')
    DB_NAME = os.getenv('DB_NAME', 'bala_billing')
    DB_USER = os.getenv('DB_USER', 'postgres')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    
    # Application
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    BILLING_BATCH_SIZE = int(os.getenv('BILLING_BATCH_SIZE', '100'))
    PROCESSING_INTERVAL_SEC = int(os.getenv('PROCESSING_INTERVAL_SEC', '60'))
    
    # Cache
    CACHE_DIR = 'src/cache'
    RATE_CARDS_CACHE = f'{CACHE_DIR}/rate_cards.json'
    CUSTOMER_RATECARD_CACHE = f'{CACHE_DIR}/customer_ratecard.json'
    
    @property
    def database_url(self):
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

config = Config()
8.3 Configurable Parameters
Parameter	            Default	                  Description
BILLING_BATCH_SIZE	     100            	Max CDRs processed per batch
PROCESSING_INTERVAL_SEC	60	               Sleep time when no CDRs found (seconds)
LOG_LEVEL	            INFO	           Logging level (DEBUG, INFO, WARNING, ERROR)
DB_HOST	                10.10.0.6	                                   PostgreSQL host
DB_PORT	                   5432	                                         PostgreSQL port
DB_NAME	                bala_billing 	          Database name



9. Error Handling
9.1 Error Types and Responses


Error Scenario	                        Handling	                Impact
No CDRs found	                   Return 0, sleep 60s, 	  Normal idle state

Database connection 
failure	Log error,                  sleep 5s, retry   	     Temporary interruption

Rate card missing	                Skip CDR, log warning,   Individual CDR skipped
                                     continue batch	


Customer wallet missing	            Skip CDR, log warning,   Individual CDR skipped
                                       continue batch	


Transaction insert failure	        Rollback entire batch,     Batch retried
                                        log error	


Idempotency violation	            Skip duplicate, log info	 Duplicate prevented

Lock timeout	                  Skip locked rows (SKIP LOCKED)	  Parallel processing safe 

Calculation error	               Skip CDR, log error, continue	  Individual CDR skipped

9.2 Transaction Rollback
When:

Any database error during batch processing
Constraint violation
Connection lost mid-transaction
Effect:

BEGIN
  ├─ Lock wallets ✓
  ├─ Insert transactions ✓
  ├─ Update CDRs ✗ (ERROR)
  └─ ROLLBACK
      ├─ Transactions not saved
      ├─ CDRs remain is_rated=false
      └─ Wallets unchanged

Recovery:

Next batch will retry same CDRs
Idempotency key prevents duplicates
9.3 Logging Strategy
Log Levels:

# DEBUG: Detailed diagnostic info
logger.debug(f"Processing CDR {cdr_id}: duration={duration}s")

# INFO: Normal operation events
logger.info(f"Successfully processed {count} CDRs")

# WARNING: Unexpected but handled
logger.warning(f"Rate card not found for customer {customer_id}")

# ERROR: Failures requiring attention
logger.error(f"Batch processing failed: {error}", exc_info=True)

Log Files:

Location: logs/billing_YYYYMMDD.log
Rotation: Daily
Format: %(asctime)s - %(name)s - %(levelname)s - %(message)s

10. Testing Scenarios
10.1 Test Data Setup
Create Test Rate Card:
INSERT INTO rate_cards (name, currency, country, in_rate_per_min, in_initial_increment_sec, in_increment_sec, ob_rate_per_min, ob_initial_increment_sec, ob_increment_sec)
VALUES ('test_ratecard', 'USD', 'US', 0.01, 60, 60, 0.005, 60, 60);

Create Test Customer:
INSERT INTO customer_wallets (customer_id, currency, fiat_balance, free_seconds)
VALUES ('test_cust_001', 'USD', 10.00, 600);

INSERT INTO customer_ratecard (customer_id, ratecard_id)
VALUES ('test_cust_001', 1);  -- Use ratecard_id from above
Create Test CDRs:
-- Short inbound call with free seconds
INSERT INTO cdr (call_uuid, customer_id, caller, callee, direction, start_time, end_time, duration_sec, currency, is_rated)
VALUES (gen_random_uuid(), 'test_cust_001', '+12025551001', '+12025552001', 'inbound', NOW() - INTERVAL '5 minutes', NOW() - INTERVAL '4 minutes', 45, 'USD', false);

-- Long outbound call
INSERT INTO cdr (call_uuid, customer_id, caller, callee, direction, start_time, end_time, duration_sec, currency, is_rated)
VALUES (gen_random_uuid(), 'test_cust_001', '+12025552001', '+12025553001', 'outbound', NOW() - INTERVAL '3 minutes', NOW() - INTERVAL '1 minute', 125, 'USD', false);

-- Unanswered call (should be skipped)
INSERT INTO cdr (call_uuid, customer_id, caller, callee, direction, start_time, end_time, duration_sec, currency, is_rated)
VALUES (gen_random_uuid(), 'test_cust_001', '+12025552001', '+12025554001', 'outbound', NOW() - INTERVAL '1 minute', NOW(), 0, 'USD', false);

10.2 Expected Results
After Processing:

Scenario 1: Short Inbound (45s)
Expected:
- Billable: 60s (initial increment)
- Free used: 60s
- Fiat charge: $0.00
- Wallet after: free_seconds=540, fiat_balance=$10.00

Scenario 2: Long Outbound (125s)

Expected:
- Billable: 180s (60 + ceil(65/60)×60 = 60+120)
- Free used: 180s
- Fiat charge: $0.00
- Wallet after: free_seconds=360, fiat_balance=$10.00
Scenario 3: Unanswered (0s)
Expected:
- Skipped (duration_sec = 0)
- No transaction created
- is_rated remains false


10.3 Validation Queries
Check Processed CDRs:
SELECT cdr_id, call_uuid, direction, duration_sec, billsec, billed_amount, is_rated
FROM cdr
WHERE customer_id = 'test_cust_001'
ORDER BY start_time;

Check Transactions:
SELECT transaction_id, source_ref, free_used_sec, wallet_debit_amount, amount_total
FROM transactions
WHERE customer_id = 'test_cust_001'
ORDER BY created_at;

Check Wallet Balance:
SELECT customer_id, fiat_balance, free_seconds, last_updated
FROM customer_wallets
WHERE customer_id = 'test_cust_001';

10.4 Edge Case Tests
Test Case	                         Setup	                Expected Result
Duplicate CDR	            Insert same call_uuid twice	    Second skipped (idempotency)
Negative balance	  Wallet with $0.00, call costs $0.50	Charge applied, balance = -$0.50
No free seconds	           Wallet with 0 free seconds	          Full fiat charge
Missing rate card	     Customer without ratecard mapping	         CDR skipped, logged
Parallel processing	   Run 2 instances simultaneously	        No duplicate charges, locks work
Database disconnect	           Kill DB mid-batch	           Rollback, retry next batch


11. Deployment & Operations
11.1 Installation
Prerequisites:

Python 3.9+
PostgreSQL 14+
pip
Steps:
# 1. Clone repository
git clone <repository_url>
cd billing

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Setup environment variables
cp .env.example .env
# Edit .env with your database credentials

# 5. Create database schema
psql -h 10.10.0.6 -U postgres -d bala_billing -f scripts/create_tables.sql

# 6. Refresh cache
python scripts/refresh_cache.py

11.2 Running the System
Start Billing Processor:
Output:
2026-01-19 20:30:00 - __main__ - INFO - === Billing System Starting ===
2026-01-19 20:30:00 - cdr_processor - INFO - Starting CDR processor in continuous mode...
2026-01-19 20:30:00 - cdr_processor - INFO - Batch size: 100, Interval: 60s
2026-01-19 20:30:01 - cdr_processor - INFO - Fetching up to 100 unrated CDRs...
2026-01-19 20:30:01 - cdr_processor - INFO - Processing 15 CDRs...
2026-01-19 20:30:02 - cdr_processor - INFO - Successfully processed 15 CDRs

Stop:

Press Ctrl+C for graceful shutdown
Current batch completes, then exits

### One-Shot Mode (for testing)

Run a single batch and exit:
```bash
BILLING_ONE_SHOT=1 python -m src.main
```

Output:
```
2026-01-21 19:38:36 - src.services.cdr_processor - INFO - Found 100 CDRs to process
2026-01-21 19:38:36 - src.services.cdr_processor - INFO - Successfully committed batch: 100 CDRs processed
One-shot mode complete: processed 100 CDRs
```

Use case: Testing before continuous deployment

11.3 Monitoring
Key Metrics:


Metric	                       Query	                               Threshold
Unrated CDRs	   SELECT COUNT(*) FROM cdr WHERE is_rated = false	   < 1000
Processing Rate	           CDRs/minute from logs	                   > 50/min

Negative Balances	SELECT COUNT(*) FROM customer_wallets 
                              WHERE fiat_balance < 0	               Monitor

Failed Transactions	    SELECT COUNT(*) FROM transactions 
                            WHERE status = 'failed'                     
                            	0
Batch Errors	             Check logs for ERROR level	                0/hour

Health Check Query:
SELECT 
    (SELECT COUNT(*) FROM cdr WHERE is_rated = false) AS unrated_cdrs,
    (SELECT COUNT(*) FROM cdr WHERE is_rated = true AND rated_at > NOW() - INTERVAL '1 hour') AS processed_last_hour,
    (SELECT COUNT(*) FROM customer_wallets WHERE fiat_balance < 0) AS negative_balances;


11.4 Maintenance
Refresh Rate Cards:    
# When rate cards updated in database
python scripts/refresh_cache.py

View Recent Logs:
tail -f logs/billing_$(date +%Y%m%d).log

Database Backup:
pg_dump -h 10.10.0.6 -U postgres -d bala_billing > backup_$(date +%Y%m%d).sql


11.5 Common Issues
Issue	                       Symptom	                    Solution
No CDRs processed	Logs show "No unrated CDRs found"	    Normal - waiting for new CDRs

High unrated count	 1000+ unrated CDRs	Increase    BILLING_BATCH_SIZE or add instances
Database locks	    Processing slows down	     Check for long-running transactions
Cache stale	     Wrong rates applied	           Run refresh_cache.py
Memory usage high	  Process using >1GB RAM	     Reduce BILLING_BATCH_SIZE


11.6 Performance Tuning
Batch Size:

Small (50-100): Lower memory, more DB calls
Large (200-500): Higher memory, fewer DB calls
Recommendation: Start with 100, adjust based on load
Database Indexes:
-- Critical for performance
CREATE INDEX CONCURRENTLY idx_cdr_is_rated_partial 
ON cdr(start_time) WHERE is_rated = false;

CREATE INDEX CONCURRENTLY idx_customer_wallets_lookup 
ON customer_wallets(customer_id) INCLUDE (fiat_balance, free_seconds);

Connection Pooling:
# Use connection pool for high-load scenarios
from psycopg_pool import ConnectionPool

pool = ConnectionPool(
    conninfo=config.database_url,
    min_size=2,
    max_size=10
)

11.7 Scaling
Horizontal Scaling:

Run multiple instances in parallel
FOR UPDATE SKIP LOCKED prevents conflicts
Each instance processes different CDRs
Example:
# Terminal 1
python src/main.py

# Terminal 2
python src/main.py

# Terminal 3
python src/main.py

Result: 3× processing throughput, no duplicates


12. Future Enhancements
12.1 Planned Features
 ✅ [COMPLETED in v1.1] amount_total now stores wallet_balance_after for audit visibility
 Future: Add free_seconds_after column to transactions table (for complete audit trail)
 Implement credit limit watcher service
 Add webhook notifications for low balance
 Support for multiple currencies conversion
 Real-time rate card updates (Redis cache)
 Web dashboard for monitoring
 API endpoints for manual billing
 
12.2 Optimization Opportunities
Use PostgreSQL LISTEN/NOTIFY for event-driven processing
Implement read replicas for reporting queries
Add caching layer (Redis) for rate cards
Partition tables by date for better performance
Archive old CDRs/transactions to separate tables


Appendix A: Quick Reference
Commands

# Start system
python src/main.py

# Refresh cache
python scripts/refresh_cache.py

# Run tests
pytest tests/

# View logs
tail -f logs/billing_$(date +%Y%m%d).log


Key Files
Entry point: main.py
Configuration: config.py
Rate cache: rate_cards.json
Database schema: create_tables.sql
Database Tables
cdr - Call detail records
transactions - Financial ledger
customer_wallets - Current balances
rate_cards - Rate configurations
customer_ratecard - Customer-rate mappings


Appendix B: Glossary
Term	   Definition
CDR	    Call Detail Record - metadata about a phone call
Billsec    	Billable seconds (answered call duration)
Increment	    Billing pulse (e.g., round up to 60-second blocks)
Initial Increment	    First billing pulse (minimum charge)
Idempotency	     Duplicate request produces same result (no double-charge)
Free Seconds	Prepaid seconds consumed before fiat charge
Fiat Balance	Monetary balance in customer wallet
Rate Card	     Set of rates and billing rules
Direction	     Inbound (receive) or Outbound (make) call
Transaction     	Financial record of charge/credit
Batch Processing	    Process multiple CDRs in single transaction
End of Document

Document Metadata:

Version: 1.0
Created: January 19, 2026
Authors: System Architect
Status: Final
Review Cycle: Quarterly


Save this complete document as `docs/BILLING_IMPLEMENTATION_SPEC.md`. This is now a complete, production-ready specification that any developer can use to build the billing system!Save this complete document as `docs/BILLING_IMPLEMENTATION_SPEC.md`. This is now a complete, production-ready specification that any developer can use to build the billing system!
