import os
from dataclasses import dataclass


@dataclass
class Settings:
    db_server: str
    db_user: str
    db_password: str
    db_name: str
    jwt_secret: str
    jwt_expire_minutes: int
    max_attachment_mb: int
    page_size: int
    key_file: str
    default_imap_host: str
    default_imap_port: int
    default_smtp_host: str
    default_smtp_port: int


def get_settings() -> Settings:
    return Settings(
        db_server=os.getenv("HUBMAIL_DB_SERVER", "172.26.117.220"),
        db_user=os.getenv("HUBMAIL_DB_USER", "sa"),
        db_password=os.getenv("HUBMAIL_DB_PASSWORD", "eyccazo"),
        db_name=os.getenv("HUBMAIL_DB_NAME", "ECCSA_Admon_Pruebas"),
        jwt_secret=os.getenv("HUBMAIL_JWT_SECRET", "cambia-este-secreto-hubmail"),
        jwt_expire_minutes=int(os.getenv("HUBMAIL_JWT_EXPIRE", "480")),
        max_attachment_mb=int(os.getenv("HUBMAIL_MAX_ATTACH_MB", "25")),
        page_size=int(os.getenv("HUBMAIL_PAGE_SIZE", "25")),
        key_file=os.getenv("HUBMAIL_KEY_FILE", "/data/.hubmail_key"),
        default_imap_host=os.getenv("HUBMAIL_IMAP_HOST", "imap.secureserver.net"),
        default_imap_port=int(os.getenv("HUBMAIL_IMAP_PORT", "993")),
        default_smtp_host=os.getenv("HUBMAIL_SMTP_HOST", "smtpout.secureserver.net"),
        default_smtp_port=int(os.getenv("HUBMAIL_SMTP_PORT", "465")),
    )


settings = get_settings()