# Customer Wallets Table Description

**Database:** bala_billing  
**Schema:** public  
**Purpose:** Current prepaid balances and free seconds per customer

## Table Structure

### Columns

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| customer_id | text | NOT NULL | - | Primary key, customer identifier |
| currency | char(3) | NOT NULL | - | Currency code (USD or CAD) |
| fiat_balance | numeric(14,6) | NOT NULL | 0 | Current spendable monetary balance |
| free_seconds | integer | NOT NULL | 0 | Remaining free usage seconds |
| last_updated | timestamptz | NOT NULL | NOW() | Timestamp of last balance change |
| version | integer | NOT NULL | 1 | Version number for optimistic locking |

### Indexes

- **customer_wallets_pkey** (PRIMARY KEY): btree (customer_id)
- **idx_customer_wallets_currency**: btree (currency)

### Constraints

**Check Constraints:**
- **customer_wallets_currency_check**: currency IN ('USD', 'CAD')
- **customer_wallets_fiat_balance_check**: fiat_balance >= 0
- **customer_wallets_free_seconds_check**: free_seconds >= 0
- **customer_wallets_version_check**: version >= 1

### Relationships

- No foreign key constraints (for performance)
- Logically linked to transactions table by customer_id
- Updated atomically during billing operations

## Usage Notes

- **Current state only** - historical changes tracked in transactions table
- Update within transaction using `SELECT ... FOR UPDATE` and increment `version`
- Use optimistic locking to detect concurrent modifications
- `fiat_balance` decremented for paid usage; `free_seconds` consumed first
- `last_updated` reflects most recent balance change for auditing
- Initialize new customers with zero balances or promotional amounts