from billing.bal_watch.config import watch_config

def format_row(row):
    return f"{row['customer_id']:<15} {row['wallet_balance']:<17.6f} {row['credit_limit']:<15.6f} {row['overlimit_amount']:.6f}"

def print_results(result):
    """
    Displays the classification structured result in the terminal.
    """
    summary = result['summary']
    
    print(f"\n[{result['cycle_timestamp']}] Wallet scan complete")
    print(f"Total wallets checked : {summary['total_wallets_checked']}")
    print(f"Overlimit wallets     : {summary['overlimit_count']}")
    print(f"Negative wallets      : {summary['negative_count']}")
    print(f"Low balance wallets   : {summary['low_balance_count']}")
    print(f"Low balance threshold : {watch_config.LOW_BALANCE_THRESHOLD}")
    print(f"Scan interval         : {watch_config.INTERVAL_SEC} sec\n")

    if result['overlimit_wallets']:
        print("Overlimit Table")
        print("================ OVERLIMIT WALLETS ================")
        print(f"{'customer_id':<15} {'wallet_balance':<17} {'credit_limit':<15} {'overlimit_amount'}")
        for row in result['overlimit_wallets']:
            print(format_row(row))
        print()
    
    if result['negative_wallets']:
        print("Negative Balance Table")
        print("================ NEGATIVE WALLETS ================")
        print(f"{'customer_id':<15} {'wallet_balance':<17} {'credit_limit':<15} {'overlimit_amount'}")
        for row in result['negative_wallets']:
            print(format_row(row))
        print()

    if result['low_balance_wallets']:
        print("Low Balance Table")
        print("================ LOW BALANCE WALLETS ================")
        print(f"{'customer_id':<15} {'wallet_balance':<17} {'credit_limit':<15} {'overlimit_amount'}")
        for row in result['low_balance_wallets']:
            print(format_row(row))
        print()
