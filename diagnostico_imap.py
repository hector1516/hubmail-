import sys

from app.config import settings
from app.crypto import decrypt_secret
from app.db import get_conn


def main():
    account_id = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT * FROM HUBMAIL_Accounts WHERE AccountID=%s", (account_id,)
        )
        acc = cur.fetchone()
    finally:
        conn.close()

    if not acc:
        print(f"cuenta {account_id}: no existe")
        return

    pwd = decrypt_secret(acc["PasswordEnc"])
    if not pwd:
        print(f"cuenta {account_id}: no se pudo descifrar la contraseña")
        return

    print(f"probando {acc['Username']} @ {acc['IMAPHost']}:{acc['IMAPPort']} ...")
    from app.imap_client import IMAPClient, IMAPError

    imap = IMAPClient(acc["IMAPHost"], acc["IMAPPort"], acc["Username"], pwd)
    try:
        imap.connect()
        print("LOGIN OK")
    except IMAPError as e:
        print(f"LOGIN FALLÓ: {e}")
        return
    try:
        lf = imap.list_folders()
        print(f"LIST OK: {len(lf['folders'])} carpetas, delimiter={lf['delimiter']!r}")
        for f in lf["folders"][:10]:
            print("  -", f["name"])
    except IMAPError as e:
        print(f"LIST FALLÓ: {e}")
    finally:
        imap.close()


if __name__ == "__main__":
    main()