# PROJECT.md — HUBMail

## Nombre
HUBMail (cliente de correo interno ECCSA Automation).

## Propósito
Cliente de correo web corporativo para el personal de ECCSA: leer, enviar, mover, filtrar y gestionar correos de múltiples cuentas IMAP desde un navegador, con PWA instalable y notificaciones push.

## Problema que resuelve
- Unificar varios correos IMAP (GoDaddy/secureserver.net) en una sola interfaz web para todos los empleados.
- Evitar tocar IMAP por cada acción del usuario: se sincroniza en segundo plano (5 min) y se lee desde caché en BD.
- Los usuarios solo ven las cuentas que el administrador les asigna.
- Funciona como PWA en móviles (instalable, notificaciones push, responsive).

## Usuarios
- Empleados de ECCSA (usuarios con cuentas asignadas).
- Administrador global: `it@ecc-sa.com.mx` (ve todas las cuentas, gestiona asignaciones).

## Alcance
- Multi-cuenta IMAP, multi-usuario, cache centralizada en BD (cuentas compartidas vía CanonicalAccountID).
- Redacción/envío SMTP con firma ECCSA por cuenta y guardado en "Enviados".
- Antispam (DNSBL), filtros por cuenta y globales, retención automática en Spam/Trash.
- Libreta de direcciones auto-recolectada, actividad por cuenta, log global de admin.
- PWA: manifest, service worker, responsive móvil, notificaciones push (Web Push VAPID).

## Tecnologías principales
- Backend: Python 3.11, FastAPI, uvicorn.
- BD: MySQL (`HUBMAIL`) + SQL Server (`ECCSA_Admon_Pruebas` para usuarios/wallpapers).
- Acceso BD: PyMySQL (wrapper `app/db.py`) y pymssql.
- IMAP/SMTP: `imaplib`/`smtplib` (GoDaddy: imap.secureserver.net:993, smtpout.secureserver.net:465).
- Frontend: HTML/CSS/JS vanilla (sin frameworks), un solo `app.js`.
- Push: pywebpush (VAPID). Deploy: Docker + script PowerShell `deploy.ps1`.
- Túnel público: Cloudflare Tunnel (remoto, gestionado en Zero Trust).

## Estado general
Estable en producción. Últimos trabajos: PWA completa (responsive, push real), detalle de mensaje con auto-altura y zoom, log de actividad como barra inferior global.