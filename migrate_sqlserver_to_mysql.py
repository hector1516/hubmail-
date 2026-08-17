import pymysql
import pymssql

SRC = dict(server="172.26.117.220", user="sa", password="eyccazo",
           database="ECCSA_Admon_Pruebas", charset="cp1252")
DST = dict(host="172.26.90.159", user="hubmail", password="eyccazo",
           database="HUBMAIL", charset="utf8mb4", autocommit=False)

# tablas simples sin binario
SIMPLE_TABLES = [
    "HUBMAIL_Accounts",
    "HUBMAIL_Contacts",
    "HUBMAIL_Unread",
    "HUBMAIL_SyncState",
    "HUBMAIL_UserSettings",
    "HUBMAIL_Admins",
    "HUBMAIL_SpamLists",
    "HUBMAIL_Filters",
    "HUBMAIL_AddressBook",
    "HUBMAIL_UserMeta",
    "HUBMAIL_Folders",
    "HUBMAIL_Retention",
    "HUBMAIL_ActivityLog",
]


def copy_table(s, d, table, where=""):
    d.execute("DELETE FROM %s" % table)
    s.execute("SELECT * FROM %s %s" % (table, ("WHERE " + where) if where else ""))
    rows = s.fetchall()
    if not rows:
        return 0
    cols = list(rows[0].keys())
    d_cols = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    sql = "INSERT INTO %s (%s) VALUES (%s)" % (table, d_cols, marks)
    total = 0
    batch = [tuple(r[c] for c in cols) for r in rows]
    for i in range(0, len(batch), 500):
        d.executemany(sql, batch[i:i + 500])
        total += len(batch[i:i + 500])
    return total


def copy_messages(s, d):
    s.execute("SELECT MsgID, AccountID, Folder, UID, MessageIdHeader, InReplyTo, FromName, "
              "FromEmail, ToText, CcText, Subject, DateSent, Seen, Answered, Flagged, Deleted, "
              "Draft, HasAttachments, BodyHtml, BodyText, Size, SyncedAt, Spam, SenderIP "
              "FROM HUBMAIL_Messages")
    cols = ["MsgID", "AccountID", "Folder", "UID", "MessageIdHeader", "InReplyTo", "FromName",
            "FromEmail", "ToText", "CcText", "Subject", "DateSent", "Seen", "Answered", "Flagged",
            "Deleted", "Draft", "HasAttachments", "BodyHtml", "BodyText", "Size", "SyncedAt",
            "Spam", "SenderIP"]
    d_cols = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    sql = "INSERT INTO HUBMAIL_Messages (%s) VALUES (%s)" % (d_cols, marks)
    total = 0
    while True:
        rows = s.fetchmany(500)
        if not rows:
            break
        d.executemany(sql, [tuple(r[c] for c in cols) for r in rows])
        total += len(rows)
        d.connection.commit()
        if total % 50000 == 0:
            print("messages", total, flush=True)
    return total


def copy_attachments(s, d):
    s.execute("SELECT AttachID, AccountID, Folder, UID, Name, ContentType, Cid, Size, Data, "
              "SyncedAt FROM HUBMAIL_Attachments")
    cols = ["AttachID", "AccountID", "Folder", "UID", "Name", "ContentType", "Cid", "Size",
            "Data", "SyncedAt"]
    d_cols = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    sql = "INSERT INTO HUBMAIL_Attachments (%s) VALUES (%s)" % (d_cols, marks)
    total = 0
    while True:
        rows = s.fetchmany(50)
        if not rows:
            break
        params = []
        for r in rows:
            data = r["Data"]
            if data is not None and not isinstance(data, (bytes, bytearray)):
                data = bytes(data)
            params.append(tuple(data if c == "Data" else r[c] for c in cols))
        d.executemany(sql, params)
        total += len(rows)
        d.connection.commit()
        if total % 5000 == 0:
            print("attachments", total, flush=True)
    return total


def main():
    src = pymssql.connect(**SRC)
    dst = pymysql.connect(**DST)
    s = src.cursor(as_dict=True)
    d = dst.cursor()
    d.execute("SET SESSION sql_mode='NO_BACKSLASH_ESCAPES'")
    d.execute("SET FOREIGN_KEY_CHECKS=0")

    for t in SIMPLE_TABLES:
        n = copy_table(s, d, t)
        dst.commit()
        print(t, n)

    n = copy_messages(s, d)
    dst.commit()
    print("HUBMAIL_Messages", n)

    n = copy_attachments(s, d)
    dst.commit()
    print("HUBMAIL_Attachments", n)

    # admin por defecto si no existe
    d.execute("SELECT COUNT(*) FROM HUBMAIL_Admins")
    if d.fetchone()[0] == 0:
        d.execute("INSERT INTO HUBMAIL_Admins (UserID) VALUES (%s)", (1,))
        dst.commit()
        print("HUBMAIL_Admins: inserted default admin UserID=1")

    src.close()
    dst.close()


if __name__ == "__main__":
    main()