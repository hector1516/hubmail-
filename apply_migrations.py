import glob
import os
import time
from pathlib import Path

import pymysql

HERE = Path(__file__).resolve().parent

MAX_DB_RETRIES = 12
DB_RETRY_DELAY = 10


def _connect():
    last_err = None
    for attempt in range(1, MAX_DB_RETRIES + 1):
        try:
            return pymysql.connect(
                host=os.getenv("HUBMAIL_DB_SERVER", "172.26.90.159"),
                user=os.getenv("HUBMAIL_DB_USER", "hubmail"),
                password=os.getenv("HUBMAIL_DB_PASSWORD", "eyccazo"),
                database=os.getenv("HUBMAIL_DB_NAME", "HUBMAIL"),
                charset="utf8mb4",
                autocommit=True,
                connect_timeout=15,
            )
        except Exception as e:
            last_err = e
            print(f"[HUBMAIL] MySQL no disponible (intento {attempt}/{MAX_DB_RETRIES}): {e}", flush=True)
            time.sleep(DB_RETRY_DELAY)
    raise last_err


def main():
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS HUBMAIL_SchemaMigrations "
        "(MigrationName VARCHAR(200) PRIMARY KEY, AppliedAt DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    applied = set()
    cur.execute("SELECT MigrationName FROM HUBMAIL_SchemaMigrations")
    for r in cur.fetchall():
        applied.add(r[0])

    migrations = sorted(glob.glob(str(HERE / "migrations_mysql" / "[0-9]*.sql")))
    for m in migrations:
        name = os.path.basename(m)
        if name in applied:
            continue
        sql = Path(m).read_text(encoding="utf-8")
        print(f"[HUBMAIL] Aplicando {name} ...")
        for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
            cur.execute(stmt)
        cur.execute(
            "INSERT INTO HUBMAIL_SchemaMigrations (MigrationName) VALUES (%s)", (name,)
        )
        print(f"[HUBMAIL] OK {name}")

    print("[HUBMAIL] Migraciones al día.")
    conn.close()


if __name__ == "__main__":
    main()