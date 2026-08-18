# DECISIONS.md — HUBMail

## DEC-001 - Cola de operaciones IMAP

Estado: ACTIVA

Decisión:
Todo lo que escriba a IMAP (leído/no leído, flag, eliminar, mover, guardar en Enviados) se encola en `HUBMAIL_PendingOps` y solo el worker de sync (5 min) lo ejecuta contra IMAP. La UI refleja el cambio inmediatamente desde MySQL.

Motivo:
Evitar múltiples conexiones IMAP simultáneas por request, latencia y bloqueos; centralizar el acceso de escritura en un solo flujo confiable.

Alternativas descartadas:
Escribir IMAP en el request síncrono.

Consecuencia:
Los cambios de IMAP tienen hasta ~5 min de latencia; el estado de la op se marca `done`/`error` y el error se registra sin romper la UI. `PendingOps.RawMessage` guarda el RFC822 para `append`.

## DEC-002 - Guardar enviados vía cola con RFC822

Estado: ACTIVA

Decisión:
`send_mail` (smtp_client.py) devuelve el mensaje RFC822 completo (`outer.as_bytes()`). `send_message` encola una op `append` con ese raw. El worker (`_apply_append_op` + `_sent_folder`) hace `APPEND` a la carpeta Sent de la cuenta (detectada por nombre/flags, fallback "Sent").

Motivo:
Persistir en Enviados sin conexión IMAP extra en el envío y de forma consistente con DEC-001.

Consecuencia:
El correo aparece en la carpeta Enviados tras el siguiente ciclo de sync.

## DEC-003 - Doble base de datos (MySQL + SQL Server)

Estado: ACTIVA

Decisión:
El schema nuevo de la app vive en MySQL (`HUBMAIL`, con `migrations_mysql/`). SQL Server (`ECCSA_Admon_Pruebas`) se conserva **solo** para `HUB_Users` (login) y `HUB_BingWallpapers` (fondo login). `app/db.py` envuelve PyMySQL con API compatible con pymssql.

Motivo:
Migrar progresivamente el schema propio a MySQL conservando la autenticación corporativa existente.

Consecuencia:
Dos conexiones/credenciales distintas; cuidado con charsets (MySQL utf8mb4, SQL Server cp1252) y con `DictCursor` vs `as_dict=True`.

## DEC-004 - PWA + Web Push reales (VAPID)

Estado: ACTIVA

Decisión:
La app es PWA instalable (manifest, service worker, iconos) y las notificaciones de correos nuevos usan Web Push con VAPID (`pywebpush`, claves generadas ES256 embebidas como defaults en `config.py`). Suscripciones en `HUBMAIL_PushSubscriptions`; el sync dispara `notify_new_mail` al detectar correos nuevos en INBOX.

Motivo:
Notificaciones reales del sistema (aunque la app esté cerrada), mejor que el polling in-app.

Consecuencia:
Requiere HTTPS (resuelto con Cloudflare Tunnel). En iOS Safari el push solo funciona con la PWA instalada (iOS 16.4+). Las claves VAPID privadas por defecto están commiteadas en `config.py` — riesgo documentado en SECURITY/ISSUES.

## DEC-005 - Render del cuerpo del correo en iframe aislado con auto-altura

Estado: ACTIVA

Decisión:
El cuerpo del mensaje se renderiza en `<iframe sandbox="allow-scripts">` (aislado, sin allow-same-origin ni allow-top-navigation). Un script inyectado mide `scrollHeight` y lo reporta por `postMessage` para ajustar la altura del iframe (`data-hid`), de modo que el contenedor (pane/modal) scrollea completo. Se añadieron controles de zoom (−/+ , 40%–200%) que envían `zoom` por postMessage.

Motivo:
Permitir scroll completo del cuerpo en PWA móvil (el iframe ya no tiene altura fija) y ajustar el texto a la pantalla.

Consecuencia:
Los scripts del correo corren dentro del sandbox aislado (no acceden al DOM padre ni a cookies). El handler `message` del padre solo confía en `e.data.hmh`/`hid` y `e.data.zoom`.

## DEC-006 - Log de actividad en barra inferior global

Estado: ACTIVA

Decisión:
La "Actividad de la cuenta" se movió del detalle del mensaje a una barra inferior fija del shell (`#activity-bar`), fuera del marco de mensajes, colapsable con botón 📋, con filtro por usuario.

Motivo:
El usuario lo pidió: el log no debe estar dentro del marco del mensaje.

Consecuencia:
`loadActivity()` (en app.js) rellena `#activity-bar` desde `GET /api/accounts/{id}/activity` (limit 15, `user_filter` opcional) y se llama en `renderShell` y tras acciones.