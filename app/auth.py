import datetime

import jwt
from fastapi import Header, HTTPException

from .config import settings
from .db import get_conn


def create_token(user_id: int, email: str, nombre: str) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "name": nombre,
        "iat": now,
        "exp": now + datetime.timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def authenticate(email: str, password: str):
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT Id, Email, Nombre FROM HUB_Users WHERE Email=%s AND Password=%s AND Activo=1",
            (email, password),
        )
        return cur.fetchone()
    finally:
        conn.close()


def get_current_user(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "No autorizado")
    token = authorization[7:]
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Sesión inválida o expirada")
    return {"id": int(payload["sub"]), "email": payload["email"], "name": payload["name"]}