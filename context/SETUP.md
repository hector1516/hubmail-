# SETUP.md — HUBMail

> NO incluye secretos reales. Los valores de ambiente de pruebas aparecen como defaults en `deploy.ps1`/`docker-compose.yml`/`config.py` (ver SECURITY.md).

## Requisitos
- Windows (host de despliegue) con PowerShell.
- plink (PuTTY): `C:\Program Files\HeidiSQL\plink.exe`.
- Docker en el servidor remoto (172.26.90.159).
- Python 3.11 local (para migraciones/compile).

## Entorno / Variables de entorno
Prefijo `HUBMAIL_*` (ver `app/config.py`):
- `HUBMAIL_DB_SERVER/_USER/_PASSWORD/_NAME` → MySQL. En el contenedor usar `172.17.0.1` (gateway del bridge de Docker; apuntar a la IP del host `172.26.90.159` falla con `2013 Lost connection` por hairpin NAT en Docker Desktop). Desde el host Windows, `172.26.90.159` funciona. Defaults: 172.17.0.1 / hubmail / eyccazo / HUBMAIL.
- `HUBMAIL_USERS_DB_SERVER/_USER/_PASSWORD/_NAME` → SQL Server (defaults: 172.26.117.220 / sa / eyccazo / ECCSA_Admon_Pruebas).
- `HUBMAIL_JWT_SECRET`, `HUBMAIL_JWT_EXPIRE` (480 min).
- `HUBMAIL_MAX_ATTACH_MB` (25), `HUBMAIL_PAGE_SIZE` (25).
- `HUBMAIL_KEY_FILE` (default `/data/.hubmail_key`) — clave AES para cifrar contraseñas de cuentas.
- `HUBMAIL_IMAP_HOST/PORT` (imap.secureserver.net:993), `HUBMAIL_SMTP_HOST/PORT` (smtpout.secureserver.net:465).
- `HUBMAIL_VAPID_PUBLIC/_PRIVATE/_SUBJECT` (claves Web Push; defaults embebidos).

## Instalación local (solo herramienta)
```powershell
pip install -r requirements.txt          # fastapi, uvicorn, pymssql, PyMySQL, cryptography, PyJWT, python-multipart, pywebpush
python apply_migrations.py               # aplica migrations_mysql/*.sql contra MySQL
python -m py_compile app\main.py app\sync.py app\push.py   # check sintaxis
node --check static\app.js static\sw.js  # check JS
```

## Despliegue a producción
```powershell
powershell -ExecutionPolicy Bypass -File .\deploy.ps1
```
Qué hace `deploy.ps1`:
1. Bootstrap de `upload.py` en el host vía plink (SSH `eccsa@172.26.90.159`).
2. Sube `app/*.py`, `static/*`, `migrations_mysql/*.sql`, `requirements.txt`, `Dockerfile`, `apply_migrations.py`.
3. `docker build -t eccsa/hubmail:latest`.
4. Detiene/elimina contenedor anterior y corre nuevo:
   `docker run -d --name hubmail --restart unless-stopped -p 8502:8502 -v hubmail_data:/data -e <HUBMAIL_DB_* y HUBMAIL_USERS_DB_*>`.
5. Muestra los últimos logs.

> IMPORTANTE: cualquier archivo **nuevo** en `static/` o `app/` debe añadirse a la lista de `Upload-File` en `deploy.ps1`.

## Servicios dependientes
- MySQL (BD HUBMAIL) — requerido. En el contenedor se accede vía `172.17.0.1`; desde el host `172.26.90.159`.
- SQL Server `172.26.117.220` (HUB_Users, HUB_BingWallpapers) — requerido.
- IMAP/SMTP GoDaddy — requerido para sync y envío.
- Cloudflare Tunnel → `http://localhost:8502` para HTTPS público (configurado remotamente en Cloudflare Zero Trust; cloudflared corre con `--token-file` en Windows del servidor).
- Acceso: app local `http://172.26.90.159:8502`, pública `https://hubmail.ecc-sa.com.mx`.