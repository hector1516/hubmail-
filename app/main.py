import threading
import time
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.staticfiles import StaticFiles as StarletteStaticFiles
from pydantic import BaseModel, Field

from .auth import authenticate, create_token, get_current_user
from .config import settings
from .crypto import encrypt_secret, decrypt_secret
from .db import get_conn
from .imap_client import IMAPClient, IMAPError
from .smtp_client import send_mail, SMTPError
from . import sync as syncmod

app = FastAPI(title="HUBMail", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_ACCOUNTS = 5

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


@app.on_event("startup")
def _start_sync_thread():
    global _sync_thread
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
    signature_html: str = ""
    is_default: bool = False


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
        "signature_html": acc["SignatureHtml"] or "",
        "is_default": bool(acc["IsDefault"]),
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
    return user


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
                 SMTPHost, SMTPPort, Username, PasswordEnc, SignatureHtml, IsDefault)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                user["id"], payload.email, payload.display_name,
                imap_host, imap_port, smtp_host, smtp_port,
                username, encrypt_secret(payload.password),
                payload.signature_html, 1 if payload.is_default else 0,
            ),
        )
        conn.commit()
        cur.execute("SELECT @@IDENTITY AS Id")
        account_id = cur.fetchone()["Id"]
    finally:
        conn.close()

    acc = _get_account(user, account_id)
    return _account_to_dict(acc)


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
                SignatureHtml=%s, IsDefault=%s
            WHERE AccountID=%s AND UserID=%s
            """,
            (
                payload.email, payload.display_name,
                imap_host, imap_port, smtp_host, smtp_port, username,
                password_enc, payload.signature_html,
                1 if payload.is_default else 0, account_id, user["id"],
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
        cur = conn.cursor()
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
    acc = _get_account(user, account_id)
    try:
        with _imap_for(acc) as imap:
            imap.list_folders()
    except IMAPError as e:
        raise HTTPException(400, f"IMAP: {e}")
    return {"ok": True, "message": "Conexión IMAP correcta"}


# ---------------------------------------------------------------- correo
@app.get("/api/accounts/{account_id}/folders")
def list_folders(account_id: int, user=Depends(get_current_user)):
    acc = _get_account(user, account_id)
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
    acc = _get_account(user, account_id)
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
    acc = _get_account(user, account_id)
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
    acc = _get_account(user, account_id)
    uid = int(msgid)
    try:
        with _imap_for(acc) as imap:
            if action in ("read", "unread"):
                imap.set_flag(folder, msgid, "\\Seen", action == "read")
                _db_update_flags(account_id, folder, uid, seen=action == "read")
            elif action in ("flag", "unflag"):
                imap.set_flag(folder, msgid, "\\Flagged", action == "flag")
                _db_update_flags(account_id, folder, uid, flagged=action == "flag")
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
    acc = _get_account(user, account_id)
    try:
        with _imap_for(acc) as imap:
            return {"unread": imap.unread_count("INBOX")}
    except IMAPError:
        return {"unread": None}


@app.post("/api/accounts/{account_id}/messages/bulk-delete")
def bulk_delete(account_id: int, payload: BulkDeletePayload, user=Depends(get_current_user)):
    acc = _get_account(user, account_id)
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
    acc = _get_account(user, account_id)
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
        )
    except SMTPError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


# ---------------------------------------------------------------- notificaciones
@app.get("/api/notifications")
def notifications(user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            """SELECT a.*,
                      (SELECT COUNT(*) FROM HUBMAIL_Messages m
                       WHERE m.AccountID=a.AccountID AND m.Folder='INBOX' AND m.Seen=0) AS Unread,
                      (SELECT COUNT(*) FROM HUBMAIL_Messages m WHERE m.AccountID=a.AccountID) AS Synced
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
                with _imap_for(acc) as imap:
                    n = imap.unread_count("INBOX")
            except Exception:
                n = None
        results.append({"account_id": acc["AccountID"], "email": acc["EmailAddress"], "unread": n})
    return results


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