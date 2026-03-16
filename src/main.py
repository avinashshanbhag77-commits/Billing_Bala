#!/usr/bin/env python3
import sys
import os
from pathlib import Path

# Add parent directory to path so imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.cdr_processor import CDRProcessor
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

def main():
    logger.info("=== Billing System Starting ===")
    
    processor = CDRProcessor()
    
    try:
        # Optional one-shot mode for testing
        if os.getenv('BILLING_ONE_SHOT', '0') == '1':
            count = processor.process_batch()
            logger.info(f"One-shot mode complete: processed {count} CDRs")
        else:
            # Run continuous processing
            processor.run_continuous()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()