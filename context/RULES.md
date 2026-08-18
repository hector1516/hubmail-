# RULES.md — HUBMail

Leer antes de modificar código.

## OBLIGATORIO

- **Escritura IMAP solo desde el worker**: ninguna acción de un request HTTP puede escribir a IMAP directamente. Debe hacer DB inmediato + `INSERT` en `HUBMAIL_PendingOps` (la aplica el sync de 5 min). Ver DEC-001.
- **Agregar migración**: todo cambio de schema (MySQL) = archivo nuevo `migrations_mysql/NNNN_*.sql` y aplicarlo con `python apply_migrations.py`. Las migraciones se aplican automáticamente al arrancar el contenedor.
- **Nuevos archivos estáticos** (`static/`) deben agregarse explícitamente a la lista de `Upload-File` de `deploy.ps1`, o no llegarán al servidor.
- **Mantener estilo vanilla**: frontend sin frameworks/build tools. Un solo `app.js`, `style.css`, `index.html`.
- **Validar sintaxis antes de desplegar**: `python -m py_compile app\*.py` y `node --check static\app.js static\sw.js`.
- **Cuerpo de correo**: el HTML del correo se renderiza en `<iframe sandbox>` (aislamiento de scripts). No renderizar `body_html` directamente en el DOM principal.
- **Servir desde BD**: listas, detalle, carpetas, notificaciones y no leídos deben servirse desde la caché MySQL, no consultando IMAP en el request.
- **Errores de IMAP no rompen la UI**: operaciones de usuario con `await api(...).catch(...)`, sin bloquear.

## RECOMENDADO

- Comentarios de commit en español, descriptivos (una línea).
- Antes de commit: `git status`, `git diff`, revisar que no entren secretos.
- Push con el PAT de GitHub (ver SECURITY.md).
- Los mensajes nuevos en INBOX notifican por push (ver `_push_new_mail` en sync.py).

## PROHIBIDO

- **NO** commitear secretos: contraseñas reales, tokens, API keys, PAT, claves VAPID privadas. (Nota: los defaults de `deploy.ps1`/`config.py` contienen credenciales de ambiente de pruebas; ver ISSUES/SECURITY.)
- **NO** usar `force-push`, `--amend`, ni cambiar config de git salvo indicación explícita.
- **NO** inventar endpoints, tablas o claves que no existan en el código.
- **NO** usar SQL Server para datos nuevos de la app: el schema nuevo es MySQL. SQL Server solo para `HUB_Users` y `HUB_BingWallpapers`.
- **NO** romper el modo PWA (manifest/SW): el SW es network-first; no cachear `/api/*`.
- **NO** ejecutar scripts del correo en el DOM principal (riesgo XSS).