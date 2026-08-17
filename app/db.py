import pymysql
import pymssql

from .config import settings


class _MySQLConnection:
    """Envuelve una conexión PyMySQL para exponer la misma API que pymssql
    (cursor(as_dict=True), commit, rollback, close, autocommit)."""

    def __init__(self, conn):
        self._conn = conn
        self._autocommit = False

    @property
    def autocommit(self):
        return self._autocommit

    @autocommit.setter
    def autocommit(self, value):
        self._autocommit = bool(value)
        self._conn.autocommit(bool(value))

    def cursor(self, as_dict=False):
        if as_dict:
            return self._conn.cursor(cursor=pymysql.cursors.DictCursor)
        return self._conn.cursor()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def get_conn():
    return _MySQLConnection(pymysql.connect(
        host=settings.db_server,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        charset="utf8mb4",
        connect_timeout=10,
        autocommit=False,
    ))


def get_users_conn():
    return pymssql.connect(
        server=settings.users_db_server,
        user=settings.users_db_user,
        password=settings.users_db_password,
        database=settings.users_db_name,
        login_timeout=10,
        autocommit=False,
        charset="cp1252",
    )