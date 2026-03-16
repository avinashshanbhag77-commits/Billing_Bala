# CDR (Call Detail Record) Table Description
**Database:** bala_billing  
**Schema:** public  
**Purpose:** Store call detail records for telephony/VoIP billing system

## Table Structure

### Columns

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| cdr_id | bigint | NOT NULL | nextval('cdr_cdr_id_seq') | Primary key, auto-incrementing CDR identifier |
| call_uuid | uuid | NOT NULL | - | Unique call identifier (UUID format) |
| customer_id | text | NOT NULL | - | Customer identifier |
| caller | text | NOT NULL | - | Calling party number (A-Number) |
| callee | text | NOT NULL | - | Called party number (B-Number) |
| last_destination | text | NULL | - | Final destination number after routing |
| direction | text | NOT NULL | - | Call direction: 'inbound' or 'outbound' |
| start_time | timestamp with time zone | NOT NULL | - | Call start/setup time |
| answer_time | timestamp with time zone | NULL | - | Time when call was answered |
| end_time | timestamp with time zone | NOT NULL | - | Call end/hangup time |
| duration_sec | integer | NOT NULL | - | Total call duration in seconds (from start to end) |
| billsec | integer | NOT NULL | - | Billable seconds (from answer to end) |
| hangup_cause | text | NULL | - | SIP/telephony hangup cause |
| sip_status | integer | NULL | - | SIP response code (e.g., 200, 486, 503) |
| ingress_trunk | text | NULL | - | Incoming trunk identifier |
| egress_trunk | text | NULL | - | Outgoing trunk identifier |
| route_id | text | NULL | - | Routing rule identifier |
| gateway_id | text | NULL | - | Gateway/carrier identifier |
| currency | character(3) | NOT NULL | - | Currency code (USD or CAD) |
| ratecard_id | bigint | NULL | - | Rate card used for billing |
| billed_amount | numeric(12,6) | NOT NULL | 0 | Amount billed for this call |
| transaction_id | bigint | NULL | - | Reference to transactions table |
| is_rated | boolean | NOT NULL | false | Flag indicating if call has been rated/billed |
| rated_at | timestamp with time zone | NULL | - | Timestamp when call was rated |
| created_at | timestamp with time zone | NOT NULL | now() | Record creation timestamp |

### Indexes

- **cdr_pkey** (PRIMARY KEY): btree (cdr_id)
- **cdr_call_uuid_key** (UNIQUE): btree (call_uuid) - Ensures no duplicate calls
- **idx_cdr_customer_time**: btree (customer_id, start_time DESC) - For customer call history
- **idx_cdr_transaction_id**: btree (transaction_id) - For transaction lookups

### Constraints

**Check Constraints:**
- **cdr_billsec_check**: billsec >= 0
- **cdr_currency_check**: currency IN ('USD', 'CAD')
- **cdr_direction_check**: direction IN ('inbound', 'outbound')
- **cdr_duration_sec_check**: duration_sec >= 0

**Foreign Key Constraints:**
- **fk_cdr_transaction**: transaction_id ? transactions.transaction_id

## Usage Notes

- **Call UUID**: Use call_uuid from your telephony system (unique per call)
- **Duration vs Billsec**: 
  - duration_sec: Total time including ringing
  - billsec: Only answered call time (used for billing)
- **Direction**: 
  - `inbound`: Customer receives call
  - `outbound`: Customer makes call
- **Rating Process**:
  1. CDR created with is_rated=false
  2. Rating engine processes CDR
  3. Creates transaction record
  4. Updates cdr.transaction_id and sets is_rated=true, rated_at=now()
- **Answer Time**: NULL if call was never answered (busy, no answer, etc.)
- **SIP Status Codes**: Standard SIP response codes (200=OK, 486=Busy, etc.)