# STATE.md — HUBMail

## COMPLETADO
- Migración SQL Server → MySQL con doble BD (DEC-003).
- Cache de correos IMAP con sync de 5 min, cuentas compartidas (CanonicalAccountID).
- Admin gestiona cuentas/asignaciones; filtros y antispam (DNSBL), retención en Spam/Trash.
- Libreta de direcciones auto-recolectada (60 días), popup de contactos con CRUD.
- Popup de bienvenida/resumen con actividad reciente (últimos 10 registros).
- Cola de operaciones IMAP (DEC-001) y guardado en Enviados vía cola (DEC-002).
- PWA: manifest, service worker, iconos, responsive móvil (breakpoint 900px, safe-areas, modales full-screen, overlay sidebar, inputs 16px, display-mode standalone).
- Web Push real con VAPID (DEC-004): endpoints `/api/push/*`, tabla PushSubscriptions, disparo desde sync, handlers push/notificationclick en SW, suscripción automática en frontend.
- Detalle de mensaje: iframe con auto-altura + zoom (DEC-005).
- Log de actividad como barra inferior global colapsable (DEC-006).
- Cloudflare Tunnel funcionando: `hubmail.ecc-sa.com.mx` → `http://localhost:8502`.
- Rediseño UI app-first estilo app móvil (Spark/Outlook) en todas las pantallas: endpoint `GET /api/unified` (bandeja unificada), appbar con menú/búsqueda/notif/tema/cuentas, drawer lateral con acciones y cuentas, bottom-nav (Bandeja/Contactos/Buscar/Ajustes), FAB Redactar, tarjetas de mensaje con avatar y tag de cuenta, swipe táctil (eliminar / leído-no leído), modo oscuro persistido (`data-theme`), tema vía variables CSS con soporte claro/oscuro.

## EN DESARROLLO
- (nada actualmente en desarrollo activo)

## PENDIENTE
- Desplegar el rediseño app-first en Docker (rebuild) y verificar en producción.
- Probar e2e push en navegador real (Chrome/Edge) con un correo de prueba a una cuenta suscrita.
- Rotar claves/credenciales que quedaron como defaults commiteados (ver SECURITY.md).

## BLOQUEADO
- (nada bloqueado)

## PRÓXIMO PASO
- Rebuild del contenedor con el rediseño app-first y commit + push del worktree (endpoint unificado, nueva UI).