# bal_watch

`bal_watch` is a continuous wallet monitoring service for the Balatrix Billing Platform.

## Features
- **Low balance detection:** Identifies wallets below a certain threshold.
- **Negative balance detection:** Identifies wallets with negative balances (but within credit limits).
- **Overlimit detection:** Identifies wallets that have exceeded their credit limit.

## Prerequisites
- Add the required `credit_limit` column to the `customer_wallets` table using the provided migration:
  `c:\billing\billing\scripts\mig_bal_watch.sql`
- A database configured and reachable using the settings in `c:\billing\billing\.env`

## Configuration
Inside `bal_watch/setting.env`, set:
- `BAL_WATCH_INTERVAL_SEC` (default: 100)
- `BAL_WATCH_LOW_BALANCE_THRESHOLD` (default: 100)

## Execution
Run the orchestrator:
```bash
python -m bal_watch.main
```
