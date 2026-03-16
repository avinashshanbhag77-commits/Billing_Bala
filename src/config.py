import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Database
    DB_HOST = os.getenv('DB_HOST', '10.30.0.6')
    DB_PORT = os.getenv('DB_PORT', '5432')
    DB_NAME = os.getenv('DB_NAME', 'bala_billing_avi')
    DB_USER = os.getenv('DB_USER', 'avinash')
    DB_PASSWORD = os.getenv('DB_PASSWORD', 'OnidaMaruti1)')
    # DB connection retry/backoff
    DB_CONNECT_RETRIES = int(os.getenv('DB_CONNECT_RETRIES', '3'))
    DB_CONNECT_BACKOFF_SEC = int(os.getenv('DB_CONNECT_BACKOFF_SEC', '2'))
    DB_CONNECT_TIMEOUT_SEC = int(os.getenv('DB_CONNECT_TIMEOUT_SEC', '10'))
    
    # Application
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    BILLING_BATCH_SIZE = int(os.getenv('BILLING_BATCH_SIZE', '100'))
    PROCESSING_INTERVAL_SEC = int(os.getenv('PROCESSING_INTERVAL_SEC', '60'))
    
    @property
    def database_url(self):
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

config = Config()