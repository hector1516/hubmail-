import email
import email.utils
import json
import threading
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import escape

from .crypto import decrypt_secret
from .db import get_conn
from .filters import apply_filters, extract_sender_ip
from .imap_client import (
    IMAPClient,
    IMAPError,
    _decode_mime,
    _decode_payload,
    _parse_addresses,
    _parse_folder_line,
)

SYNC_INTERVAL = 300  # 5 minutos

RETENTION_MAX_KEEP = 10
RETENTION_MAX_DAYS = 7
RETENTION_FOLDER_PARTS = [
    "junk", "spam", "bulk", "trash", "deleted",
    "papelera", "basura", "no deseado", "elementos eliminados", "correo no deseado",
]

_locks_guard = threading.Lock()
_folder_locks = {}
_account_cooldown = {}
_account_busy = {}


def _account_in_use(account_id):
    return _account_busy.get(account_id, False)


def _cooldown_active(account_id):
    cd = _account_cooldown.get(account_id)
    return cd is not None and datetime.now() < cd


def _mark_connected(account_id):
    _account_cooldown[account_id] = datetime.now() + timedelta(seconds=SYNC_INTERVAL)


def _safe(value):
    if value is None:
        return None
    try:
        value.encode("cp1252")
        return value
    except UnicodeEncodeError:
        return value.encode("cp1252", "ignore").decode("cp1252")


def _data_hex(value):
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return value


def _addr_json(items):
    return json.dumps([{"name": it.get("name", ""), "email": it.get("email", "")} for it in items], ensure_ascii=False)


def _addr_from_json(text):
    try:
        return json.loads(text or "[]")
    except Exception:
        return []


def _fmt_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone().replace(tzinfo=None)


def parse_email(raw_bytes):
    msg = email.message_from_bytes(raw_bytes)
    body_html = ""
    body_text = ""
    attachments = 0
    attachment_items = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        ct = part.get_content_type()
        disp = part.get_content_disposition() or ""
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        fn = part.get_filename()
        if disp == "attachment" or (fn and not disp):
            attachments += 1
            attachment_items.append({
                "name": _decode_mime(fn) or "adjunto",
                "content_type": ct,
                "cid": "",
                "size": len(payload),
                "data": payload,
            })
        elif ct.startswith("image/") and disp == "inline":
            cid = part.get("Content-ID")
            cid_clean = cid.strip("<>") if cid else ""
            attachment_items.append({
                "name": _decode_mime(fn) or cid_clean or "inline",
                "content_type": ct,
                "cid": cid_clean,
                "size": len(payload),
                "data": payload,
            })
        elif ct == "text/html" and not body_html:
            body_html = _decode_payload(payload, part.get_content_charset())
        elif ct == "text/plain" and not body_text:
            body_text = _decode_payload(payload, part.get_content_charset())
    if not body_html and body_text:
        body_html = "<pre>" + escape(body_text) + "</pre>"

    date = None
    try:
        if msg.get("Date"):
            date = _fmt_dt(parsedate_to_datetime(msg.get("Date")))
    except Exception:
        date = None

    from_list = _parse_addresses(msg.get("From"))
    return {
        "from_name": from_list[0]["name"] if from_list else "",
        "from_email": from_list[0]["email"] if from_list else "",
        "to_text": _addr_json(_parse_addresses(msg.get("To"))),
        "cc_text": _addr_json(_parse_addresses(msg.get("Cc"))),
        "subject": _decode_mime(msg.get("Subject")),
        "date": date,
        "message_id": msg.get("Message-ID"),
        "in_reply_to": msg.get("In-Reply-To"),
        "body_html": body_html,
        "body_text": body_text,
        "attachments": attachments,
        "attachment_items": attachment_items,
        "size": len(raw_bytes),
    }


def _get_account_row(account_id):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute("SELECT * FROM HUBMAIL_Accounts WHERE AccountID=%s", (account_id,))
        return cur.fetchone()
    finally:
        conn.close()


def canonical_account_id(account_id):
    row = _get_account_row(account_id)
    if row and row.get("CanonicalAccountID"):
        return int(row["CanonicalAccountID"])
    return account_id


