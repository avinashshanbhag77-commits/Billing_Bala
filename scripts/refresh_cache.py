#!/usr/bin/env python3
"""
Refresh both rate cards and customer ratecard caches.
Run this script whenever rate cards or customer assignments change.
Includes pre-calculated per-second rates for billing efficiency.
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database.connection import db
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

CACHE_DIR = Path(__file__).parent.parent / "src" / "cache"
RATE_CARDS_CACHE = CACHE_DIR / "rate_cards.json"
CUSTOMER_RATECARD_CACHE = CACHE_DIR / "customer_ratecard.json"


def round_to_decimals(value, decimals=10):
    """Round float to specified decimal places (default 10)"""
    if value is None:
        return None
    return round(float(value), decimals)


def to_string(value):
    """Convert bytes or any value to string"""
    if isinstance(value, bytes):
        return value.decode('utf-8')
    return value


def load_rate_cards_from_db():
    """Fetch all rate cards from database"""
    query = """
        SELECT 
            ratecard_id,
            name,
            currency,
            country,
            in_rate_per_min,
            in_initial_increment_sec,
            in_increment_sec,
            ob_rate_per_min,
            ob_initial_increment_sec,
            ob_increment_sec,
            created_at,
            updated_at
        FROM rate_cards
        ORDER BY ratecard_id
    """
    
    with db.get_cursor() as cursor:
        cursor.execute(query)
        rows = cursor.fetchall()
    
    rate_cards = []
    for row in rows:
        in_rate_per_min = float(row['in_rate_per_min'])
        ob_rate_per_min = float(row['ob_rate_per_min'])
        
        # Calculate per-second rates from per-minute rates, rounded to 10 decimals
        in_rate_per_sec = round_to_decimals(in_rate_per_min / 60, 10)
        ob_rate_per_sec = round_to_decimals(ob_rate_per_min / 60, 10)
        
        rate_cards.append({
            'ratecard_id': row['ratecard_id'],
            'name': to_string(row['name']),
            'currency': to_string(row['currency']),
            'country': to_string(row['country']) if row['country'] else None,
            'in_rate_per_min': round_to_decimals(in_rate_per_min, 10),
            'in_rate_per_sec': in_rate_per_sec,
            'in_initial_increment_sec': row['in_initial_increment_sec'],
            'in_increment_sec': row['in_increment_sec'],
            'ob_rate_per_min': round_to_decimals(ob_rate_per_min, 10),
            'ob_rate_per_sec': ob_rate_per_sec,
            'ob_initial_increment_sec': row['ob_initial_increment_sec'],
            'ob_increment_sec': row['ob_increment_sec'],
            'created_at': row['created_at'].isoformat() if row['created_at'] else None,
            'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None,
        })
    
    return rate_cards


def load_customer_ratecards_from_db():
    """Fetch all customer→ratecard mappings from database (mapping only)"""
    query = """
        SELECT 
            customer_id,
            ratecard_id,
            effective_from,
            effective_to,
            created_at,
            updated_at
        FROM customer_ratecard
        WHERE effective_to IS NULL OR effective_to > NOW()
        ORDER BY customer_id
    """
    
    with db.get_cursor() as cursor:
        cursor.execute(query)
        rows = cursor.fetchall()
    
    customer_ratecards = []
    for row in rows:
        customer_ratecards.append({
            'customer_id': to_string(row['customer_id']),
            'ratecard_id': row['ratecard_id'],
            'effective_from': row['effective_from'].isoformat() if row['effective_from'] else None,
            'effective_to': row['effective_to'].isoformat() if row['effective_to'] else None,
            'created_at': row['created_at'].isoformat() if row['created_at'] else None,
            'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None,
        })
    
    return customer_ratecards


def save_rate_cards_cache(rate_cards):
    """Save rate cards to JSON cache file"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    cache_data = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'rate_cards': rate_cards,
        'total': len(rate_cards)
    }
    
    with open(RATE_CARDS_CACHE, 'w') as f:
        json.dump(cache_data, f, indent=2)
    
    logger.info(f"Rate cards cache saved ({len(rate_cards)} total)")


def save_customer_ratecard_cache(customer_ratecards):
    """Save customer ratecards to JSON cache file"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    cache_data = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'customer_ratecard': customer_ratecards,
        'total': len(customer_ratecards)
    }
    
    with open(CUSTOMER_RATECARD_CACHE, 'w') as f:
        json.dump(cache_data, f, indent=2)
    
    logger.info(f"Customer ratecard cache saved ({len(customer_ratecards)} total)")


def main():
    try:
        logger.info("Refreshing all caches...")
        print("\nRefreshing caches...\n")
        
        # Load and save rate cards
        logger.info("Loading rate cards from database...")
        rate_cards = load_rate_cards_from_db()
        save_rate_cards_cache(rate_cards)
        
        # Load and save customer ratecards (mapping only)
        logger.info("Loading customer->ratecard mappings from database...")
        customer_ratecards = load_customer_ratecards_from_db()
        save_customer_ratecard_cache(customer_ratecards)
        
        print(f"Cache refresh complete!")
        print(f"   • Rate cards: {len(rate_cards)}")
        print(f"   • Customer mappings: {len(customer_ratecards)}")
        print(f"   • Cache location: {CACHE_DIR}\n")
        
    except Exception as e:
        logger.error(f"Error refreshing caches: {e}")
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()