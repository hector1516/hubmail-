import html
import json
import random
import re
import threading
import time
import urllib.parse
import urllib.request
import base64
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
from .db import get_conn, get_users_conn
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

ACC_COLORS = [
    "#2a6fd6", "#8e44ad", "#d63031", "#0984e3", "#00b894", "#e17055",
    "#e84393", "#6c5ce7", "#00cec9", "#e67e22", "#d35400", "#16a085",
]


def _pick_color(color: str) -> str:
    color = (color or "").strip()
    return color if color else random.choice(ACC_COLORS)

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
                    "SELECT DisplayName, EmailAddress, Phone "
                    "FROM HUBMAIL_Accounts WHERE UserID=%s AND CanonicalAccountID IS NULL "
                    "ORDER BY IsDefault DESC, AccountID LIMIT 1",
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
    color: str = ""


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


class MoveMessagesPayload(BaseModel):
    source_account_id: int
    dest_account_id: int
    folder: str
    dest_folder: str
    uids: list[str]


class BulkSeenPayload(BaseModel):
    folder: str = "INBOX"
    ids: list[str]
    seen: bool = True


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
        "color": acc.get("Color") or "",
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
    last_login = _record_login(row["Id"])
    _log_activity(
        {"id": row["Id"], "name": row["Nombre"], "email": row["Email"]},
        None, "login", f"Inició sesión",
    )
    return {
        "token": token,
        "user": {"id": row["Id"], "email": row["Email"], "name": row["Nombre"]},
        "last_login": last_login,
    }


def _record_login(user_id: int):
    """Guarda la fecha del inicio de sesión y devuelve la anterior (si existe)."""
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute("SELECT LastLogin FROM HUBMAIL_UserMeta WHERE UserID=%s", (user_id,))
        prev = cur.fetchone()
        last_login = prev["LastLogin"] if prev else None
        if prev:
            cur.execute(
                "UPDATE HUBMAIL_UserMeta SET LastLogin=NOW() WHERE UserID=%s",
                (user_id,),
            )
        else:
            cur.execute(
                "INSERT INTO HUBMAIL_UserMeta (UserID, LastLogin) VALUES (%s, NOW())",
                (user_id,),
            )
        conn.commit()
    finally:
        conn.close()
    return last_login


def _log_activity(user, account_id, action, details):
    if not user:
        return
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO HUBMAIL_ActivityLog (AccountID, UserID, UserName, Action, Details) "
            "VALUES (%s,%s,%s,%s,%s)",
            (account_id, user["id"], user.get("name") or user.get("email") or "", action, details),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


@app.get("/api/auth/me")
def me(user=Depends(get_current_user)):
    return {**user, "is_admin": is_admin(user)}


# ---------------------------------------------------------------- resumen de bienvenida
_EXCLUDED_FOLDER_PARTS = [
    "archiv", "spam", "junk", "bulk", "trash", "deleted",
    "papelera", "basura", "borrado", "sent", "enviado", "draft", "borrador",
]


def _is_excluded_folder(folder: str) -> bool:
    low = (folder or "").lower()
    return any(p in low for p in _EXCLUDED_FOLDER_PARTS)


