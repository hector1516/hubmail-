import pymssql

from .config import settings


def get_conn():
    return pymssql.connect(
        server=settings.db_server,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        login_timeout=10,
        autocommit=False,
    )