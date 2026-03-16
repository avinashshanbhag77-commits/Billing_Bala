# Transactions Table Description
**Database:** bala_billing  
**Schema:** public  
**Purpose:** Financial transaction ledger tracking all billing activities

## Table Structure

### Columns

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| transaction_id | bigint | NOT NULL | nextval('transactions_transaction_id_seq') | Primary key, auto-incrementing transaction identifier |
| customer_id | text | NOT NULL | - | Customer identifier (foreign reference) |
| source_type | text | NOT NULL | - | Type of transaction source: 'cdr', 'manual', 'subscription', 'adjustment', 'recharge' |
| source_ref | text | NULL | - | Reference to source record (e.g., CDR ID) |
| idempotency_key | text | NOT NULL | - | Unique key to prevent duplicate transactions |
| currency | character(3) | NOT NULL | - | Currency code (USD or CAD) |
| free_used_sec | integer | NOT NULL | 0 | Free seconds/minutes used from customer's plan |
| wallet_debit_amount | numeric(12,6) | NOT NULL | 0 | Amount debited from customer wallet |
| amount_total | numeric(12,6) | NOT NULL | 0 | Total transaction amount |
| ratecard_id | bigint | NULL | - | Reference to rate card used for billing |
| rate_per_min | numeric(12,6) | NULL | - | Rate per minute applied |
| billing_increment_sec | integer | NULL | - | Billing increment in seconds |
| status | text | NOT NULL | 'posted' | Transaction status: 'pending', 'posted', 'reversed', 'failed' |
| notes | text | NULL | - | Additional notes or metadata |
| created_at | timestamp with time zone | NOT NULL | now() | Transaction creation timestamp |

### Indexes

- **transactions_pkey** (PRIMARY KEY): btree (transaction_id)
- **idx_tx_customer_time**: btree (customer_id, created_at DESC) - For customer transaction history queries
- **idx_tx_source**: btree (source_type, source_ref) - For source reference lookups
- **transactions_idempotency_key_key** (UNIQUE): btree (idempotency_key)

### Constraints

**Check Constraints:**
- **transactions_currency_check**: currency IN ('USD', 'CAD')
- **transactions_free_used_sec_check**: free_used_sec >= 0
- **transactions_source_type_check**: source_type IN ('cdr', 'manual', 'subscription', 'adjustment', 'recharge')
- **transactions_status_check**: status IN ('pending', 'posted', 'reversed', 'failed')
- **transactions_wallet_debit_amount_check**: wallet_debit_amount >= 0

### Relationships

**Referenced By:**
- cdr.transaction_id ? transactions.transaction_id (FK: fk_cdr_transaction)

## Usage Notes

- **Idempotency**: Always use unique idempotency_key to prevent duplicate charges
- **Source Types**:
  - `cdr`: Call Detail Record billing
  - `manual`: Manual adjustments by admin
  - `subscription`: Recurring subscription charges
  - `adjustment`: Balance adjustments
  - `recharge`: Customer wallet recharge
- **Financial Fields**: All monetary amounts use numeric(12,6) for precision
- **Status Flow**: pending ? posted (or failed/reversed)