@app.get("/api/welcome")
def welcome_summary(user=Depends(get_current_user)):
    ids, _ = _account_ids_for(user)
    if not ids:
        return {"first_login": False, "last_login": None, "total_unread": 0, "folders": [], "preview": []}
    ph = ",".join(["%s"] * len(ids))
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute("SELECT LastLogin FROM HUBMAIL_UserMeta WHERE UserID=%s", (user["id"],))
        row = cur.fetchone()
        last_login = row["LastLogin"] if row else None
        cur.execute(
            "SELECT Folder, COUNT(*) AS N FROM HUBMAIL_Messages "
            f"WHERE AccountID IN ({ph}) AND Seen=0 GROUP BY Folder",
            tuple(ids),
        )
        grouped = cur.fetchall()
        folders = [
            {"folder": r["Folder"], "count": r["N"]}
            for r in grouped
            if not _is_excluded_folder(r["Folder"])
        ]
        folders.sort(key=lambda f: f["count"], reverse=True)
        total = sum(f["count"] for f in folders)
        cur.execute(
            "SELECT m.UID, m.Folder, m.Subject, m.FromEmail, m.FromName, "
            "m.DateSent AS MsgDate, m.AccountID "
            "FROM HUBMAIL_Messages m "
            f"WHERE m.AccountID IN ({ph}) AND m.Seen=0 "
            "AND NOT (m.Folder LIKE '%%Archiv%%' OR m.Folder LIKE '%%Spam%%' "
            "OR m.Folder LIKE '%%Junk%%' OR m.Folder LIKE '%%Bulk%%' "
            "OR m.Folder LIKE '%%Trash%%' OR m.Folder LIKE '%%Deleted%%' "
            "OR m.Folder LIKE '%%Papelera%%' OR m.Folder LIKE '%%Basura%%' "
            "OR m.Folder LIKE '%%Borrad%%' OR m.Folder LIKE 'Sent%%' "
            "OR m.Folder LIKE '%%Enviad%%' OR m.Folder LIKE 'Draft%%') "
            "ORDER BY m.DateSent DESC "
            "LIMIT 8",
            tuple(ids),
        )
        preview_rows = cur.fetchall()
        cur.execute(
            f"SELECT AccountID, EmailAddress FROM HUBMAIL_Accounts WHERE AccountID IN ({ph})",
            tuple(ids),
        )
        emails = {r["AccountID"]: r["EmailAddress"] for r in cur.fetchall()}
        preview = []
        for r in preview_rows:
            preview.append({
                "uid": str(r["UID"]),
                "folder": r["Folder"],
                "subject": r["Subject"] or "(sin asunto)",
                "from_name": r["FromName"] or "",
                "from_email": r["FromEmail"] or "",
                "date": r["MsgDate"],
                "account": emails.get(r["AccountID"], ""),
            })
        return {
            "first_login": last_login is None,
            "last_login": last_login,
            "total_unread": total,
            "folders": folders[:12],
            "preview": preview,
        }
    finally:
        conn.close()


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
    if not is_admin(user):
        raise HTTPException(403, "Solo el administrador puede agregar cuentas")
    admin_uid = get_admin_user_id() or user["id"]
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        imap_host = payload.imap_host or settings.default_imap_host
        imap_port = payload.imap_port or settings.default_imap_port
        smtp_host = payload.smtp_host or settings.default_smtp_host
        smtp_port = payload.smtp_port or settings.default_smtp_port
        username = payload.username or payload.email

        if payload.is_default:
            cur.execute(
                "UPDATE HUBMAIL_Accounts SET IsDefault=0 WHERE UserID=%s", (admin_uid,)
            )
        color = _pick_color(payload.color)
        cur.execute(
            """
            INSERT INTO HUBMAIL_Accounts
                (UserID, EmailAddress, DisplayName, IMAPHost, IMAPPort,
                 SMTPHost, SMTPPort, Username, PasswordEnc, SignatureHtml, Phone, IsDefault, CanonicalAccountID, Color)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,NULL,%s,NULL,%s)
            """,
            (
                admin_uid, payload.email, payload.display_name,
                imap_host, imap_port, smtp_host, smtp_port,
                username, encrypt_secret(payload.password),
                1 if payload.is_default else 0, color,
            ),
        )
        conn.commit()
        account_id = cur.lastrowid
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


@app.get("/api/settings/colors")
def get_account_colors(user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT AccountID, Color FROM HUBMAIL_AccountColors WHERE UserID=%s",
            (user["id"],),
        )
        return {"colors": {r[0]: r[1] for r in cur.fetchall()}}
    finally:
        conn.close()


@app.put("/api/settings/colors")
def set_account_colors(payload: dict, user=Depends(get_current_user)):
    colors = payload.get("colors") or {}
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM HUBMAIL_AccountColors WHERE UserID=%s", (user["id"],))
        for account_id, color in colors.items():
            if not color:
                continue
            cur.execute(
                "INSERT INTO HUBMAIL_AccountColors (UserID, AccountID, Color) VALUES (%s,%s,%s)",
                (user["id"], int(account_id), color),
            )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@app.put("/api/accounts/{account_id}")