def canonical_account_row(account_id):
    row = _get_account_row(account_id)
    if row and row.get("CanonicalAccountID"):
        cid = int(row["CanonicalAccountID"])
        if cid != account_id:
            crow = _get_account_row(cid)
            if crow:
                return crow
    return row


def _load_existing(account_id, folder):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT m.UID, m.BodyHtml, m.HasAttachments, "
            "(SELECT COUNT(*) FROM HUBMAIL_Attachments a WHERE a.AccountID=m.AccountID AND a.Folder=m.Folder AND a.UID=m.UID) AS AttCount "
            "FROM HUBMAIL_Messages m WHERE m.AccountID=%s AND m.Folder=%s",
            (account_id, folder),
        )
        result = {}
        for r in cur.fetchall():
            uid = int(r["UID"])
            needs_att = bool(r["HasAttachments"]) and (r["AttCount"] or 0) == 0
            result[uid] = {
                "has_body": bool(r["BodyHtml"]),
                "needs_full": needs_att,
            }
        return result
    finally:
        conn.close()


def _sync_state(account_id, folder):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT LastSync, TotalCount FROM HUBMAIL_SyncState WHERE AccountID=%s AND Folder=%s",
            (account_id, folder),
        )
        row = cur.fetchone()
        if not row:
            return None, 0
        last = row["LastSync"]
        if last is not None and last.tzinfo is not None:
            last = last.replace(tzinfo=None)
        return last, row["TotalCount"] or 0
    finally:
        conn.close()


def _update_sync_state(account_id, folder):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT COUNT(*) AS N FROM HUBMAIL_Messages WHERE AccountID=%s AND Folder=%s",
            (account_id, folder),
        )
        total = cur.fetchone()["N"]
        cur.execute(
            "SELECT COUNT(*) AS N FROM HUBMAIL_SyncState WHERE AccountID=%s AND Folder=%s",
            (account_id, folder),
        )
        if cur.fetchone()["N"]:
            cur.execute(
                "UPDATE HUBMAIL_SyncState SET LastSync=GETDATE(), TotalCount=%s "
                "WHERE AccountID=%s AND Folder=%s",
                (total, account_id, folder),
            )
        else:
            cur.execute(
                "INSERT INTO HUBMAIL_SyncState (AccountID, Folder, LastSync, TotalCount) VALUES (%s,%s,GETDATE(),%s)",
                (account_id, folder, total),
            )
        conn.commit()
    finally:
        conn.close()


def _folder_db_count(account_id, folder):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT COUNT(*) AS N FROM HUBMAIL_Messages WHERE AccountID=%s AND Folder=%s",
            (account_id, folder),
        )
        return cur.fetchone()["N"]
    finally:
        conn.close()


