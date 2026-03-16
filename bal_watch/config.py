import os
from dotenv import load_dotenv

# Import the main project's DB configuration directly
from billing.src.config import config as db_config

# Load bal_watch specific environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "setting.env"))

class WatchConfig:
    INTERVAL_SEC = int(os.getenv('BAL_WATCH_INTERVAL_SEC', 100))
    LOW_BALANCE_THRESHOLD = float(os.getenv('BAL_WATCH_LOW_BALANCE_THRESHOLD', 100))

watch_config = WatchConfig()
