import codecs
import email
import email.utils
import imaplib
import base64
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from html import escape


class IMAPError(Exception):
    pass


def _utf7_encode(name: str) -> str:
    try:
        return codecs.encode(name, "imap4-utf-7")
    except Exception:
        return name


def _utf7_decode(name: str) -> str:
    try:
        return codecs.decode(name, "imap4-utf-7")
    except Exception:
        return name


def _decode_mime(value):
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _parse_addresses(value):
    if not value:
        return []
    result = []
    for name, addr in email.utils.getaddresses([value]):
        if addr:
            result.append({"name": _decode_mime(name), "email": addr})
    return result


def _fmt_date(value):
    if not value:
        return ""
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return value


def _decode_payload(payload, charset):
    for enc in (charset, "utf-8", "latin-1"):
        if enc:
            try:
                return payload.decode(enc)
            except Exception:
                continue
    return payload.decode("utf-8", "replace")


def _parse_folder_line(line):
    flags = []
    rest = line
    if rest.startswith("("):
        end = rest.find(")")
        flags = rest[1:end].split()
        rest = rest[end + 1:].strip()
    parts = rest.split(" ", 1)
    name = parts[1] if len(parts) > 1 else parts[0]
    name = name.strip().strip('"').replace('\\"', '"')
    return flags, name


class IMAPClient:
    def __init__(self, host, port, username, password):
        self.host = host
        self.port = int(port)
        self.username = username
        self.password = password
        self._conn = None

    def _connect(self):
        try:
            conn = imaplib.IMAP4_SSL(self.host, self.port, timeout=45)
        except Exception as e:
            raise IMAPError(f"No se pudo conectar a IMAP ({self.host}): {e}")
        try:
            conn.login(self.username, self.password)
        except Exception:
            raise IMAPError("Credenciales IMAP incorrectas o cuenta bloqueada")
        self._conn = conn
        return conn

    def close(self):
        if self._conn:
            try:
                self._conn.logout()
            except Exception:
                pass
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def list_folders(self):
        conn = self._connect()
        try:
            typ, data = conn.list()
            if typ != "OK":
                raise IMAPError("Error al listar carpetas")
            folders = []
            for line in data:
                try:
                    s = line.decode("utf-8", "replace")
                except Exception:
                    s = line.decode("latin-1", "replace")
                flags, name = _parse_folder_line(s)
                folders.append({"name": _utf7_decode(name), "flags": flags})
            return folders
        finally:
            self.close()

    def list_messages(self, folder="INBOX", criteria="ALL", page=1, page_size=25, unread_only=False):
        conn = self._connect()
        try:
            typ, _ = conn.select(_utf7_encode(folder), readonly=True)
            if typ != "OK":
                raise IMAPError(f"No se pudo abrir la carpeta {folder}")
            search_criteria = "UNSEEN" if unread_only else criteria
            typ, data = conn.search(None, search_criteria)
            if typ != "OK":
                raise IMAPError("Error en la búsqueda")
            ids = data[0].split()
            total = len(ids)
            ids = ids[::-1]
            start = (page - 1) * page_size
            chunk = ids[start:start + page_size]
            messages = []
            for mid in chunk:
                typ, d = conn.fetch(mid, "(FLAGS RFC822.HEADER)")
                if typ != "OK" or not d or not isinstance(d[0], tuple):
                    continue
                flags, raw = d[0][0].decode("utf-8", "replace"), d[0][1]
                messages.append(self._parse_header(raw, mid.decode(), flags))
            return {"total": total, "page": page, "page_size": page_size, "messages": messages}
        finally:
            self.close()

    def _parse_header(self, raw, msgid, flags):
        msg = email.message_from_bytes(raw)
        return {
            "id": msgid,
            "subject": _decode_mime(msg.get("Subject")) or "(sin asunto)",
            "from": _parse_addresses(msg.get("From")),
            "to": _parse_addresses(msg.get("To")),
            "date": _fmt_date(msg.get("Date")),
            "unread": b"\\Seen" not in flags.encode(),
            "flagged": b"\\Flagged" in flags.encode(),
            "has_attachments": "multipart/mixed" in (msg.get_content_type() or ""),
        }

    def get_message(self, folder, msgid):
        conn = self._connect()
        try:
            conn.select(_utf7_encode(folder), readonly=True)
            typ, d = conn.fetch(msgid, "(FLAGS RFC822)")
            if typ != "OK" or not d or not isinstance(d[0], tuple):
                raise IMAPError("Mensaje no encontrado")
            flags, raw = d[0][0].decode("utf-8", "replace"), d[0][1]
            msg = email.message_from_bytes(raw)
            return self._full_message(msg, msgid, flags)
        finally:
            self.close()

    def _full_message(self, msg, msgid, flags):
        body_html = ""
        body_text = ""
        attachments = []
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
                attachments.append({
                    "name": _decode_mime(fn) or "adjunto",
                    "content_type": ct,
                    "cid": "",
                    "size": len(payload),
                    "data": base64.b64encode(payload).decode(),
                })
            elif ct == "text/html" and not body_html:
                body_html = _decode_payload(payload, part.get_content_charset())
            elif ct == "text/plain" and not body_text:
                body_text = _decode_payload(payload, part.get_content_charset())
            elif ct.startswith("image/") and disp == "inline":
                cid = part.get("Content-ID")
                cid_clean = cid.strip("<>") if cid else ""
                attachments.append({
                    "name": _decode_mime(fn) or cid_clean or "inline",
                    "content_type": ct,
                    "cid": cid_clean,
                    "size": len(payload),
                    "data": base64.b64encode(payload).decode(),
                })
        if not body_html and body_text:
            body_html = "<pre>" + escape(body_text) + "</pre>"
        return {
            "id": msgid,
            "subject": _decode_mime(msg.get("Subject")) or "(sin asunto)",
            "from": _parse_addresses(msg.get("From")),
            "to": _parse_addresses(msg.get("To")),
            "cc": _parse_addresses(msg.get("Cc")),
            "date": _fmt_date(msg.get("Date")),
            "unread": b"\\Seen" not in flags.encode(),
            "flagged": b"\\Flagged" in flags.encode(),
            "body_html": body_html,
            "body_text": body_text,
            "attachments": attachments,
            "message_id": msg.get("Message-ID"),
            "in_reply_to": msg.get("In-Reply-To"),
        }

    def set_flag(self, folder, msgid, flag, value):
        conn = self._connect()
        try:
            conn.select(_utf7_encode(folder))
            prefix = "+" if value else "-"
            conn.store(msgid, prefix + "FLAGS", flag)
        finally:
            self.close()

    def move_message(self, folder, msgid, dest):
        conn = self._connect()
        try:
            conn.select(_utf7_encode(folder))
            typ, _ = conn.copy(msgid, _utf7_encode(dest))
            if typ != "OK":
                raise IMAPError("No se pudo mover a la carpeta destino")
            conn.store(msgid, "+FLAGS", "\\Deleted")
            conn.expunge()
        finally:
            self.close()

    def delete_message(self, folder, msgid):
        conn = self._connect()
        try:
            conn.select(_utf7_encode(folder))
            conn.store(msgid, "+FLAGS", "\\Deleted")
            conn.expunge()
        finally:
            self.close()

    def unread_count(self, folder="INBOX"):
        conn = self._connect()
        try:
            conn.select(_utf7_encode(folder), readonly=True)
            typ, data = conn.search(None, "UNSEEN")
            if typ != "OK":
                return 0
            return len(data[0].split()) if data and data[0] else 0
        finally:
            self.close()