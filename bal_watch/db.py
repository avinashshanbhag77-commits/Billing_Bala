import psycopg
from psycopg.rows import dict_row
from billing.bal_watch.config import db_config

def get_db_connection():
    return psycopg.connect(
        host=db_config.DB_HOST,
        port=db_config.DB_PORT,
        dbname=db_config.DB_NAME,
        user=db_config.DB_USER,
        password=db_config.DB_PASSWORD
    )

def fetch_wallets():
    """
    Fetches all customer wallets.
    Returns a list of dictionaries.
    """
    query = """
    SELECT 
        customer_id, 
        currency, 
        fiat_balance, 
        credit_limit 
    FROM 
        customer_wallets;
    """
    
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query)
            wallets = cursor.fetchall()
            return wallets
    finally:
        if conn:
            conn.close()
