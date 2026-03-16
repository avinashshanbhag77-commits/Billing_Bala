from datetime import datetime
from decimal import Decimal
from billing.bal_watch.config import watch_config

def _to_str(val):
    if isinstance(val, bytes):
        return val.decode('utf-8')
    return str(val)

def process_wallets(wallets):
    """
    Classifies wallets into overlimit, negative, and low_balance categories.
    Returns a structured dictionary with the results.
    """
    summary = {
        "total_wallets_checked": len(wallets),
        "overlimit_count": 0,
        "negative_count": 0,
        "low_balance_count": 0
    }
    
    overlimit_wallets = []
    negative_wallets = []
    low_balance_wallets = []

    for row in wallets:
        # Convert to Decimal for precision
        balance = Decimal(_to_str(row['fiat_balance']))
        credit_limit = Decimal(_to_str(row['credit_limit']))
        customer_id = _to_str(row['customer_id'])
        currency = _to_str(row['currency'])
        
        # Classification logic
        if balance < (-credit_limit):
            overlimit_amount = abs(balance) - credit_limit
            summary["overlimit_count"] += 1
            overlimit_wallets.append({
                "customer_id": customer_id,
                "wallet_balance": balance,
                "credit_limit": credit_limit,
                "overlimit_amount": overlimit_amount,
                "currency": currency
            })
        elif balance < Decimal('0'):
            summary["negative_count"] += 1
            negative_wallets.append({
                "customer_id": customer_id,
                "wallet_balance": balance,
                "credit_limit": credit_limit,
                "overlimit_amount": Decimal('0'),
                "currency": currency
            })
        elif balance < Decimal(str(watch_config.LOW_BALANCE_THRESHOLD)):
            summary["low_balance_count"] += 1
            low_balance_wallets.append({
                "customer_id": customer_id,
                "wallet_balance": balance,
                "credit_limit": credit_limit,
                "overlimit_amount": Decimal('0'),
                "currency": currency
            })

    # Sorting
    overlimit_wallets.sort(key=lambda x: x['overlimit_amount'], reverse=True)
    negative_wallets.sort(key=lambda x: x['wallet_balance'])
    low_balance_wallets.sort(key=lambda x: x['wallet_balance'])

    return {
        "cycle_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
        "overlimit_wallets": overlimit_wallets,
        "negative_wallets": negative_wallets,
        "low_balance_wallets": low_balance_wallets
    }
