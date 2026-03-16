# bal_watch Service Documentation

**Service Name:** bal_watch  
**Purpose:** Continuous monitoring and classification of customer wallet balances.  
**Technology Stack:** Python 3.9+, PostgreSQL, psycopg

---

## Overview

The `bal_watch` service is a background utility that periodically scans the `customer_wallets` table to identify and categorize wallets based on their balance status. It provides real-time visibility into overlimit usage, negative balances, and low balance thresholds.

## Component Structure

- **`main.py`**: The entry point of the service. Handles the main execution loop and periodic scanning.
- **`config.py`**: Manages configuration settings, including database connection details and monitoring thresholds.
- **`db.py`**: Contains database interaction logic for fetching wallet data.
- **`processor.py`**: Implements the core classification logic and result sorting.
- **`printer.py`**: Formats and prints classification results to the terminal.
- **`publisher.py`**: Placeholder for future event publishing functionality (e.g., API calls, notifications).

## Classification Logic

Wallets are categorized into three distinct tables based on the following rules:

### 1. Overlimit Wallets
- **Condition**: `balance < (-credit_limit)`
- **Sorting**: Priority given to the highest `overlimit_amount` (Absolute balance exceeding the credit limit).

### 2. Negative Wallets
- **Condition**: `0 > balance >= (-credit_limit)`
- **Sorting**: Sorted by lowest `wallet_balance`.

### 3. Low Balance Wallets
- **Condition**: `0 <= balance < LOW_BALANCE_THRESHOLD`
- **Sorting**: Sorted by lowest `wallet_balance`.

## Configuration

The service is configured via environment variables, typically stored in `setting.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `BAL_WATCH_INTERVAL_SEC` | Time interval (in seconds) between scans. | 100 |
| `BAL_WATCH_LOW_BALANCE_THRESHOLD` | Threshold value for identifying low balance wallets. | 100 |

## Sample Output

The service prints a summary and detailed tables for each category:

```text
[2026-03-13 13:27:15] Wallet scan complete
Total wallets checked : 150
Overlimit wallets     : 3
Negative wallets      : 5
Low balance wallets   : 12
Low balance threshold : 100.0
Scan interval         : 100 sec

================ OVERLIMIT WALLETS ================
customer_id     wallet_balance    credit_limit    overlimit_amount
cust_ABC        -550.000000       500.000000      50.000000
...
```

## Usage Notes

- The service uses `Decimal` for all financial calculations to ensure precision.
- Future versions will include an event publisher to automate notifications for overlimit and low balance events.
