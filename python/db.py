"""MySQL connection helper. Settings come from environment variables."""

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def get_engine() -> Engine:
    host = os.getenv("MYSQL_HOST", "127.0.0.1")
    port = os.getenv("MYSQL_PORT", "3307")
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "")
    database = os.getenv("MYSQL_DATABASE", "solar_analytics")
    return create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}")
