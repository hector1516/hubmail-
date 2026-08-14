import glob
import os
import sys
from pathlib import Path

import pymssql

HERE = Path(__file__).resolve().parent


def main():
    db = os.getenv("HUBMAIL_DB_NAME", "ECCSA_Admon_Pruebas")
    if "prueba" not in db.lower() and os.getenv("HUB_MIGRATE_PRODUCTION") != "1":
        print(
            f"[HUBMAIL] ABORTANDO: la BD '{db}' no es de pruebas y "
            "HUB_MIGRATE_PRODUCTION != 1",
            file=sys.stderr,
        )
        sys.exit(1)

    conn = pymssql.connect(
        server=os.getenv("HUBMAIL_DB_SERVER", "172.26.117.220"),
        user=os.getenv("HUBMAIL_DB_USER", "sa"),
        password=os.getenv("HUBMAIL_DB_PASSWORD", "eyccazo"),
        database=db,
        login_timeout=10,
        autocommit=True,
        charset="cp1252",
    )
    cur = conn.cursor()
    cur.execute(
        "IF OBJECT_ID('HUBMAIL_SchemaMigrations','U') IS NULL "
        "CREATE TABLE HUBMAIL_SchemaMigrations "
        "(MigrationName NVARCHAR(200) PRIMARY KEY, AppliedAt DATETIME DEFAULT GETDATE())"
    )
    applied = set()
    cur.execute("SELECT MigrationName FROM HUBMAIL_SchemaMigrations")
    for r in cur.fetchall():
        applied.add(r[0])

    migrations = sorted(glob.glob(str(HERE / "migrations" / "[0-9]*.sql")))
    for m in migrations:
        name = os.path.basename(m)
        if name in applied:
            continue
        sql = Path(m).read_text(encoding="utf-8")
        print(f"[HUBMAIL] Aplicando {name} ...")
        cur.execute(sql)
        cur.execute(
            "INSERT INTO HUBMAIL_SchemaMigrations (MigrationName) VALUES (%s)", (name,)
        )
        print(f"[HUBMAIL] OK {name}")

    print("[HUBMAIL] Migraciones al día.")
    conn.close()


if __name__ == "__main__":
    main()