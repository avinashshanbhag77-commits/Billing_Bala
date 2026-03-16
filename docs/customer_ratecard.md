# Customer Rate Card Table Description

**Database:** bala_billing  
**Schema:** public  
**Purpose:** Enforces one rate card per customer with effective dates

## Table Structure

### Columns

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| customer_id | text | NOT NULL | - | Primary key, customer identifier |
| ratecard_id | bigint | NOT NULL | - | Foreign key to rate_cards table |
| effective_from | timestamptz | NOT NULL | NOW() | Start of rate card applicability |
| effective_to | timestamptz | NULL | - | Optional end date for rate card |
| created_at | timestamptz | NOT NULL | NOW() | Record creation timestamp |
| updated_at | timestamptz | NOT NULL | NOW() | Last update timestamp |

### Indexes

- **customer_ratecard_pkey** (PRIMARY KEY): btree (customer_id)
- **idx_customer_ratecard_ratecard_id**: btree (ratecard_id)

### Constraints

**Check Constraints:**
- **customer_ratecard_effective_window**: effective_to IS NULL OR effective_to > effective_from

**Foreign Keys:**
- **customer_ratecard_ratecard_id_fkey**: FOREIGN KEY (ratecard_id) REFERENCES rate_cards(ratecard_id) ON UPDATE CASCADE ON DELETE RESTRICT

### Relationships

**References:**
- rate_cards.ratecard_id (FK with CASCADE on update, RESTRICT on delete)

## Usage Notes

- **One row per customer** enforced by primary key on customer_id
- Billing service looks up rate card by customer_id
- For rate changes, update the existing row rather than creating overlapping records
- `effective_to` is nullable for currently active rate cards
- Use `effective_from`/`effective_to` for future scheduling if needed