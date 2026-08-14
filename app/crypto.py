import os

from cryptography.fernet import Fernet, InvalidToken

from .config import settings


def _load_key() -> bytes:
    env = os.getenv("HUBMAIL_ENCRYPTION_KEY")
    if env:
        return env.encode()
    if os.path.exists(settings.key_file):
        with open(settings.key_file, "rb") as f:
            return f.read().strip()
    key = Fernet.generate_key()
    try:
        os.makedirs(os.path.dirname(settings.key_file), exist_ok=True)
        with open(settings.key_file, "wb") as f:
            f.write(key)
    except OSError:
        pass
    return key


_key = _load_key()


def encrypt_secret(value: str) -> str:
    return Fernet(_key).encrypt(value.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return Fernet(_key).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return ""