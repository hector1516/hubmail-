import os
from dataclasses import dataclass


@dataclass
class Settings:
    db_server: str
    db_user: str
    db_password: str
    db_name: str
    users_db_server: str
    users_db_user: str
    users_db_password: str
    users_db_name: str
    jwt_secret: str
    jwt_expire_minutes: int
    max_attachment_mb: int
    page_size: int
    key_file: str
    default_imap_host: str
    default_imap_port: int
    default_smtp_host: str
    default_smtp_port: int
    vapid_public_key: str
    vapid_private_key: str
    vapid_subject: str
    deepl_api_key: str
    attachments_dir: str


def get_settings() -> Settings:
    return Settings(
        db_server=os.getenv("HUBMAIL_DB_SERVER", "172.26.90.159"),
        db_user=os.getenv("HUBMAIL_DB_USER", "hubmail"),
        db_password=os.getenv("HUBMAIL_DB_PASSWORD", "eyccazo"),
        db_name=os.getenv("HUBMAIL_DB_NAME", "HUBMAIL"),
        users_db_server=os.getenv("HUBMAIL_USERS_DB_SERVER", "172.26.117.220"),
        users_db_user=os.getenv("HUBMAIL_USERS_DB_USER", "sa"),
        users_db_password=os.getenv("HUBMAIL_USERS_DB_PASSWORD", "eyccazo"),
        users_db_name=os.getenv("HUBMAIL_USERS_DB_NAME", "ECCSA_Admon"),
        jwt_secret=os.getenv("HUBMAIL_JWT_SECRET", "cambia-este-secreto-hubmail"),
        jwt_expire_minutes=int(os.getenv("HUBMAIL_JWT_EXPIRE", "5256000")),
        max_attachment_mb=int(os.getenv("HUBMAIL_MAX_ATTACH_MB", "25")),
        page_size=int(os.getenv("HUBMAIL_PAGE_SIZE", "25")),
        key_file=os.getenv("HUBMAIL_KEY_FILE", "/data/.hubmail_key"),
        default_imap_host=os.getenv("HUBMAIL_IMAP_HOST", "imap.secureserver.net"),
        default_imap_port=int(os.getenv("HUBMAIL_IMAP_PORT", "993")),
        default_smtp_host=os.getenv("HUBMAIL_SMTP_HOST", "smtpout.secureserver.net"),
        default_smtp_port=int(os.getenv("HUBMAIL_SMTP_PORT", "465")),
        vapid_public_key=os.getenv("HUBMAIL_VAPID_PUBLIC", "BMutVGBRlPlW5LUEe2SW0MPKbikLMP95Oya1JLGtcsv9gSrABaZDYtejHhJXo1TOdzJD1e0Bdj3wt5SPjUaK6fQ"),
        vapid_private_key=os.getenv("HUBMAIL_VAPID_PRIVATE", "MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgC55h9YhmoWFKQrj8k2PEOXwK7JGEn96YrNVCgu34T2OhRANCAATLrVRgUZT5VuS1BHtkltDDym4pCzD_eTsmtSSxrXLL_YEqwAWmQ2LXox4SV6NUzncyQ9XtAXY98LeUj41Giun0"),
        vapid_subject=os.getenv("HUBMAIL_VAPID_SUBJECT", "mailto:it@ecc-sa.com.mx"),
        deepl_api_key=os.getenv("HUBMAIL_DEEPL_KEY", ""),
        attachments_dir=os.getenv("HUBMAIL_ATTACHMENTS_DIR", "/data/attachments"),
    )


settings = get_settings()