import base64
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate

from .config import settings
from .crypto import decrypt_secret

MAX_ATTACH_BYTES = settings.max_attachment_mb * 1024 * 1024


class SMTPError(Exception):
    pass


def send_mail(account, to, cc, bcc, subject, body_html, attachments, reply_to=None, read_receipt=False):
    total_size = sum(a.get("size", 0) for a in attachments)
    if total_size > MAX_ATTACH_BYTES:
        raise SMTPError(
            f"Los adjuntos superan el límite de {settings.max_attachment_mb} MB "
            f"({total_size // (1024 * 1024)} MB enviados)"
        )

    outer = MIMEMultipart("mixed")
    outer["From"] = formataddr((account["DisplayName"] or "", account["EmailAddress"]))
    outer["To"] = ", ".join(to)
    if cc:
        outer["Cc"] = ", ".join(cc)
    if bcc:
        outer["Bcc"] = ", ".join(bcc)
    outer["Subject"] = subject or "(sin asunto)"
    if reply_to:
        outer["Reply-To"] = reply_to
    if read_receipt:
        outer["Disposition-Notification-To"] = account["EmailAddress"]
    outer["Date"] = formatdate(localtime=True)

    html = body_html or ""

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html, "html", "utf-8"))
    outer.attach(alt)

    for att in attachments:
        subtype = att.get("content_type", "application/octet-stream").split("/")[-1]
        if subtype == "octet-stream":
            subtype = "octet-stream"
        part = MIMEApplication(base64.b64decode(att["data"]), _subtype=subtype)
        part.add_header("Content-Disposition", "attachment", filename=att["name"])
        outer.attach(part)

    password = decrypt_secret(account["PasswordEnc"])
    port = int(account["SMTPPort"])
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(account["SMTPHost"], port, timeout=60)
        else:
            server = smtplib.SMTP(account["SMTPHost"], port, timeout=60)
            server.starttls()
        try:
            server.login(account["Username"], password)
            server.send_message(outer)
        finally:
            server.quit()
    except SMTPError:
        raise
    except Exception as e:
        raise SMTPError(f"Error al enviar por SMTP: {e}")