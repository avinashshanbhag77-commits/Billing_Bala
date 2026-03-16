import psycopg
from psycopg.rows import dict_row
from contextlib import contextmanager
from src.config import config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class DatabaseConnection:
    def __init__(self):
        self.connection_params = {
            'host': config.DB_HOST,
            'port': config.DB_PORT,
            'dbname': config.DB_NAME,
            'user': config.DB_USER,
            'password': config.DB_PASSWORD
        }
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = None
        try:
            conn = psycopg.connect(**self.connection_params)
            yield conn
            conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    @contextmanager
    def get_cursor(self, dict_cursor=True):
        """Context manager for database cursor"""
        with self.get_connection() as conn:
            cursor_kwargs = {'row_factory': dict_row} if dict_cursor else {}
            cursor = conn.cursor(**cursor_kwargs)
            try:
                yield cursor
            finally:
                cursor.close()

db = DatabaseConnection()