def _replace_attachments(account_id, folder, uid, items):
    if not items:
        return
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM HUBMAIL_Attachments WHERE AccountID=%s AND Folder=%s AND UID=%s",
            (account_id, folder, uid),
        )
        cur.executemany(
            "INSERT INTO HUBMAIL_Attachments (AccountID, Folder, UID, Name, ContentType, Cid, Size, Data) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,CONVERT(VARBINARY(MAX),%s,2))",
            [
                (account_id, folder, uid, _safe(a["name"]), _safe(a["content_type"]), _safe(a["cid"]),
                 a["size"], _data_hex(a["data"]))
                for a in items
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _upsert_message(account_id, folder, uid, flags, raw):
    p = parse_email(raw)
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT COUNT(*) AS N FROM HUBMAIL_Messages WHERE AccountID=%s AND Folder=%s AND UID=%s",
            (account_id, folder, uid),
        )
        exists = cur.fetchone()["N"] > 0
        base = [
            _safe(p["message_id"]), _safe(p["in_reply_to"]),
            _safe(p["from_name"]), _safe(p["from_email"]),
            _safe(p["to_text"]), _safe(p["cc_text"]),
            _safe(p["subject"]), p["date"],
            1 if "\\Seen" in flags else 0,
            1 if "\\Answered" in flags else 0,
            1 if "\\Flagged" in flags else 0,
            1 if "\\Draft" in flags else 0,
            1 if p["attachments"] else 0,
            _safe(p["body_html"]), _safe(p["body_text"]), p["size"],
        ]
        if exists:
            cur.execute(
                """UPDATE HUBMAIL_Messages SET
                       MessageIdHeader=%s, InReplyTo=%s, FromName=%s, FromEmail=%s,
                       ToText=%s, CcText=%s, Subject=%s, DateSent=%s,
                       Seen=%s, Answered=%s, Flagged=%s, Draft=%s,
                       HasAttachments=%s, BodyHtml=%s, BodyText=%s, Size=%s,
                       SyncedAt=GETDATE()
                   WHERE AccountID=%s AND Folder=%s AND UID=%s""",
                base + [account_id, folder, uid],
            )
        else:
            cur.execute(
                """INSERT INTO HUBMAIL_Messages
                       (AccountID, Folder, UID, MessageIdHeader, InReplyTo, FromName, FromEmail,
                        ToText, CcText, Subject, DateSent, Seen, Answered, Flagged, Deleted, Draft,
                        HasAttachments, BodyHtml, BodyText, Size)
                   VALUES
                       (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s,%s,%s)""",
                [account_id, folder, uid] + base,
            )
        conn.commit()
    finally:
        conn.close()
    _replace_attachments(account_id, folder, uid, p["attachment_items"])


def _insert_many(account_id, folder, items):
    if not items:
        return 0
    conn = get_conn()
    try:
        cur = conn.cursor()
        data = []
        att_rows = []
        for uid, meta, raw in items:
            try:
                p = parse_email(raw)
            except Exception as e:
                print(f"[SYNC] parse skip uid={uid}: {e}", flush=True)
                continue
            data.append([
                account_id, folder, uid,
                _safe(p["message_id"]), _safe(p["in_reply_to"]),
                _safe(p["from_name"]), _safe(p["from_email"]),
                _safe(p["to_text"]), _safe(p["cc_text"]),
                _safe(p["subject"]), p["date"],
                1 if "\\Seen" in meta else 0,
                1 if "\\Answered" in meta else 0,
                1 if "\\Flagged" in meta else 0,
                1 if "\\Draft" in meta else 0,
                1 if p["attachments"] else 0,
                _safe(p["body_html"]), _safe(p["body_text"]), p["size"],
                extract_sender_ip(raw),
            ])
            for a in p["attachment_items"]:
                att_rows.append(
                    (account_id, folder, uid, _safe(a["name"]), _safe(a["content_type"]),
                     _safe(a["cid"]), a["size"], _data_hex(a["data"]))
                )
        if not data:
            return 0
        sql = """INSERT INTO HUBMAIL_Messages
               (AccountID, Folder, UID, MessageIdHeader, InReplyTo, FromName, FromEmail,
                ToText, CcText, Subject, DateSent, Seen, Answered, Flagged, Deleted, Draft,
                HasAttachments, BodyHtml, BodyText, Size, SenderIP)
               VALUES
                (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s,%s,%s,%s)"""
        ok = 0
        try:
            cur.executemany(sql, data)
            ok = len(data)
        except Exception as e:
            print(f"[SYNC] batch insert falló ({e}), reintento por fila", flush=True)
            conn.rollback()
            cur = conn.cursor()
            for row in data:
                try:
                    cur.execute(sql, row)
                    ok += 1
                except Exception as e2:
                    print(f"[SYNC] fila rechazada uid={row[2]}: {e2}", flush=True)
        conn.commit()
        if att_rows:
            try:
                cur.executemany(
                    "INSERT INTO HUBMAIL_Attachments (AccountID, Folder, UID, Name, ContentType, Cid, Size, Data) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,CONVERT(VARBINARY(MAX),%s,2))",
                    att_rows,
                )
                conn.commit()
            except Exception as e:
                print(f"[SYNC] attachments batch falló ({e}), reintento por fila", flush=True)
                conn.rollback()
                cur = conn.cursor()
                for row in att_rows:
                    try:
                        cur.execute(
                            "INSERT INTO HUBMAIL_Attachments (AccountID, Folder, UID, Name, ContentType, Cid, Size, Data) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,CONVERT(VARBINARY(MAX),%s,2))",
                            row,
                        )
                    except Exception as e2:
                        print(f"[SYNC] adjunto rechazado uid={row[2]}: {e2}", flush=True)
                conn.commit()
        return ok
    finally:
        conn.close()


def _update_body_many(account_id, folder, items):
    if not items:
        return 0
    conn = get_conn()
    try:
        cur = conn.cursor()
        data = []
        att_rows = []
        for uid, meta, raw in items:
            try:
                p = parse_email(raw)
            except Exception as e:
                print(f"[SYNC] parse skip uid={uid}: {e}", flush=True)
                continue
            data.append([
                _safe(p["message_id"]), _safe(p["in_reply_to"]),
                _safe(p["from_name"]), _safe(p["from_email"]),
                _safe(p["to_text"]), _safe(p["cc_text"]),
                _safe(p["subject"]), p["date"],
                1 if "\\Seen" in meta else 0,
                1 if "\\Answered" in meta else 0,
                1 if "\\Flagged" in meta else 0,
                1 if "\\Draft" in meta else 0,
                1 if p["attachments"] else 0,
                _safe(p["body_html"]), _safe(p["body_text"]), p["size"],
                account_id, folder, uid,
            ])
            for a in p["attachment_items"]:
                att_rows.append(
                    (account_id, folder, uid, _safe(a["name"]), _safe(a["content_type"]),
                     _safe(a["cid"]), a["size"], _data_hex(a["data"]))
                )
        if not data:
            return 0
        sql = """UPDATE HUBMAIL_Messages SET
               MessageIdHeader=%s, InReplyTo=%s, FromName=%s, FromEmail=%s,
               ToText=%s, CcText=%s, Subject=%s, DateSent=%s,
               Seen=%s, Answered=%s, Flagged=%s, Draft=%s,
               HasAttachments=%s, BodyHtml=%s, BodyText=%s, Size=%s,
               SyncedAt=GETDATE()
               WHERE AccountID=%s AND Folder=%s AND UID=%s"""
        ok = 0
        try:
            cur.executemany(sql, data)
            ok = len(data)
        except Exception as e:
            print(f"[SYNC] batch update falló ({e}), reintento por fila", flush=True)
            conn.rollback()
            cur = conn.cursor()
            for row in data:
                try:
                    cur.execute(sql, row)
                    ok += 1
                except Exception as e2:
                    print(f"[SYNC] fila rechazada uid={row[-1]}: {e2}", flush=True)
        conn.commit()
        uids = sorted({r[2] for r in att_rows})
        for uid in uids:
            rows = [r for r in att_rows if r[2] == uid]
            try:
                _replace_attachments(account_id, folder, uid, [
                    {"name": r[3], "content_type": r[4], "cid": r[5], "size": r[6], "data": r[7]}
                    for r in rows
                ])
            except Exception as e:
                print(f"[SYNC] adjuntos uid={uid}: {e}", flush=True)
        return ok
    finally:
        conn.close()


def _update_flags(account_id, folder, flags_map):
    if not flags_map:
        return
    conn = get_conn()
    try:
        cur = conn.cursor()
        rows = [
            (
                1 if "\\Seen" in fl else 0,
                1 if "\\Flagged" in fl else 0,
                1 if "\\Answered" in fl else 0,
                1 if "\\Draft" in fl else 0,
                account_id, folder, uid,
            )
            for uid, fl in flags_map.items()
        ]
        cur.executemany(
            "UPDATE HUBMAIL_Messages SET Seen=%s, Flagged=%s, Answered=%s, Draft=%s "
            "WHERE AccountID=%s AND Folder=%s AND UID=%s",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def _sync_folder_conn(account_id, folder, imap, force=False, with_bodies=True):
    key = (account_id, folder)
    with _locks_guard:
        lock = _folder_locks.setdefault(key, threading.Lock())
    if not lock.acquire(blocking=False):
        print(f"[SYNC] skip {account_id}/{folder}: lock ocupado", flush=True)
        return {"new": 0, "updated": 0, "total": 0}

    try:
        last, total = _sync_state(account_id, folder)
        fresh = last is not None and (datetime.now() - last).total_seconds() < SYNC_INTERVAL \
            and _folder_db_count(account_id, folder) == total
        if not with_bodies and fresh and not force:
            return {"new": 0, "updated": 0, "total": total}

        try:
            uids = imap.fetch_uid_list(folder)
            flags_map = imap.fetch_flags_map(folder, uids)
            print(f"[SYNC] {account_id}/{folder}: uids={len(uids)}", flush=True)
        except IMAPError as e:
            print(f"[SYNC] {account_id}/{folder}: error IMAP uid/flags: {e}", flush=True)
            return {"new": 0, "updated": 0, "total": 0}

        existing = _load_existing(account_id, folder)
        new_uids = [u for u in uids if u not in existing]
        missing_body = [u for u in uids if u in existing and (not existing[u]["has_body"] or existing[u]["needs_full"])]

        new = updated = 0
        if new_uids:
            try:
                it = imap.iter_headers_many(folder, new_uids) if not with_bodies \
                    else imap.iter_full_many(folder, new_uids)
                for chunk in it:
                    new += _insert_many(account_id, folder, chunk)
            except Exception as e:
                print(f"[SYNC] error fetch new {account_id}/{folder}: {e}", flush=True)
        if missing_body and with_bodies:
            try:
                for chunk in imap.iter_full_many(folder, missing_body):
                    updated += _update_body_many(account_id, folder, chunk)
            except Exception as e:
                print(f"[SYNC] error fetch body {account_id}/{folder}: {e}", flush=True)
        if with_bodies and new_uids:
            try:
                apply_filters(account_id, folder, new_uids, imap)
            except Exception as e:
                print(f"[SYNC] filtros {account_id}/{folder}: {e}", flush=True)
        try:
            _update_flags(account_id, folder, flags_map)
        except Exception as e:
            print(f"[SYNC] error flags {account_id}/{folder}: {e}", flush=True)
        try:
            _update_sync_state(account_id, folder)
        except Exception as e:
            print(f"[SYNC] error syncstate {account_id}/{folder}: {e}", flush=True)
        print(f"[SYNC] {account_id}/{folder}: fin new={new} updated={updated} total={len(uids)}", flush=True)
        return {"new": new, "updated": updated, "total": len(uids)}
    finally:
        lock.release()


def sync_folder(account_id, folder, force=False, with_bodies=True):
    account_id = canonical_account_id(account_id)
    if _account_in_use(account_id):
        total = _folder_db_count(account_id, folder)
        return {"new": 0, "updated": 0, "total": total, "throttled": True}
    if _cooldown_active(account_id) and not force:
        total = _folder_db_count(account_id, folder)
        return {"new": 0, "updated": 0, "total": total, "throttled": True}

    acc = _get_account_row(account_id)
    if not acc:
        return {"error": "cuenta no existe"}

    _mark_connected(account_id)
    imap = IMAPClient(acc["IMAPHost"], acc["IMAPPort"], acc["Username"], decrypt_secret(acc["PasswordEnc"]))
    try:
        imap.connect()
        return _sync_folder_conn(account_id, folder, imap, force=force, with_bodies=with_bodies)
    finally:
        imap.close()


def _is_retention_folder(folder):
    low = (folder or "").lower()
    return any(p in low for p in RETENTION_FOLDER_PARTS)


def _run_retention(account_id, imap):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute("SELECT LastRun FROM HUBMAIL_Retention WHERE AccountID=%s", (account_id,))
        row = cur.fetchone()
        if row and row["LastRun"]:
            if (datetime.now() - row["LastRun"]).total_seconds() < 86400:
                return {"skipped": True}
        cur.execute("SELECT Folder FROM HUBMAIL_Folders WHERE AccountID=%s", (account_id,))
        target_folders = [r["Folder"] for r in cur.fetchall() if _is_retention_folder(r["Folder"])]
        if not target_folders:
            _upsert_retention(cur, account_id)
            conn.commit()
            return {"folders": 0, "deleted": 0}
        cutoff = datetime.now() - timedelta(days=RETENTION_MAX_DAYS)
        deleted_total = 0
        for folder in target_folders:
            cur.execute(
                "SELECT UID, DateSent FROM HUBMAIL_Messages WHERE AccountID=%s AND Folder=%s",
                (account_id, folder),
            )
            rows = cur.fetchall()
            if not rows:
                continue
            rows.sort(key=lambda r: (r["DateSent"] or datetime.min), reverse=True)
            keep = rows[:RETENTION_MAX_KEEP]
            keep_ids = set(int(r["UID"]) for r in keep if (r["DateSent"] or datetime.min) >= cutoff)
            to_delete = [r for r in rows if int(r["UID"]) not in keep_ids]
            if not to_delete:
                continue
            try:
                imap.delete_messages(folder, [str(int(r["UID"])) for r in to_delete])
            except Exception as e:
                print(f"[RETENTION] imap {account_id}/{folder}: {e}", flush=True)
            for r in to_delete:
                uid = int(r["UID"])
                cur.execute(
                    "DELETE FROM HUBMAIL_Attachments WHERE AccountID=%s AND Folder=%s AND UID=%s",
                    (account_id, folder, uid),
                )
                cur.execute(
                    "DELETE FROM HUBMAIL_Messages WHERE AccountID=%s AND Folder=%s AND UID=%s",
                    (account_id, folder, uid),
                )
            deleted_total += len(to_delete)
        _upsert_retention(cur, account_id)
        conn.commit()
        return {"folders": len(target_folders), "deleted": deleted_total}
    finally:
        conn.close()


def _upsert_retention(cur, account_id):
    cur.execute("SELECT 1 FROM HUBMAIL_Retention WHERE AccountID=%s", (account_id,))
    if cur.fetchone():
        cur.execute("UPDATE HUBMAIL_Retention SET LastRun=GETDATE() WHERE AccountID=%s", (account_id,))
    else:
        cur.execute("INSERT INTO HUBMAIL_Retention (AccountID, LastRun) VALUES (%s, GETDATE())", (account_id,))


def _save_folders(account_id, delimiter, folders):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM HUBMAIL_Folders WHERE AccountID=%s", (account_id,))
        if folders:
            cur.executemany(
                "INSERT INTO HUBMAIL_Folders (AccountID, Folder, Delimiter, Flags) VALUES (%s,%s,%s,%s)",
                [(account_id, f["name"], delimiter, ",".join(f.get("flags") or [])) for f in folders],
            )
        conn.commit()
    finally:
        conn.close()


def sync_account(account_id):
    account_id = canonical_account_id(account_id)
    acc = _get_account_row(account_id)
    if not acc:
        return None

    _mark_connected(account_id)
    _account_busy[account_id] = True
    imap = IMAPClient(acc["IMAPHost"], acc["IMAPPort"], acc["Username"], decrypt_secret(acc["PasswordEnc"]))
    try:
        imap.connect()
        lf = imap.list_folders()
        folders = lf["folders"]
        _save_folders(account_id, lf["delimiter"], folders)
    except IMAPError as e:
        print(f"[SYNC] account {account_id}: error conexión/listado: {e}", flush=True)
        _account_busy[account_id] = False
        return None
    result = {"new": 0, "updated": 0, "total": 0}
    try:
        for f in folders:
            try:
                r = _sync_folder_conn(account_id, f["name"], imap)
                result["new"] += r.get("new", 0)
                result["updated"] += r.get("updated", 0)
                result["total"] += r.get("total", 0)
            except Exception as e:
                print(f"[SYNC] error folder {account_id}/{f['name']}: {e}", flush=True)
                imap.close()
                continue
        try:
            retention = _run_retention(account_id, imap)
            if retention and not retention.get("skipped"):
                print(f"[RETENTION] {account_id}: {retention}", flush=True)
        except Exception as e:
            print(f"[RETENTION] error {account_id}: {e}", flush=True)
    finally:
        imap.close()
        _account_busy[account_id] = False
    return result


def sync_all_accounts():
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute("SELECT AccountID FROM HUBMAIL_Accounts WHERE CanonicalAccountID IS NULL")
        ids = [r["AccountID"] for r in cur.fetchall()]
    finally:
        conn.close()
    for aid in ids:
        try:
            sync_account(aid)
        except Exception:
            continue