def update_account(account_id: int, payload: AccountPayload, user=Depends(get_current_user)):
    if not is_admin(user):
        raise HTTPException(403, "Solo el administrador puede editar cuentas")
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
        color = _pick_color(payload.color) if payload.color else (acc.get("Color") or "")

        cur.execute(
            """
            UPDATE HUBMAIL_Accounts SET
                EmailAddress=%s, DisplayName=%s, IMAPHost=%s, IMAPPort=%s,
                SMTPHost=%s, SMTPPort=%s, Username=%s, PasswordEnc=%s,
                IsDefault=%s, Color=%s
            WHERE AccountID=%s AND UserID=%s
            """,
            (
                payload.email, payload.display_name,
                imap_host, imap_port, smtp_host, smtp_port, username,
                password_enc, 1 if payload.is_default else 0, color, account_id, user["id"],
            ),
        )
        cur.execute(
            """UPDATE HUBMAIL_Accounts SET
                 EmailAddress=%s, DisplayName=%s, IMAPHost=%s, IMAPPort=%s,
                 SMTPHost=%s, SMTPPort=%s, Username=%s, PasswordEnc=%s, Color=%s
               WHERE CanonicalAccountID=%s""",
            (
                payload.email, payload.display_name,
                imap_host, imap_port, smtp_host, smtp_port, username,
                password_enc, color, account_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    updated = _get_account(user, account_id)
    return _account_to_dict(updated)


@app.delete("/api/accounts/{account_id}")
def delete_account(account_id: int, user=Depends(get_current_user)):
    if not is_admin(user):
        raise HTTPException(403, "Solo el administrador puede eliminar cuentas")
    _get_account(user, account_id)
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT AccountID FROM HUBMAIL_Accounts WHERE AccountID=%s OR CanonicalAccountID=%s",
            (account_id, account_id),
        )
        ids = [r["AccountID"] for r in cur.fetchall()]
        for tid in ids:
            for table in ("HUBMAIL_Messages", "HUBMAIL_SyncState", "HUBMAIL_Unread"):
                cur.execute(f"DELETE FROM {table} WHERE AccountID=%s", (tid,))
        cur.execute(
            "DELETE FROM HUBMAIL_Accounts WHERE AccountID=%s OR CanonicalAccountID=%s",
            (account_id, account_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


# ---------------------------------------------------------------- administración (solo admin)
@app.get("/api/admin/users")
def admin_users(user=Depends(get_current_user)):
    if not is_admin(user):
        raise HTTPException(403, "Solo el administrador")
    conn = get_users_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute("SELECT Id, Email, Nombre, Activo FROM HUB_Users ORDER BY Nombre, Email")
        return [
            {"id": r["Id"], "email": r["Email"], "name": r["Nombre"], "active": bool(r["Activo"])}
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


@app.get("/api/admin/accounts")
def admin_accounts(user=Depends(get_current_user)):
    if not is_admin(user):
        raise HTTPException(403, "Solo el administrador")
    admin_uid = get_admin_user_id() or user["id"]
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT * FROM HUBMAIL_Accounts WHERE UserID=%s AND CanonicalAccountID IS NULL "
            "ORDER BY EmailAddress",
            (admin_uid,),
        )
        result = []
        for m in cur.fetchall():
            cur.execute(
                "SELECT UserID FROM HUBMAIL_Accounts WHERE CanonicalAccountID=%s",
                (m["AccountID"],),
            )
            d = _account_to_dict(m)
            d["assigned_users"] = [r["UserID"] for r in cur.fetchall()]
            result.append(d)
        return result
    finally:
        conn.close()


class AssignPayload(BaseModel):
    user_ids: list[int] = Field(default_factory=list)


@app.post("/api/admin/accounts/{account_id}/assign")
def assign_account(account_id: int, payload: AssignPayload, user=Depends(get_current_user)):
    if not is_admin(user):
        raise HTTPException(403, "Solo el administrador")
    admin_uid = get_admin_user_id() or user["id"]
    master = _get_account(user, account_id)
    if master.get("CanonicalAccountID"):
        raise HTTPException(400, "No es una cuenta maestra")
    desired = set(payload.user_ids)
    desired.discard(admin_uid)
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT UserID FROM HUBMAIL_Accounts WHERE CanonicalAccountID=%s", (account_id,)
        )
        current = {r["UserID"] for r in cur.fetchall()}
        for uid in desired - current:
            cur.execute(
                """INSERT INTO HUBMAIL_Accounts
                   (UserID, EmailAddress, DisplayName, IMAPHost, IMAPPort, SMTPHost, SMTPPort,
                    Username, PasswordEnc, SignatureHtml, Phone, IsDefault, CanonicalAccountID, Color)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,NULL,0,%s,%s)""",
                (uid, master["EmailAddress"], master["DisplayName"], master["IMAPHost"],
                 master["IMAPPort"], master["SMTPHost"], master["SMTPPort"], master["Username"],
                 master["PasswordEnc"], account_id, master.get("Color") or ""),
            )
            cur.execute(
                "SELECT COUNT(*) AS N FROM HUBMAIL_Accounts WHERE UserID=%s", (uid,)
            )
            if cur.fetchone()["N"] == 1:
                cur.execute(
                    "UPDATE HUBMAIL_Accounts SET IsDefault=1 WHERE UserID=%s AND CanonicalAccountID=%s",
                    (uid, account_id),
                )
        for uid in current - desired:
            cur.execute(
                "DELETE FROM HUBMAIL_Accounts WHERE UserID=%s AND CanonicalAccountID=%s",
                (uid, account_id),
            )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "assigned_users": sorted(desired)}


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
    account_id = acc["AccountID"]
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT Folder, Delimiter, Flags FROM HUBMAIL_Folders "
            "WHERE AccountID=%s ORDER BY Folder",
            (account_id,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    if not rows:
        return {"delimiter": "/", "folders": []}
    delimiter = rows[0]["Delimiter"] or "/"
    folders = [
        {
            "name": r["Folder"],
            "flags": [f for f in (r["Flags"] or "").split(",") if f],
        }
        for r in rows
    ]
    return {"delimiter": delimiter, "folders": folders}


@app.get("/api/accounts/{account_id}/unread")
def account_unread(account_id: int, user=Depends(get_current_user)):
    acc = _canonical_row(_get_account(user, account_id))
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT Folder, COUNT(*) AS N FROM HUBMAIL_Messages "
            "WHERE AccountID=%s AND Seen=0 GROUP BY Folder",
            (acc["AccountID"],),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    folders = [{"folder": r["Folder"], "count": r["N"]} for r in rows]
    return {
        "account_id": account_id,
        "folders": folders,
        "total": sum(r["N"] for r in rows),
    }


@app.get("/api/accounts/{account_id}/activity")
def account_activity(
    account_id: int,
    user=Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
    user_filter: str | None = Query(default=None),
):
    acc = _canonical_row(_get_account(user, account_id))
    cid = acc["AccountID"]
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT DISTINCT UserName FROM HUBMAIL_ActivityLog WHERE AccountID=%s AND UserName IS NOT NULL AND UserName<>''",
            (cid,),
        )
        users = sorted(r["UserName"] for r in cur.fetchall())
        sql = (
            "SELECT UserName, Action, Details, CreatedAt "
            "FROM HUBMAIL_ActivityLog "
            "WHERE AccountID=%s "
        )
        params = [cid]
        if user_filter:
            sql += "AND UserName=%s "
            params.append(user_filter)
        sql += "ORDER BY CreatedAt DESC, LogID DESC"
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()[:limit]
    finally:
        conn.close()
    return {
        "account_id": cid,
        "users": users,
        "items": [
            {
                "user": r["UserName"] or "",
                "action": r["Action"],
                "details": r["Details"] or "",
                "created_at": r["CreatedAt"],
            }
            for r in rows
        ],
    }


@app.get("/api/admin/activity")
def admin_activity(
    user=Depends(get_current_user),
    account_id: int | None = Query(default=None),
    user_filter: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    if not is_admin(user):
        raise HTTPException(403, "Solo el administrador")
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT AccountID, EmailAddress FROM HUBMAIL_Accounts "
            "WHERE CanonicalAccountID IS NULL ORDER BY EmailAddress"
        )
        accounts = [{"id": r["AccountID"], "email": r["EmailAddress"]} for r in cur.fetchall()]
        if account_id is not None:
            cur.execute(
                "SELECT DISTINCT UserName FROM HUBMAIL_ActivityLog "
                "WHERE AccountID=%s AND UserName IS NOT NULL AND UserName<>''",
                (account_id,),
            )
        else:
            cur.execute(
                "SELECT DISTINCT UserName FROM HUBMAIL_ActivityLog "
                "WHERE UserName IS NOT NULL AND UserName<>''"
            )
        users = sorted(r["UserName"] for r in cur.fetchall())
        sql = "SELECT AccountID, UserName, Action, Details, CreatedAt FROM HUBMAIL_ActivityLog WHERE 1=1 "
        params = []
        if account_id is not None:
            sql += "AND AccountID=%s "
            params.append(account_id)
        if user_filter:
            sql += "AND UserName=%s "
            params.append(user_filter)
        sql += "ORDER BY CreatedAt DESC, LogID DESC"
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()[:limit]
    finally:
        conn.close()
    return {
        "accounts": accounts,
        "users": users,
        "items": [
            {
                "account_id": r["AccountID"],
                "user": r["UserName"] or "",
                "action": r["Action"],
                "details": r["Details"] or "",
                "created_at": r["CreatedAt"],
            }
            for r in rows
        ],
    }


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


def _db_get_attachments(account_id, folder, uid):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT Name, ContentType, Cid, Size, Data FROM HUBMAIL_Attachments "
            "WHERE AccountID=%s AND Folder=%s AND UID=%s ORDER BY AttachID",
            (account_id, folder, uid),
        )
        out = []
        for r in cur.fetchall():
            out.append({
                "name": r["Name"] or "adjunto",
                "content_type": r["ContentType"] or "application/octet-stream",
                "cid": r["Cid"] or "",
                "size": r["Size"] or 0,
                "data": base64.b64encode(r["Data"]).decode() if r["Data"] else "",
            })
        return out
    finally:
        conn.close()


