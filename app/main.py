import html
import json
import re
import threading
import time
import urllib.parse
import urllib.request
from typing import Optional

import jwt
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.staticfiles import StaticFiles as StarletteStaticFiles
from pydantic import BaseModel, Field

from .auth import authenticate, create_token, get_current_user
from .config import settings
from .crypto import encrypt_secret, decrypt_secret
from .db import get_conn
from .filters import get_admin_user_id, is_admin
from .imap_client import IMAPClient, IMAPError
from .smtp_client import send_mail, SMTPError
from .signature import build_default_signature
from . import sync as syncmod
from . import filters as filtmod

app = FastAPI(title="HUBMail", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_ACCOUNTS = 5

IMG_CACHE = {}
IMG_CACHE_MAX_ENTRIES = 300
IMG_MAX_BYTES = 8 * 1024 * 1024
_IMG_BLOCKED_HOSTS = ("localhost", "127.0.0.1", "::1", "0.0.0.0", "169.254.169.254")


def _user_from_token(t: str = ""):
    if not t:
        raise HTTPException(401, "No autorizado")
    try:
        payload = jwt.decode(t, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Sesión inválida o expirada")
    return {"id": int(payload["sub"]), "email": payload["email"], "name": payload["name"]}


def _fetch_image(url: str):
    req = urllib.request.Request(
        url, headers={"User-Agent": "HUBMail/1.0", "Accept": "image/*,image/webp,*/*"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        ctype = (r.headers.get("Content-Type", "") or "image/jpeg").split(";")[0]
        data = r.read(IMG_MAX_BYTES + 1)
        if len(data) > IMG_MAX_BYTES:
            raise HTTPException(400, "Imagen demasiado grande")
    return ctype, data

SYNC_PERIOD = 300  # segundos: sincronización en el servidor cada 5 min
_sync_thread = None
_sync_stop = False


def _background_sync_loop():
    time.sleep(20)  # primer sync poco después de arrancar
    while not _sync_stop:
        try:
            syncmod.sync_all_accounts()
        except Exception:
            pass
        for _ in range(SYNC_PERIOD):
            if _sync_stop:
                return
            time.sleep(1)


def _backfill_user_settings():
    try:
        conn = get_conn()
        try:
            cur = conn.cursor(as_dict=True)
            cur.execute("SELECT DISTINCT UserID FROM HUBMAIL_Accounts")
            users = [r["UserID"] for r in cur.fetchall()]
            for uid in users:
                cur.execute(
                    "SELECT COUNT(*) AS N FROM HUBMAIL_UserSettings WHERE UserID=%s",
                    (uid,),
                )
                if cur.fetchone()["N"]:
                    continue
                cur.execute(
                    "SELECT TOP 1 DisplayName, EmailAddress, Phone "
                    "FROM HUBMAIL_Accounts WHERE UserID=%s AND CanonicalAccountID IS NULL "
                    "ORDER BY IsDefault DESC, AccountID",
                    (uid,),
                )
                a = cur.fetchone()
                name = (a["DisplayName"] if a else "") or ""
                phone = (a["Phone"] if a else "") or ""
                email = (a["EmailAddress"] if a else "") or ""
                sig = build_default_signature(name, email, phone)
                cur.execute(
                    "INSERT INTO HUBMAIL_UserSettings "
                    "(UserID, DisplayName, Phone, SignatureHtml) VALUES (%s,%s,%s,%s)",
                    (uid, name, phone, sig),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


@app.on_event("startup")
def _start_sync_thread():
    global _sync_thread
    _backfill_user_settings()
    if _sync_thread is None:
        _sync_thread = threading.Thread(target=_background_sync_loop, daemon=True)
        _sync_thread.start()


@app.on_event("shutdown")
def _stop_sync_thread():
    global _sync_stop
    _sync_stop = True


# ---------------------------------------------------------------- modelos
class LoginPayload(BaseModel):
    email: str
    password: str


class AccountPayload(BaseModel):
    email: str
    display_name: str = ""
    imap_host: str = ""
    imap_port: int = 0
    smtp_host: str = ""
    smtp_port: int = 0
    username: str = ""
    password: str = ""
    is_default: bool = False


class SettingsPayload(BaseModel):
    display_name: str = ""
    phone: str = ""
    signature_html: str = ""


class Attachment(BaseModel):
    name: str
    content_type: str = "application/octet-stream"
    data: str
    size: int = 0
    cid: str = ""


class SendPayload(BaseModel):
    to: list[str]
    cc: list[str] = []
    bcc: list[str] = []
    subject: str = ""
    body_html: str = ""
    reply_to: Optional[str] = None
    read_receipt: bool = False
    attachments: list[Attachment] = Field(default_factory=list)


class BulkDeletePayload(BaseModel):
    folder: str = "INBOX"
    ids: list[str]


class ContactPayload(BaseModel):
    name: str
    email: str
    phone: str = ""
    notes: str = ""


# ---------------------------------------------------------------- helpers
def _account_to_dict(acc):
    return {
        "id": acc["AccountID"],
        "email": acc["EmailAddress"],
        "display_name": acc["DisplayName"],
        "imap_host": acc["IMAPHost"],
        "imap_port": acc["IMAPPort"],
        "smtp_host": acc["SMTPHost"],
        "smtp_port": acc["SMTPPort"],
        "username": acc["Username"],
        "is_default": bool(acc["IsDefault"]),
        "shared": bool(acc.get("CanonicalAccountID")),
        "canonical_id": acc.get("CanonicalAccountID"),
    }


def _get_account(user, account_id):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT * FROM HUBMAIL_Accounts WHERE AccountID=%s AND UserID=%s",
            (account_id, user["id"]),
        )
        acc = cur.fetchone()
        if not acc:
            raise HTTPException(404, "Cuenta no encontrada")
        return acc
    finally:
        conn.close()


def _canonical_row(acc):
    if acc and acc.get("CanonicalAccountID"):
        conn = get_conn()
        try:
            cur = conn.cursor(as_dict=True)
            cur.execute(
                "SELECT * FROM HUBMAIL_Accounts WHERE AccountID=%s",
                (acc["CanonicalAccountID"],),
            )
            c = cur.fetchone()
            if c:
                return c
        finally:
            conn.close()
    return acc


def _imap_for(acc):
    return IMAPClient(
        acc["IMAPHost"],
        acc["IMAPPort"],
        acc["Username"],
        decrypt_secret(acc["PasswordEnc"]),
    )


def _imap_query(q: str) -> str:
    q = q.replace("\\", "\\\\").replace('"', '\\"')
    return f'TEXT "{q}"'


# ---------------------------------------------------------------- auth
@app.post("/api/auth/login")
def login(payload: LoginPayload):
    row = authenticate(payload.email, payload.password)
    if not row:
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    token = create_token(row["Id"], row["Email"], row["Nombre"])
    return {
        "token": token,
        "user": {"id": row["Id"], "email": row["Email"], "name": row["Nombre"]},
    }


@app.get("/api/auth/me")
def me(user=Depends(get_current_user)):
    return {**user, "is_admin": is_admin(user)}


# ---------------------------------------------------------------- cuentas
@app.get("/api/accounts")
def list_accounts(user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT * FROM HUBMAIL_Accounts WHERE UserID=%s ORDER BY IsDefault DESC, EmailAddress",
            (user["id"],),
        )
        return [_account_to_dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


@app.post("/api/accounts")
def create_account(payload: AccountPayload, user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute("SELECT COUNT(*) AS N FROM HUBMAIL_Accounts WHERE UserID=%s", (user["id"],))
        if cur.fetchone()["N"] >= MAX_ACCOUNTS:
            raise HTTPException(400, f"Máximo {MAX_ACCOUNTS} cuentas por usuario")

        imap_host = payload.imap_host or settings.default_imap_host
        imap_port = payload.imap_port or settings.default_imap_port
        smtp_host = payload.smtp_host or settings.default_smtp_host
        smtp_port = payload.smtp_port or settings.default_smtp_port
        username = payload.username or payload.email

        if payload.is_default:
            cur.execute(
                "UPDATE HUBMAIL_Accounts SET IsDefault=0 WHERE UserID=%s", (user["id"],)
            )
        cur.execute(
            """
            INSERT INTO HUBMAIL_Accounts
                (UserID, EmailAddress, DisplayName, IMAPHost, IMAPPort,
                 SMTPHost, SMTPPort, Username, PasswordEnc, SignatureHtml, Phone, IsDefault)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,NULL,%s)
            """,
            (
                user["id"], payload.email, payload.display_name,
                imap_host, imap_port, smtp_host, smtp_port,
                username, encrypt_secret(payload.password),
                1 if payload.is_default else 0,
            ),
        )
        conn.commit()
        cur.execute("SELECT @@IDENTITY AS Id")
        account_id = cur.fetchone()["Id"]

        cur.execute(
            """
            SELECT TOP 1 ISNULL(CanonicalAccountID, AccountID) AS Cid
            FROM HUBMAIL_Accounts
            WHERE LOWER(EmailAddress)=LOWER(%s) AND LOWER(IMAPHost)=LOWER(%s)
              AND LOWER(Username)=LOWER(%s) AND AccountID <> %s
            ORDER BY AccountID
            """,
            (payload.email, imap_host, username, account_id),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE HUBMAIL_Accounts SET CanonicalAccountID=%s WHERE AccountID=%s",
                (row["Cid"], account_id),
            )
            conn.commit()

        admin_uid = get_admin_user_id()
        if admin_uid and admin_uid != user["id"]:
            eff = row["Cid"] if row else account_id
            cur.execute(
                "SELECT COUNT(*) AS N FROM HUBMAIL_Accounts "
                "WHERE UserID=%s AND EmailAddress=%s AND IMAPHost=%s AND Username=%s",
                (admin_uid, payload.email, imap_host, username),
            )
            if cur.fetchone()["N"] == 0:
                cur.execute(
                    """INSERT INTO HUBMAIL_Accounts
                       (UserID, EmailAddress, DisplayName, IMAPHost, IMAPPort, SMTPHost, SMTPPort, Username, PasswordEnc, SignatureHtml, Phone, IsDefault, CanonicalAccountID)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,NULL,0,%s)""",
                    (admin_uid, payload.email, payload.display_name, imap_host, imap_port,
                     smtp_host, smtp_port, username, encrypt_secret(payload.password), eff),
                )
                conn.commit()
    finally:
        conn.close()

    acc = _get_account(user, account_id)
    return _account_to_dict(acc)


# ---------------------------------------------------------------- ajustes del usuario (firma personal)
@app.get("/api/settings")
def get_settings(user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT DisplayName, Phone, SignatureHtml FROM HUBMAIL_UserSettings WHERE UserID=%s",
            (user["id"],),
        )
        r = cur.fetchone()
        if not r:
            return {"display_name": "", "phone": "", "signature_html": ""}
        return {
            "display_name": r["DisplayName"] or "",
            "phone": r["Phone"] or "",
            "signature_html": r["SignatureHtml"] or "",
        }
    finally:
        conn.close()


@app.put("/api/settings")
def update_settings(payload: SettingsPayload, user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT COUNT(*) AS N FROM HUBMAIL_UserSettings WHERE UserID=%s",
            (user["id"],),
        )
        if cur.fetchone()["N"]:
            cur.execute(
                "UPDATE HUBMAIL_UserSettings SET DisplayName=%s, Phone=%s, SignatureHtml=%s WHERE UserID=%s",
                (payload.display_name, payload.phone, payload.signature_html, user["id"]),
            )
        else:
            cur.execute(
                "INSERT INTO HUBMAIL_UserSettings (UserID, DisplayName, Phone, SignatureHtml) VALUES (%s,%s,%s,%s)",
                (user["id"], payload.display_name, payload.phone, payload.signature_html),
            )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@app.put("/api/accounts/{account_id}")
def update_account(account_id: int, payload: AccountPayload, user=Depends(get_current_user)):
    acc = _get_account(user, account_id)
    conn = get_conn()
    try:
        cur = conn.cursor()
        imap_host = payload.imap_host or acc["IMAPHost"]
        imap_port = payload.imap_port or acc["IMAPPort"]
        smtp_host = payload.smtp_host or acc["SMTPHost"]
        smtp_port = payload.smtp_port or acc["SMTPPort"]
        username = payload.username or acc["Username"]

        if payload.is_default:
            conn.cursor(as_dict=True).execute(
                "UPDATE HUBMAIL_Accounts SET IsDefault=0 WHERE UserID=%s", (user["id"],)
            )
        password_enc = acc["PasswordEnc"]
        if payload.password:
            password_enc = encrypt_secret(payload.password)

        cur.execute(
            """
            UPDATE HUBMAIL_Accounts SET
                EmailAddress=%s, DisplayName=%s, IMAPHost=%s, IMAPPort=%s,
                SMTPHost=%s, SMTPPort=%s, Username=%s, PasswordEnc=%s,
                IsDefault=%s
            WHERE AccountID=%s AND UserID=%s
            """,
            (
                payload.email, payload.display_name,
                imap_host, imap_port, smtp_host, smtp_port, username,
                password_enc, 1 if payload.is_default else 0, account_id, user["id"],
            ),
        )
        conn.commit()
    finally:
        conn.close()

    updated = _get_account(user, account_id)
    return _account_to_dict(updated)


@app.delete("/api/accounts/{account_id}")
def delete_account(account_id: int, user=Depends(get_current_user)):
    _get_account(user, account_id)
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT AccountID FROM HUBMAIL_Accounts WHERE CanonicalAccountID=%s ORDER BY AccountID",
            (account_id,),
        )
        linked = [r["AccountID"] for r in cur.fetchall()]
        if linked:
            promote = linked[0]
            cur.execute("DELETE FROM HUBMAIL_Messages WHERE AccountID=%s", (promote,))
            cur.execute("DELETE FROM HUBMAIL_SyncState WHERE AccountID=%s", (promote,))
            cur.execute("DELETE FROM HUBMAIL_Unread WHERE AccountID=%s", (promote,))
            for table in ("HUBMAIL_Messages", "HUBMAIL_SyncState", "HUBMAIL_Unread"):
                cur.execute(
                    f"UPDATE {table} SET AccountID=%s WHERE AccountID=%s",
                    (promote, account_id),
                )
            cur.execute(
                "UPDATE HUBMAIL_Accounts SET CanonicalAccountID=%s WHERE CanonicalAccountID=%s AND AccountID<>%s",
                (promote, account_id, promote),
            )
            cur.execute(
                "UPDATE HUBMAIL_Accounts SET CanonicalAccountID=NULL WHERE AccountID=%s",
                (promote,),
            )
        cur.execute(
            "DELETE FROM HUBMAIL_Accounts WHERE AccountID=%s AND UserID=%s",
            (account_id, user["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@app.post("/api/accounts/{account_id}/test")
def test_account(account_id: int, user=Depends(get_current_user)):
    acc = _canonical_row(_get_account(user, account_id))
    try:
        with _imap_for(acc) as imap:
            imap.list_folders()
    except IMAPError as e:
        raise HTTPException(400, f"IMAP: {e}")
    return {"ok": True, "message": "Conexión IMAP correcta"}


# ---------------------------------------------------------------- correo
@app.get("/api/accounts/{account_id}/folders")
def list_folders(account_id: int, user=Depends(get_current_user)):
    acc = _canonical_row(_get_account(user, account_id))
    try:
        with _imap_for(acc) as imap:
            return imap.list_folders()
    except IMAPError as e:
        raise HTTPException(400, str(e))


def _msg_row_to_dict(r):
    return {
        "id": str(r["UID"]),
        "subject": r["Subject"] or "(sin asunto)",
        "from": [{"name": r["FromName"] or "", "email": r["FromEmail"] or ""}],
        "to": syncmod._addr_from_json(r["ToText"]),
        "date": r["DateSent"].strftime("%Y-%m-%d %H:%M") if r["DateSent"] else "",
        "unread": not r["Seen"],
        "flagged": bool(r["Flagged"]),
        "has_attachments": bool(r["HasAttachments"]),
        "spam": bool(r.get("Spam")),
    }


def _msg_detail_row(r):
    return {
        "id": str(r["UID"]),
        "subject": r["Subject"] or "(sin asunto)",
        "from": [{"name": r["FromName"] or "", "email": r["FromEmail"] or ""}],
        "to": syncmod._addr_from_json(r["ToText"]),
        "cc": syncmod._addr_from_json(r["CcText"]),
        "date": r["DateSent"].strftime("%Y-%m-%d %H:%M") if r["DateSent"] else "",
        "unread": not r["Seen"],
        "flagged": bool(r["Flagged"]),
        "spam": bool(r.get("Spam")),
        "body_html": r["BodyHtml"] or "",
        "body_text": r["BodyText"] or "",
        "attachments": [],
        "message_id": r["MessageIdHeader"],
        "in_reply_to": r["InReplyTo"],
    }


@app.get("/api/accounts/{account_id}/messages")
def list_messages(
    account_id: int,
    user=Depends(get_current_user),
    folder: str = Query(default="INBOX"),
    page: int = Query(default=1, ge=1),
    q: str = Query(default=""),
    unread_only: bool = Query(default=False),
):
    acc = _canonical_row(_get_account(user, account_id))
    account_id = acc["AccountID"]
    sync_error = None
    try:
        syncmod.sync_folder(account_id, folder, with_bodies=False)
    except Exception as e:
        sync_error = e

    last_sync = None
    conn0 = get_conn()
    try:
        cur = conn0.cursor(as_dict=True)
        cur.execute(
            "SELECT LastSync FROM HUBMAIL_SyncState WHERE AccountID=%s AND Folder=%s",
            (account_id, folder),
        )
        row = cur.fetchone()
        if row and row["LastSync"]:
            last_sync = row["LastSync"].strftime("%d/%m/%Y %H:%M")
    finally:
        conn0.close()

    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        where = "AccountID=%s AND Folder=%s"
        params = [account_id, folder]
        if q:
            like = f"%{q}%"
            where += " AND (Subject LIKE %s OR FromName LIKE %s OR FromEmail LIKE %s)"
            params += [like, like, like]
        if unread_only:
            where += " AND Seen=0"
        cur.execute(f"SELECT COUNT(*) AS N FROM HUBMAIL_Messages WHERE {where}", params)
        total = cur.fetchone()["N"]
        cur.execute(
            f"""SELECT UID, FromName, FromEmail, ToText, Subject, DateSent, Seen, Flagged, HasAttachments
                FROM HUBMAIL_Messages WHERE {where}
                ORDER BY DateSent DESC
                OFFSET %s ROWS FETCH NEXT %s ROWS ONLY""",
            params + [(page - 1) * settings.page_size, settings.page_size],
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    messages = [_msg_row_to_dict(r) for r in rows]
    if not messages and sync_error:
        try:
            with _imap_for(acc) as imap:
                criteria = _imap_query(q) if q else "ALL"
                return imap.list_messages(folder, criteria, page, settings.page_size, unread_only)
        except IMAPError:
            raise HTTPException(400, f"No se pudo cargar la carpeta: {sync_error}")
    return {
        "total": total, "page": page, "page_size": settings.page_size,
        "messages": messages, "last_sync": last_sync,
    }


@app.get("/api/accounts/{account_id}/messages/{msgid}")
def get_message(
    account_id: int,
    msgid: str,
    user=Depends(get_current_user),
    folder: str = Query(default="INBOX"),
):
    acc = _canonical_row(_get_account(user, account_id))
    account_id = acc["AccountID"]
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT * FROM HUBMAIL_Messages WHERE AccountID=%s AND Folder=%s AND UID=%s",
            (account_id, folder, int(msgid)),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row and not row["HasAttachments"] and row["BodyHtml"]:
        return _msg_detail_row(row)
    with _imap_for(acc) as imap:
        return imap.get_message(folder, msgid)


def _db_update_flags(account_id, folder, uid, seen=None, flagged=None):
    conn = get_conn()
    try:
        cur = conn.cursor()
        if seen is not None:
            cur.execute(
                "UPDATE HUBMAIL_Messages SET Seen=%s WHERE AccountID=%s AND Folder=%s AND UID=%s",
                (1 if seen else 0, account_id, folder, uid),
            )
        if flagged is not None:
            cur.execute(
                "UPDATE HUBMAIL_Messages SET Flagged=%s WHERE AccountID=%s AND Folder=%s AND UID=%s",
                (1 if flagged else 0, account_id, folder, uid),
            )
        conn.commit()
    finally:
        conn.close()


@app.patch("/api/accounts/{account_id}/messages/{msgid}")
def message_action(
    account_id: int,
    msgid: str,
    user=Depends(get_current_user),
    folder: str = Query(default="INBOX"),
    action: str = Query(default="read"),
    dest: str = Query(default=""),
):
    acc = _canonical_row(_get_account(user, account_id))
    account_id = acc["AccountID"]
    uid = int(msgid)
    try:
        with _imap_for(acc) as imap:
            if action in ("read", "unread"):
                imap.set_flag(folder, msgid, "\\Seen", action == "read")
                _db_update_flags(account_id, folder, uid, seen=action == "read")
            elif action in ("flag", "unflag"):
                imap.set_flag(folder, msgid, "\\Flagged", action == "flag")
                _db_update_flags(account_id, folder, uid, flagged=action == "flag")
            elif action == "notspam":
                filtmod._db_set_spam(account_id, uid, False)
            elif action == "delete":
                imap.delete_message(folder, msgid)
                _db_delete_messages(account_id, folder, [msgid])
            elif action == "move":
                if not dest:
                    raise HTTPException(400, "Falta carpeta destino")
                imap.move_message(folder, msgid, dest)
                _db_move_message(account_id, folder, uid, dest)
            else:
                raise HTTPException(400, "Acción no válida")
    except IMAPError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


def _db_delete_messages(account_id, folder, uids):
    if not uids:
        return
    conn = get_conn()
    try:
        cur = conn.cursor()
        for uid in uids:
            cur.execute(
                "DELETE FROM HUBMAIL_Messages WHERE AccountID=%s AND Folder=%s AND UID=%s",
                (account_id, folder, int(uid)),
            )
        conn.commit()
    finally:
        conn.close()


def _db_move_message(account_id, folder, uid, dest):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE HUBMAIL_Messages SET Folder=%s WHERE AccountID=%s AND Folder=%s AND UID=%s",
            (dest, account_id, folder, uid),
        )
        conn.commit()
    finally:
        conn.close()


@app.get("/api/accounts/{account_id}/unread")
def unread_count(account_id: int, user=Depends(get_current_user)):
    acc = _canonical_row(_get_account(user, account_id))
    try:
        with _imap_for(acc) as imap:
            return {"unread": imap.unread_count("INBOX")}
    except IMAPError:
        return {"unread": None}


@app.post("/api/accounts/{account_id}/messages/bulk-delete")
def bulk_delete(account_id: int, payload: BulkDeletePayload, user=Depends(get_current_user)):
    acc = _canonical_row(_get_account(user, account_id))
    account_id = acc["AccountID"]
    if not payload.ids:
        raise HTTPException(400, "No hay mensajes seleccionados")
    try:
        with _imap_for(acc) as imap:
            imap.delete_messages(payload.folder, payload.ids)
    except IMAPError as e:
        raise HTTPException(400, str(e))
    _db_delete_messages(account_id, payload.folder, payload.ids)
    return {"ok": True, "deleted": len(payload.ids)}


@app.post("/api/accounts/{account_id}/send")
def send_message(account_id: int, payload: SendPayload, user=Depends(get_current_user)):
    acc = _canonical_row(_get_account(user, account_id))
    try:
        send_mail(
            acc,
            payload.to,
            payload.cc,
            payload.bcc,
            payload.subject,
            payload.body_html,
            [a.model_dump() for a in payload.attachments],
            payload.reply_to,
            payload.read_receipt,
        )
    except SMTPError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.get("/api/wallpaper")
def wallpaper():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT TOP 1 Url FROM HUB_BingWallpapers WHERE Url IS NOT NULL ORDER BY NEWID()"
        )
        row = cur.fetchone()
        return {"url": row[0] if row else ""}
    finally:
        conn.close()


@app.get("/api/img")
def img_proxy(url: str = Query(...), t: str = Query(...)):
    _user_from_token(t)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(400, "URL no permitida")
    host = parsed.hostname.lower().rstrip(".")
    if host in _IMG_BLOCKED_HOSTS or host.startswith("127.") or host.startswith("169.254."):
        raise HTTPException(400, "URL no permitida")
    cached = IMG_CACHE.get(url)
    if cached and cached[0] > time.time() - 3600:
        ctype, data = cached[1], cached[2]
    else:
        try:
            ctype, data = _fetch_image(url)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, "No se pudo cargar la imagen")
        IMG_CACHE[url] = (time.time(), ctype, data)
        if len(IMG_CACHE) > IMG_CACHE_MAX_ENTRIES:
            oldest = min(IMG_CACHE, key=lambda k: IMG_CACHE[k][0])
            del IMG_CACHE[oldest]
    return Response(
        content=data,
        media_type=ctype,
        headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Disposition": "inline",
        },
    )


# ---------------------------------------------------------------- notificaciones
@app.get("/api/notifications")
def notifications(user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            """SELECT a.*, ISNULL(a.CanonicalAccountID, a.AccountID) AS EffAccountID,
                      (SELECT COUNT(*) FROM HUBMAIL_Messages m
                       WHERE m.AccountID=ISNULL(a.CanonicalAccountID, a.AccountID)
                         AND m.Folder='INBOX' AND m.Seen=0) AS Unread,
                      (SELECT COUNT(*) FROM HUBMAIL_Messages m
                       WHERE m.AccountID=ISNULL(a.CanonicalAccountID, a.AccountID)) AS Synced
               FROM HUBMAIL_Accounts a WHERE a.UserID=%s""",
            (user["id"],),
        )
        accounts = cur.fetchall()
    finally:
        conn.close()

    results = []
    for acc in accounts:
        n = acc["Unread"]
        if not acc["Synced"]:
            try:
                with _imap_for(_canonical_row(acc)) as imap:
                    n = imap.unread_count("INBOX")
            except Exception:
                n = None
        results.append({"account_id": acc["AccountID"], "email": acc["EmailAddress"], "unread": n})
    return results


def _preview_lines(body_text, body_html, max_lines=5, max_chars=320):
    text = body_text or ""
    if not text.strip() and body_html:
        text = re.sub(r"<[^>]+>", " ", body_html)
        text = html.unescape(text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return ""
    out = "\n".join(lines[:max_lines])
    if len(out) > max_chars:
        out = out[:max_chars].rsplit(" ", 1)[0] + "…"
    return out


@app.get("/api/notifications/new")
def new_messages(user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT AccountID, CanonicalAccountID FROM HUBMAIL_Accounts WHERE UserID=%s",
            (user["id"],),
        )
        accs = cur.fetchall()
    finally:
        conn.close()
    for a in accs:
        try:
            syncmod.sync_folder(a["CanonicalAccountID"] or a["AccountID"], "INBOX", with_bodies=True)
        except Exception:
            pass

    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            """SELECT TOP 8 ua.EmailAddress, m.AccountID, m.UID, m.FromName, m.FromEmail,
                      m.Subject, m.DateSent, m.BodyText, m.BodyHtml
               FROM HUBMAIL_Accounts ua
               JOIN HUBMAIL_Accounts c ON c.AccountID = ISNULL(ua.CanonicalAccountID, ua.AccountID)
               JOIN HUBMAIL_Messages m ON m.AccountID = c.AccountID
                  AND m.Folder = 'INBOX' AND m.Seen = 0
               WHERE ua.UserID = %s
               ORDER BY m.DateSent DESC""",
            (user["id"],),
        )
        items = [
            {
                "account_id": r["AccountID"],
                "email": r["EmailAddress"],
                "uid": str(r["UID"]),
                "from_name": r["FromName"] or "",
                "from_email": r["FromEmail"] or "",
                "subject": r["Subject"] or "(sin asunto)",
                "date": r["DateSent"].strftime("%d/%m/%Y %H:%M") if r["DateSent"] else "",
                "preview": _preview_lines(r["BodyText"], r["BodyHtml"]),
            }
            for r in cur.fetchall()
        ]
    finally:
        conn.close()
    return {"items": items}


# ---------------------------------------------------------------- filtros
class FilterPayload(BaseModel):
    scope: str = "ACCOUNT"
    account_id: Optional[int] = None
    name: str = ""
    conditions: list = Field(default_factory=list)
    action: str = "spam"
    action_folder: str = ""
    enabled: bool = True
    order_no: int = 0


def _filter_to_dict(r):
    try:
        conds = json.loads(r["Conditions"] or "[]")
    except Exception:
        conds = []
    return {
        "id": r["FilterID"],
        "scope": r["Scope"],
        "account_id": r["AccountID"],
        "name": r["Name"],
        "conditions": conds,
        "action": r["Action"],
        "action_folder": r["ActionFolder"] or "",
        "enabled": bool(r["Enabled"]),
        "order_no": r["OrderNo"],
    }


@app.get("/api/filters")
def list_filters(user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT * FROM HUBMAIL_Filters WHERE UserID=%s ORDER BY OrderNo, FilterID",
            (user["id"],),
        )
        return [_filter_to_dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


@app.post("/api/filters")
def create_filter(payload: FilterPayload, user=Depends(get_current_user)):
    scope = payload.scope.upper()
    if scope not in ("GLOBAL", "ACCOUNT"):
        raise HTTPException(400, "Alcance no válido")
    if scope == "GLOBAL" and not is_admin(user):
        raise HTTPException(403, "Solo el administrador puede crear filtros globales")
    if scope == "ACCOUNT":
        if not payload.account_id:
            raise HTTPException(400, "Indica la cuenta a la que aplica")
        _get_account(user, payload.account_id)
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO HUBMAIL_Filters
               (UserID, Scope, AccountID, Name, Conditions, Action, ActionFolder, Enabled, OrderNo)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (user["id"], scope,
             payload.account_id if scope == "ACCOUNT" else None,
             payload.name, json.dumps(payload.conditions, ensure_ascii=False),
             payload.action, payload.action_folder, 1 if payload.enabled else 0,
             payload.order_no),
        )
        conn.commit()
        cur.execute("SELECT @@IDENTITY AS Id")
        fid = cur.fetchone()[0]
    finally:
        conn.close()
    return {"id": fid}


@app.put("/api/filters/{filter_id}")
def update_filter(filter_id: int, payload: FilterPayload, user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT * FROM HUBMAIL_Filters WHERE FilterID=%s AND UserID=%s",
            (filter_id, user["id"]),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Filtro no encontrado")
        scope = payload.scope.upper()
        if scope == "GLOBAL" and not is_admin(user):
            raise HTTPException(403, "Solo el administrador puede usar filtros globales")
        if scope == "ACCOUNT":
            if not payload.account_id:
                raise HTTPException(400, "Indica la cuenta a la que aplica")
            _get_account(user, payload.account_id)
        cur.execute(
            """UPDATE HUBMAIL_Filters SET Scope=%s, AccountID=%s, Name=%s, Conditions=%s,
               Action=%s, ActionFolder=%s, Enabled=%s, OrderNo=%s
               WHERE FilterID=%s AND UserID=%s""",
            (scope, payload.account_id if scope == "ACCOUNT" else None,
             payload.name, json.dumps(payload.conditions, ensure_ascii=False),
             payload.action, payload.action_folder, 1 if payload.enabled else 0,
             payload.order_no, filter_id, user["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@app.delete("/api/filters/{filter_id}")
def delete_filter(filter_id: int, user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM HUBMAIL_Filters WHERE FilterID=%s AND UserID=%s",
            (filter_id, user["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


# ---------------------------------------------------------------- listas antispam (admin)
class SpamListPayload(BaseModel):
    name: str
    zone: str
    list_type: str = "DNSBL"
    enabled: bool = True
    priority: int = 0


def _spam_list_to_dict(r):
    return {
        "id": r["ListId"],
        "name": r["Name"],
        "zone": r["Zone"],
        "list_type": r["Type"],
        "enabled": bool(r["Enabled"]),
        "priority": r["Priority"],
    }


@app.get("/api/spam-lists")
def list_spam_lists(user=Depends(get_current_user)):
    if not is_admin(user):
        raise HTTPException(403, "Solo el administrador")
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute("SELECT * FROM HUBMAIL_SpamLists ORDER BY Priority, ListId")
        return [_spam_list_to_dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


@app.post("/api/spam-lists")
def create_spam_list(payload: SpamListPayload, user=Depends(get_current_user)):
    if not is_admin(user):
        raise HTTPException(403, "Solo el administrador")
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO HUBMAIL_SpamLists (Name, Type, Zone, Enabled, Priority) VALUES (%s,%s,%s,%s,%s)",
            (payload.name, payload.list_type, payload.zone, 1 if payload.enabled else 0, payload.priority),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@app.put("/api/spam-lists/{list_id}")
def update_spam_list(list_id: int, payload: SpamListPayload, user=Depends(get_current_user)):
    if not is_admin(user):
        raise HTTPException(403, "Solo el administrador")
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE HUBMAIL_SpamLists SET Name=%s, Type=%s, Zone=%s, Enabled=%s, Priority=%s WHERE ListId=%s",
            (payload.name, payload.list_type, payload.zone, 1 if payload.enabled else 0, payload.priority, list_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@app.delete("/api/spam-lists/{list_id}")
def delete_spam_list(list_id: int, user=Depends(get_current_user)):
    if not is_admin(user):
        raise HTTPException(403, "Solo el administrador")
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM HUBMAIL_SpamLists WHERE ListId=%s", (list_id,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


# ---------------------------------------------------------------- contactos
@app.get("/api/contacts")
def list_contacts(user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute("SELECT Nombre, Email FROM HUB_Users WHERE Activo=1 ORDER BY Nombre")
        users = [{"name": r["Nombre"], "email": r["Email"]} for r in cur.fetchall()]
        cur.execute(
            "SELECT ContactID, Name, Email, Phone, Notes FROM HUBMAIL_Contacts ORDER BY Name"
        )
        contacts = []
        for r in cur.fetchall():
            contacts.append({
                "id": r["ContactID"],
                "name": r["Name"],
                "email": r["Email"],
                "phone": r["Phone"] or "",
                "notes": r["Notes"] or "",
            })
        return {"users": users, "contacts": contacts}
    finally:
        conn.close()


@app.post("/api/contacts")
def create_contact(payload: ContactPayload, user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT ContactID FROM HUBMAIL_Contacts WHERE Email=%s", (payload.email,)
        )
        if cur.fetchone():
            raise HTTPException(400, "Ya existe un contacto con ese email")
        cur.execute(
            "INSERT INTO HUBMAIL_Contacts (Name, Email, Phone, Notes, CreatedBy) VALUES (%s,%s,%s,%s,%s)",
            (payload.name, payload.email, payload.phone, payload.notes, user["id"]),
        )
        conn.commit()
        cur.execute("SELECT @@IDENTITY AS Id")
        cid = cur.fetchone()["Id"]
    finally:
        conn.close()
    return {"id": cid}


@app.put("/api/contacts/{contact_id}")
def update_contact(contact_id: int, payload: ContactPayload, user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE HUBMAIL_Contacts SET Name=%s, Email=%s, Phone=%s, Notes=%s WHERE ContactID=%s",
            (payload.name, payload.email, payload.phone, payload.notes, contact_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@app.delete("/api/contacts/{contact_id}")
def delete_contact(contact_id: int, user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM HUBMAIL_Contacts WHERE ContactID=%s", (contact_id,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"status": "ok"}


class NoCacheStaticFiles(StarletteStaticFiles):
    def file_response(self, full_path, stat_result, scope, status_code=200):
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Cache-Control"] = "no-store"
        return response


app.mount("/", NoCacheStaticFiles(directory="static", html=True), name="static")