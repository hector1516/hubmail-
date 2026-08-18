# CHANGELOG.md — HUBMail (cambios de contexto)

> Changelog de CONTEXTO (arquitectura/reglas/decisiones/estado/integraciones), no de código.

## 2026-08-18

- [STATE] PWA completa: responsive móvil (breakpoint 900px, safe-areas, modales full-screen, overlay sidebar, inputs 16px), manifest+SW+iconos, display-mode standalone.
- [INTEGRATION] Web Push real (VAPID): `/api/push/*`, tabla PushSubscriptions, pywebpush, disparo desde sync, handlers push/notificationclick.
- [ARCHITECTURE] Detalle de mensaje: iframe con auto-altura (postMessage) y controles de zoom (−/+).
- [DECISION] DEC-006: log de actividad movido a barra inferior global colapsable (fuera del marco del mensaje).
- [STATE] Cloudflare Tunnel operativo: `hubmail.ecc-sa.com.mx` → `http://localhost:8502` (origen http; https causaba 502).

## Historial relevante previo (resumen)
- [ARCHITECTURE] DEC-001 cola de operaciones IMAP; DEC-002 guardado en Enviados vía cola; DEC-003 doble BD; DEC-004 PWA+push; DEC-005 iframe auto-altura/zoom.
- [INTEGRATION] Migración SQL Server → MySQL (doble BD); retención automática Spam/Trash; libreta de contactos auto-recolectada; popup de bienvenida con actividad.