def _msg_detail_row(r, attachments=None):
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
        "attachments": attachments or [],
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
                LIMIT %s OFFSET %s""",
            params + [settings.page_size, (page - 1) * settings.page_size],
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    messages = [_msg_row_to_dict(r) for r in rows]
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
    if not row:
        raise HTTPException(404, "Mensaje no encontrado en la caché")
    attachments = _db_get_attachments(account_id, folder, int(msgid))
    return _msg_detail_row(row, attachments)


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
    _log_activity(user, account_id, action,
                  f"{'Marcó como leído' if action == 'read' else 'Marcó como no leído' if action == 'unread' else 'Marcó con bandera' if action == 'flag' else 'Quitó bandera' if action == 'unflag' else 'Marcó como no spam' if action == 'notspam' else 'Eliminó' if action == 'delete' else f'Movío a {dest}'} (carpeta {folder}, UID {uid})")
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


def _db_get_message_id(account_id, folder, uid):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT MessageIdHeader FROM HUBMAIL_Messages WHERE AccountID=%s AND Folder=%s AND UID=%s",
            (account_id, folder, uid),
        )
        row = cur.fetchone()
        return row["MessageIdHeader"] if row else None
    finally:
        conn.close()


def _db_move_message(account_id, folder, uid, dest, new_uid=None):
    conn = get_conn()
    try:
        cur = conn.cursor()
        if new_uid:
            cur.execute(
                "DELETE FROM HUBMAIL_Messages WHERE AccountID=%s AND Folder=%s AND UID=%s",
                (account_id, dest, new_uid),
            )
            cur.execute(
                "UPDATE HUBMAIL_Messages SET Folder=%s, UID=%s "
                "WHERE AccountID=%s AND Folder=%s AND UID=%s",
                (dest, new_uid, account_id, folder, uid),
            )
        else:
            cur.execute(
                "UPDATE HUBMAIL_Messages SET Folder=%s WHERE AccountID=%s AND Folder=%s AND UID=%s",
                (dest, account_id, folder, uid),
            )
        conn.commit()
    finally:
        conn.close()


@app.post("/api/messages/move")
def move_messages(payload: MoveMessagesPayload, user=Depends(get_current_user)):
    if not payload.uids:
        raise HTTPException(400, "No hay mensajes para mover")
    src = _canonical_row(_get_account(user, payload.source_account_id))
    dst = _canonical_row(_get_account(user, payload.dest_account_id))
    src_id, dst_id = src["AccountID"], dst["AccountID"]

    if src_id == dst_id:
        try:
            with _imap_for(src) as imap:
                for uid in payload.uids:
                    msgid = _db_get_message_id(src_id, payload.folder, int(uid))
                    imap.move_message(payload.folder, uid, payload.dest_folder)
                    new_uid = None
                    if msgid:
                        new_uid = imap.find_uid_by_message_id(payload.dest_folder, msgid)
                    if not new_uid:
                        new_uid = imap.last_uid(payload.dest_folder)
                    _db_move_message(src_id, payload.folder, int(uid), payload.dest_folder, int(new_uid) if new_uid else None)
        except IMAPError as e:
            raise HTTPException(400, str(e))
        _log_activity(user, src_id, "move",
                      f"Movío {len(payload.uids)} correo(s) de '{payload.folder}' a '{payload.dest_folder}' (misma cuenta)")
        return {"ok": True, "moved": len(payload.uids), "cross": False}

    moved = 0
    try:
        with _imap_for(src) as simap, _imap_for(dst) as dimap:
            for uid in payload.uids:
                raw, flags = simap.fetch_raw_with_flags(payload.folder, uid)
                new_uid = dimap.append_message(payload.dest_folder, raw, flags)
                simap.delete_message(payload.folder, uid)
                seen = 1 if "\\Seen" in flags else 0
                _db_cross_move_message(
                    src_id, payload.folder, int(uid),
                    dst_id, payload.dest_folder, int(new_uid), seen,
                )
                moved += 1
    except IMAPError as e:
        raise HTTPException(400, f"No se pudo mover entre cuentas: {e}")
    _log_activity(user, src_id, "move",
                  f"Movío {moved} correo(s) de '{payload.folder}' a '{payload.dest_folder}' en la cuenta {dst['EmailAddress']} (entre cuentas)")
    return {"ok": True, "moved": moved, "cross": True}


def _db_cross_move_message(src_account_id, src_folder, uid, dst_account_id, dst_folder, new_uid, seen):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT MessageIdHeader, InReplyTo, FromName, FromEmail, ToText, CcText, Subject, "
            "DateSent, Answered, Flagged, HasAttachments, BodyHtml, BodyText, Size, Spam, SenderIP "
            "FROM HUBMAIL_Messages WHERE AccountID=%s AND Folder=%s AND UID=%s",
            (src_account_id, src_folder, uid),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                "DELETE FROM HUBMAIL_Messages WHERE AccountID=%s AND Folder=%s AND UID=%s",
                (dst_account_id, dst_folder, new_uid),
            )
            cur.execute(
                "INSERT INTO HUBMAIL_Messages (AccountID, Folder, UID, MessageIdHeader, InReplyTo, "
                "FromName, FromEmail, ToText, CcText, Subject, DateSent, Seen, Answered, Flagged, "
                "HasAttachments, BodyHtml, BodyText, Size, Spam, SenderIP) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (dst_account_id, dst_folder, new_uid, row["MessageIdHeader"], row["InReplyTo"],
                 row["FromName"], row["FromEmail"], row["ToText"], row["CcText"], row["Subject"],
                 row["DateSent"], seen, row["Answered"], row["Flagged"], row["HasAttachments"],
                 row["BodyHtml"], row["BodyText"], row["Size"], row["Spam"], row["SenderIP"]),
            )
            cur.execute(
                "DELETE FROM HUBMAIL_Attachments WHERE AccountID=%s AND Folder=%s AND UID=%s",
                (dst_account_id, dst_folder, new_uid),
            )
            cur.execute(
                "SELECT Name, ContentType, Cid, Size, Data FROM HUBMAIL_Attachments "
                "WHERE AccountID=%s AND Folder=%s AND UID=%s",
                (src_account_id, src_folder, uid),
            )
            atts = cur.fetchall()
            if atts:
                cur.executemany(
                    "INSERT INTO HUBMAIL_Attachments (AccountID, Folder, UID, Name, ContentType, Cid, Size, Data) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    [
                        (dst_account_id, dst_folder, new_uid, a["Name"], a["ContentType"], a["Cid"],
                         a["Size"], a["Data"])
                        for a in atts
                    ],
                )
        cur.execute(
            "DELETE FROM HUBMAIL_Messages WHERE AccountID=%s AND Folder=%s AND UID=%s",
            (src_account_id, src_folder, uid),
        )
        cur.execute(
            "DELETE FROM HUBMAIL_Attachments WHERE AccountID=%s AND Folder=%s AND UID=%s",
            (src_account_id, src_folder, uid),
        )
        conn.commit()
    finally:
        conn.close()


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
    _log_activity(user, account_id, "bulk_delete",
                  f"Eliminó {len(payload.ids)} correo(s) de '{payload.folder}'")
    return {"ok": True, "deleted": len(payload.ids)}


@app.post("/api/accounts/{account_id}/messages/bulk-seen")
def bulk_set_seen(account_id: int, payload: BulkSeenPayload, user=Depends(get_current_user)):
    acc = _canonical_row(_get_account(user, account_id))
    account_id = acc["AccountID"]
    if not payload.ids:
        raise HTTPException(400, "No hay mensajes seleccionados")
    try:
        with _imap_for(acc) as imap:
            imap.set_flags(payload.folder, payload.ids, "\\Seen", payload.seen)
    except IMAPError as e:
        raise HTTPException(400, str(e))
    for uid in payload.ids:
        _db_update_flags(account_id, payload.folder, int(uid), seen=payload.seen)
    _log_activity(user, account_id, "bulk_seen",
                  f"Marcó {len(payload.ids)} correo(s) como {'leído' if payload.seen else 'no leído'} en '{payload.folder}'")
    return {"ok": True, "updated": len(payload.ids), "seen": payload.seen}


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
    try:
        _upsert_sent_recipients(user, payload)
    except Exception:
        pass
    _log_activity(user, acc["AccountID"], "send",
                  f"Envió correo a {', '.join(payload.to) or '(sin destinatario)'}: {payload.subject or '(sin asunto)'}")
    return {"ok": True}


def _upsert_sent_recipients(user, payload):
    entries = {}
    for addr in payload.to + payload.cc + payload.bcc:
        e = addr.strip().lower()
        if not e or not _valid_email(e):
            continue
        entries.setdefault(e, "")
    if not entries:
        return
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute("SELECT Email FROM HUBMAIL_AddressBook WHERE UserID=%s", (user["id"],))
        existing = {r["Email"].lower() for r in cur.fetchall()}
        for email in entries:
            if email in existing:
                continue
            cur.execute(
                "INSERT INTO HUBMAIL_AddressBook (UserID, Email, Name) VALUES (%s,%s,NULL)",
                (user["id"], email),
            )
        conn.commit()
    finally:
        conn.close()


@app.get("/api/wallpaper")
def wallpaper():
    conn = get_users_conn()
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
            """SELECT a.*, COALESCE(a.CanonicalAccountID, a.AccountID) AS EffAccountID,
                      (SELECT COUNT(*) FROM HUBMAIL_Messages m
                       WHERE m.AccountID=COALESCE(a.CanonicalAccountID, a.AccountID)
                         AND m.Folder='INBOX' AND m.Seen=0) AS Unread,
                      (SELECT COUNT(*) FROM HUBMAIL_Messages m
                       WHERE m.AccountID=COALESCE(a.CanonicalAccountID, a.AccountID)) AS Synced
               FROM HUBMAIL_Accounts a WHERE a.UserID=%s""",
            (user["id"],),
        )
        accounts = cur.fetchall()
    finally:
        conn.close()

    results = []
    for acc in accounts:
        n = acc["Unread"]
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
            """SELECT ua.EmailAddress, m.AccountID, m.UID, m.FromName, m.FromEmail,
                      m.Subject, m.DateSent, m.BodyText, m.BodyHtml
               FROM HUBMAIL_Accounts ua
               JOIN HUBMAIL_Accounts c ON c.AccountID = COALESCE(ua.CanonicalAccountID, ua.AccountID)
               JOIN HUBMAIL_Messages m ON m.AccountID = c.AccountID
                  AND m.Folder = 'INBOX' AND m.Seen = 0
               WHERE ua.UserID = %s
               ORDER BY m.DateSent DESC
               LIMIT 8""",
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
        fid = cur.lastrowid
    finally:
        conn.close()
    _log_activity(
        user,
        payload.account_id if scope == "ACCOUNT" else None,
        "rule_create",
        f"Creó la regla '{payload.name}' (alcance {scope.lower()}, acción {payload.action})",
    )
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
    _log_activity(
        user,
        payload.account_id if scope == "ACCOUNT" else None,
        "rule_update",
        f"Actualizó la regla '{payload.name}' (alcance {scope.lower()})",
    )
    return {"ok": True}


@app.delete("/api/filters/{filter_id}")
def delete_filter(filter_id: int, user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT Name, Scope, AccountID FROM HUBMAIL_Filters WHERE FilterID=%s AND UserID=%s",
            (filter_id, user["id"]),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                "DELETE FROM HUBMAIL_Filters WHERE FilterID=%s AND UserID=%s",
                (filter_id, user["id"]),
            )
            conn.commit()
    finally:
        conn.close()
    if row:
        _log_activity(
            user,
            row["AccountID"],
            "rule_delete",
            f"Eliminó la regla '{row['Name']}' (alcance {row['Scope'].lower()})",
        )
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
    conn = get_users_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute("SELECT Nombre, Email FROM HUB_Users WHERE Activo=1 ORDER BY Nombre")
        users = [{"name": r["Nombre"], "email": r["Email"]} for r in cur.fetchall()]
    finally:
        conn.close()

    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
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
        cur.execute(
            "SELECT EntryID, Email, Name FROM HUBMAIL_AddressBook WHERE UserID=%s ORDER BY Name",
            (user["id"],),
        )
        addressbook = [
            {"id": r["EntryID"], "email": r["Email"], "name": r["Name"] or ""}
            for r in cur.fetchall()
        ]
        return {"users": users, "contacts": contacts, "addressbook": addressbook}
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
        cid = cur.lastrowid
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


@app.put("/api/addressbook/{entry_id}")
def update_addressbook(entry_id: int, payload: ContactPayload, user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE HUBMAIL_AddressBook SET Name=%s WHERE EntryID=%s AND UserID=%s",
            (payload.name, entry_id, user["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@app.delete("/api/addressbook/{entry_id}")
def delete_addressbook(entry_id: int, user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM HUBMAIL_AddressBook WHERE EntryID=%s AND UserID=%s",
            (entry_id, user["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


# ---------------------------------------------------------------- libreta de direcciones (autocomplete)
def _valid_email(e):
    return "@" in e and "." in e.split("@")[-1]


def _account_ids_for(user):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT AccountID, CanonicalAccountID, EmailAddress FROM HUBMAIL_Accounts WHERE UserID=%s",
            (user["id"],),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    ids = set()
    own = set()
    for r in rows:
        ids.add(r["CanonicalAccountID"] or r["AccountID"])
        own.add((r["EmailAddress"] or "").strip().lower())
    return ids, own


def collect_addresses(user):
    ids, own = _account_ids_for(user)
    if not ids:
        return 0
    seen = {}
    ph = ",".join(["%s"] * len(ids))
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT DISTINCT FromEmail, FromName FROM HUBMAIL_Messages "
            "WHERE AccountID IN (%s) AND FromEmail IS NOT NULL AND FromEmail<>'' "
            "AND DateSent >= DATE_SUB(NOW(), INTERVAL 60 DAY)" % ph,
            list(ids),
        )
        for r in cur.fetchall():
            e = (r["FromEmail"] or "").strip().lower()
            if not e or e in own or not _valid_email(e):
                continue
            seen.setdefault(e, (r["FromName"] or "").strip())
        cur.execute(
            "SELECT ToText FROM HUBMAIL_Messages WHERE AccountID IN (%s) "
            "AND ToText IS NOT NULL AND ToText<>'' "
            "AND DateSent >= DATE_SUB(NOW(), INTERVAL 60 DAY)" % ph,
            list(ids),
        )
        for r in cur.fetchall():
            try:
                to = json.loads(r["ToText"] or "[]")
            except Exception:
                continue
            for addr in to if isinstance(to, list) else []:
                e = (addr.get("email") or "").strip().lower()
                if not e or e in own or not _valid_email(e):
                    continue
                seen.setdefault(e, (addr.get("name") or "").strip())
    finally:
        conn.close()

    if not seen:
        return 0
    added = 0
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute("SELECT Email FROM HUBMAIL_AddressBook WHERE UserID=%s", (user["id"],))
        existing = {r["Email"].lower() for r in cur.fetchall()}
        for email, name in seen.items():
            if email in existing:
                continue
            cur.execute(
                "INSERT INTO HUBMAIL_AddressBook (UserID, Email, Name) VALUES (%s,%s,%s)",
                (user["id"], email, (name[:255] if name else None)),
            )
            added += 1
        conn.commit()
    finally:
        conn.close()
    return added


@app.post("/api/contacts/collect")
def collect_contacts(user=Depends(get_current_user)):
    added = collect_addresses(user)
    return {"ok": True, "added": added}


@app.get("/api/contacts/autocomplete")
def autocomplete_contacts(q: str = Query(default=""), user=Depends(get_current_user)):
    q = (q or "").strip().lower()
    if len(q) < 1:
        return {"items": []}
    like = "%" + q + "%"
    items = []
    seen = set()

    def add(name, email):
        e = (email or "").strip().lower()
        if not e or e in seen:
            return
        seen.add(e)
        items.append({"name": (name or "").strip(), "email": (email or "").strip()})

    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT Name, Email FROM HUBMAIL_AddressBook WHERE UserID=%s "
            "AND (LOWER(Email) LIKE %s OR LOWER(Name) LIKE %s) ORDER BY Name",
            (user["id"], like, like),
        )
        for r in cur.fetchall():
            add(r["Name"], r["Email"])
        cur.execute(
            "SELECT Name, Email FROM HUBMAIL_Contacts "
            "WHERE (LOWER(Email) LIKE %s OR LOWER(Name) LIKE %s) ORDER BY Name",
            (like, like),
        )
        for r in cur.fetchall():
            add(r["Name"], r["Email"])
    finally:
        conn.close()

    conn2 = get_users_conn()
    try:
        cur2 = conn2.cursor(as_dict=True)
        cur2.execute(
            "SELECT Nombre, Email FROM HUB_Users WHERE Activo=1 "
            "AND (LOWER(Email) LIKE %s OR LOWER(Nombre) LIKE %s) ORDER BY Nombre",
            (like, like),
        )
        for r in cur2.fetchall():
            add(r["Nombre"], r["Email"])
    finally:
        conn2.close()
    return {"items": items[:20]}


@app.get("/api/health")
def health():
    return {"status": "ok"}


class NoCacheStaticFiles(StarletteStaticFiles):
    def file_response(self, full_path, stat_result, scope, status_code=200):
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Cache-Control"] = "no-store"
        return response


app.mount("/", NoCacheStaticFiles(directory="static", html=True), name="static")