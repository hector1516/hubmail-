# INTEGRATIONS.md — HUBMail

> Sin secretos. Detalles de credenciales en SECURITY.md.

## IMAP (lectura/sync)
- Hosts por cuenta (`HUBMAIL_Accounts.IMAPHost/Port`); defaults GoDaddy: `imap.secureserver.net:993` (SSL).
- `app/imap_client.py` (imaplib), charset cp1252 + UTF-7 para carpetas, `\\Seen`/`\\Flagged` etc.
- Flujo: worker de sync abre 1 conexión por cuenta cada 5 min; **nunca** desde requests (DEC-001).

## SMTP (envío)
- `smtpout.secureserver.net:465` (SSL). `app/smtp_client.py` devuelve RFC822 completo para el guardado en Enviados (DEC-002).
- Adjuntos, firma ECCSA por cuenta (`app/signature.py`), lectura de confirmación opcional.

## MySQL (HUBMAIL) — principal
- PyMySQL vía `app/db.py` (`_MySQLConnection`, API compatible con pymssql; usar `cursor(as_dict=True)`).
- Schema en `migrations_mysql/0001..0006`, aplicado por `apply_migrations.py`.

## SQL Server (ECCSA_Admon_Pruebas) — usuarios
- pymssql, charset `cp1252`. Tablas: `HUB_Users` (auth), `HUB_BingWallpapers` (fondo login).
- `app/db.py:get_users_conn()`.

## Cloudflare Tunnel (HTTPS público)
- `hubmail.ecc-sa.com.mx` → hostname público; ruta `*` → origen `http://localhost:8502` (**http, no https**; usar https causa 502).
- Gestionado remotamente en Cloudflare Zero Trust dashboard (cloudflared corre en el servidor Windows con `--token-file`).
- No hay config de túnel en este repo.

## Web Push (VAPID)
- `pywebpush` en `app/push.py`; suscripciones en `HUBMAIL_PushSubscriptions` (endpoint único por Endpoint).
- Endpoints: `GET /api/push/config` (VAPID pública), `POST /api/push/subscribe`, `POST /api/push/unsubscribe`.
- Disparo: `sync.py:_push_new_mail` al llegar correos nuevos a INBOX (usuarios asignados vía `HUBMAIL_Accounts`).
- Claves VAPID (ES256) por defecto en `app/config.py`.

## Antispam / DNSBL
- Listas en `HUBMAIL_SpamLists` (tipo DNSBL, p.ej. Spamhaus ZEN). `app/filters.py:check_dnsbl(sender_ip)`.
- Filtros por cuenta/globales con acciones (leído/spam/eliminar/mover).

## Bing Wallpapers
- `GET /api/wallpaper` sirve fondo de login desde `HUB_BingWallpapers` (SQL Server).