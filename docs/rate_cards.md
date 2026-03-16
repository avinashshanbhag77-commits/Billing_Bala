# Rate Cards Table Description

**Database:** bala_billing  
**Schema:** public  
**Purpose:** Catalog of rate configurations for inbound and outbound billing

## Table Structure

### Columns

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| ratecard_id | bigint | NOT NULL | nextval('rate_cards_ratecard_id_seq') | Primary key |
| name | text | NOT NULL | - | Unique label for this rate card |
| currency | char(3) | NOT NULL | - | Currency code (USD or CAD) |
| country | text | NULL | - | Optional ISO country or region |
| in_rate_per_min | numeric(12,6) | NOT NULL | - | Inbound rate per minute of usage |
| in_initial_increment_sec | integer | NOT NULL | 60 | Inbound first billing increment in seconds |
| in_increment_sec | integer | NOT NULL | 60 | Inbound subsequent billing increments in seconds |
| ob_rate_per_min | numeric(12,6) | NOT NULL | - | Outbound rate per minute of usage |
| ob_initial_increment_sec | integer | NOT NULL | 60 | Outbound first billing increment in seconds |
| ob_increment_sec | integer | NOT NULL | 60 | Outbound subsequent billing increments in seconds |
| created_at | timestamptz | NOT NULL | NOW() | Record creation timestamp |
| updated_at | timestamptz | NOT NULL | NOW() | Last update timestamp |

### Indexes

- **rate_cards_pkey** (PRIMARY KEY): btree (ratecard_id)
- **rate_cards_name_key** (UNIQUE): btree (name)
- **idx_rate_cards_currency_country**: btree (currency, country)

### Constraints

**Check Constraints:**
- **rate_cards_currency_check**: currency IN ('USD', 'CAD')
- **rate_cards_rate_per_min_check**: rate_per_min >= 0
- **rate_cards_initial_increment_check**: initial_increment_sec > 0
- **rate_cards_increment_check**: increment_sec > 0

### Relationships

**Referenced By:**
- customer_ratecard.ratecard_id → rate_cards.ratecard_id
- transactions.ratecard_id → rate_cards.ratecard_id

## Cache Structure

When rate cards are cached via `scripts/refresh_cache.py`, the following fields are added:

| Field | Type | Description |
|-------|------|-------------|
| in_rate_per_sec | float (10 decimals) | Pre-calculated: `in_rate_per_min / 60`, rounded to 10 decimals |
| ob_rate_per_sec | float (10 decimals) | Pre-calculated: `ob_rate_per_min / 60`, rounded to 10 decimals |

**Cache Location:** `src/cache/rate_cards.json`

Example cached rate card:
```json
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