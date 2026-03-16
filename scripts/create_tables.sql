`BEGIN;

-- =====================================================================
-- rate_cards: catalog of rate definitions
-- =====================================================================
CREATE TABLE IF NOT EXISTS rate_cards (
ratecard_id BIGSERIAL PRIMARY KEY,
name TEXT NOT NULL UNIQUE,
currency CHAR(3) NOT NULL,
country TEXT NULL,
rate_per_min NUMERIC(12,6) NOT NULL,
initial_increment_sec INTEGER NOT NULL DEFAULT 60,
increment_sec INTEGER NOT NULL DEFAULT 60,
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
CONSTRAINT rate_cards_currency_check CHECK (currency IN ('USD','CAD')),
CONSTRAINT rate_cards_rate_per_min_check CHECK (rate_per_min >= 0),
CONSTRAINT rate_cards_initial_increment_check CHECK (initial_increment_sec > 0),
CONSTRAINT rate_cards_increment_check CHECK (increment_sec > 0)
);

-- Useful lookups
CREATE INDEX IF NOT EXISTS idx_rate_cards_currency_country
ON rate_cards (currency, country);

-- =====================================================================
-- customer_ratecard: enforce one rate card per customer
-- =====================================================================
CREATE TABLE IF NOT EXISTS customer_ratecard (
customer_id TEXT PRIMARY KEY,
ratecard_id BIGINT NOT NULL REFERENCES rate_cards(ratecard_id) ON UPDATE CASCADE ON DELETE RESTRICT,
effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
effective_to TIMESTAMPTZ NULL,
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
CONSTRAINT customer_ratecard_effective_window CHECK (effective_to IS NULL OR effective_to > effective_from)
);

CREATE INDEX IF NOT EXISTS idx_customer_ratecard_ratecard_id
ON customer_ratecard (ratecard_id);

-- =====================================================================
-- customer_wallets: current balances for prepaid usage
-- =====================================================================
CREATE TABLE IF NOT EXISTS customer_wallets (
customer_id TEXT PRIMARY KEY,
currency CHAR(3) NOT NULL,
fiat_balance NUMERIC(14,6) NOT NULL DEFAULT 0,
free_seconds INTEGER NOT NULL DEFAULT 0,
last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
version INTEGER NOT NULL DEFAULT 1,
CONSTRAINT customer_wallets_currency_check CHECK (currency IN ('USD','CAD')),
CONSTRAINT customer_wallets_fiat_balance_check CHECK (fiat_balance >= 0),
CONSTRAINT customer_wallets_free_seconds_check CHECK (free_seconds >= 0),
CONSTRAINT customer_wallets_version_check CHECK (version >= 1)
);

CREATE INDEX IF NOT EXISTS idx_customer_wallets_currency
ON customer_wallets (currency);

-- =====================================================================
-- Optional: strengthen transactions linkage to rate_cards
-- Skips if column missing; adjust if your schema differs.
-- =====================================================================
DO $$
BEGIN
IF NOT EXISTS (
SELECT 1
FROM pg_constraint
WHERE conname = 'fk_transactions_ratecard'
) THEN
BEGIN
ALTER TABLE transactions
ADD CONSTRAINT fk_transactions_ratecard
FOREIGN KEY (ratecard_id)
REFERENCES rate_cards(ratecard_id)
ON UPDATE CASCADE
ON DELETE SET NULL;
EXCEPTION
WHEN undefined_table THEN
RAISE NOTICE 'transactions table not found or column missing; skipping FK addition';
END;
END IF;
END
$$;

COMMIT;`