import queue
import threading
import time

import pymysql
import pymssql

from .config import settings


class _MySQLConnection:
    """Envuelve una conexión PyMySQL para exponer la misma API que pymssql
    (cursor(as_dict=True), commit, rollback, close, autocommit)."""

    def __init__(self, conn, pool=None):
        self._conn = conn
        self._pool = pool
        self._autocommit = False
        self._in_use = True

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
        if self._pool is not None:
            self._pool._release(self)
        else:
            self._conn.close()


class _MySQLPool:
    """Connection pool simple para PyMySQL."""

    def __init__(self, max_size=10, max_idle_sec=300):
        self._max_size = max_size
        self._max_idle = max_idle_sec
        self._pool = queue.Queue(maxsize=max_size)
        self._size = 0
        self._lock = threading.Lock()

    def _create_conn(self):
        return pymysql.connect(
            host=settings.db_server,
            user=settings.db_user,
            password=settings.db_password,
            database=settings.db_name,
            charset="utf8mb4",
            connect_timeout=10,
            autocommit=False,
        )

    def _release(self, wrapper):
        wrapper._in_use = False
        try:
            # Ping para verificar que la conexión sigue viva
            wrapper._conn.ping(reconnect=True)
            self._pool.put_nowait(wrapper)
        except Exception:
            with self._lock:
                self._size -= 1
            try:
                wrapper._conn.close()
            except Exception:
                pass

    def get_conn(self):
        # Intentar reutilizar una conexión existente
        while True:
            try:
                wrapper = self._pool.get_nowait()
                try:
                    wrapper._conn.ping(reconnect=True)
                    wrapper._in_use = True
                    return wrapper
                except Exception:
                    with self._lock:
                        self._size -= 1
                    try:
                        wrapper._conn.close()
                    except Exception:
                        pass
            except queue.Empty:
                break

        # Crear nueva conexión si no hemos alcanzado el máximo
        with self._lock:
            if self._size < self._max_size:
                self._size += 1
                try:
                    conn = self._create_conn()
                    return _MySQLConnection(conn, pool=self)
                except Exception:
                    self._size -= 1
                    raise

        # Pool lleno: esperar a que liberen una
        wrapper = self._pool.get(timeout=15)
        try:
            wrapper._conn.ping(reconnect=True)
            wrapper._in_use = True
            return wrapper
        except Exception:
            with self._lock:
                self._size -= 1
            try:
                wrapper._conn.close()
            except Exception:
                pass
            return self.get_conn()


_pool = _MySQLPool(max_size=10)


def get_conn():
    return _pool.get_conn()


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
