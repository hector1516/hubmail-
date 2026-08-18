# SECURITY.md — HUBMail

## Autenticación
- Login contra SQL Server `HUB_Users` (email + password). JWT HS256 con `HUBMAIL_JWT_SECRET`, expiración 480 min.
- Endpoints protegidos por `Authorization: Bearer <jwt>` (helper `_user_from_token` / `get_current_user`).
- Admin global: `it@ecc-sa.com.mx` (miembro de `HUBMAIL_Admins`). Solo el admin crea/gestiona cuentas y asigna cuentas a usuarios.

## Autorización
- Los usuarios ven solo sus cuentas asignadas. `is_admin` (app/filters.py) → el admin ve todas.
- Los filtros globales solo los gestiona el admin; los de cuenta, su dueño.

## Manejo de credenciales
- Contraseñas de cuentas IMAP cifradas con AES (`app/crypto.py`) usando clave en `HUBMAIL_KEY_FILE` (`/data/.hubmail_key`), fuera del contenedor (volumen `hubmail_data`).
- JWT secret y credenciales de BD vía variables de entorno `HUBMAIL_*` (con defaults para el ambiente de pruebas).

## Riesgos conocidos
1. **Secretos como defaults commiteados** (ISSUE-001): `deploy.ps1`, `docker-compose.yml`, `config.py` contienen credenciales del ambiente de pruebas (MySQL, SQL Server, SSH plink, JWT secret, VAPID privada). Repo remoto = riesgo de exposición. **PENDIENTE de rotación.**
2. **Claves VAPID privadas** embebidas como defaults en `config.py`. Si se rotan, cambiar `HUBMAIL_VAPID_*` en el entorno (docker run) y desplegar.
3. **XSS por HTML de correo**: el cuerpo se renderiza en `<iframe sandbox="allow-scripts">` (sin allow-same-origin/allow-top-navigation). NO moverlo a un div del DOM principal.
4. **Proxy de imágenes** (`/api/img`): redirige/descarga URLs de correo con el token; cuidado con SSRF (solo uso interno; verificar restricciones de URL en `_fetch_image`).
5. PAT de GitHub usado para push (ver nota abajo). No commitearlo.

## No guardar aquí (ubicación real)
- Contraseñas/tokens/API keys/secretos NO se copian en este documento. Se encuentran en: `deploy.ps1`, `docker-compose.yml`, `app/config.py`, `.credenciales.env` (local, gitignored).
- El PAT de GitHub (`ghp_*`) utilizado para `git push` en sesiones anteriores NO debe repetirse en archivos ni commits.

## Reglas de seguridad (resumen)
- Nunca loguear contraseñas ni tokens.
- Nunca añadir secretos al repo; usar env/archivos gitignored.
- Los cambios de schema van con migración versionada (rollback planificado).
- Validar inputs de `user_filter`, `folder`, `action` en endpoints (parámetros de URL encodeados en frontend).