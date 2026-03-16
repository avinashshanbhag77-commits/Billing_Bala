-- Add credit_limit to customer_wallets table
ALTER TABLE customer_wallets ADD COLUMN IF NOT EXISTS credit_limit NUMERIC(14,6) NOT NULL DEFAULT 0;
