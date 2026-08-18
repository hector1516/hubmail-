# ISSUES.md — HUBMail

## ISSUE-001 - Credenciales/secretos como defaults commiteados

Estado: ABIERTO

Problema:
`deploy.ps1`, `docker-compose.yml` y `app/config.py` contienen credenciales reales del ambiente de pruebas como valores por defecto (BD MySQL/SQL Server, SSH plink, JWT secret, claves VAPID privadas). El repo es GitHub público/remoto.

Causa conocida:
Defaults puestos por comodidad de despliegue local; nunca rotados.

Workaround:
Ninguno necesario para operar (el ambiente usa esos defaults), pero es un riesgo de exposición.

Solución pendiente:
P0 a futuro: mover a variables de entorno/archivos secretos fuera del repo y rotar todos los valores. Referencia: SECURITY.md.

## ISSUE-002 - Push requiere HTTPS y PWA instalada (iOS)

Estado: ABIERTO (comportamiento por diseño)

Problema:
Web Push solo funciona bajo HTTPS y, en iOS Safari, únicamente con la PWA instalada en pantalla de inicio (iOS 16.4+). En Android funciona directo.

Causa conocida:
Restricciones de los navegadores para Web Push.

Workaround:
HTTPS ya resuelto con Cloudflare Tunnel. Instruir a usuarios iOS a instalar la PWA.

Solución pendiente:
Documentar/instruir a usuarios finales.

## ISSUE-003 - Login del admin con contraseña anterior da 401

Estado: ABIERTO (información)

Problema:
`it@ecc-sa.com.mx` con `Qwe123456?` devuelve 401; la contraseña corporativa cambió. Los endpoints (`/api/welcome`, etc.) funcionan bien con una sesión válida.

Causa conocida:
La autenticación usa `HUB_Users` de SQL Server; la contraseña real ya no es la antigua.

Workaround:
Usar las credenciales vigentes de `HUB_Users`.

Solución pendiente:
Ninguna de código.

## ISSUE-004 - Resolución de la causa de imágenes en login (Bing) — PENDIENTE

Estado: ABIERTO

Problema:
El fondo del login usa `HUB_BingWallpapers` (SQL Server). No se confirmó por completo el mecanismo de refresco de wallpapers en esta memoria.

Causa conocida:
No documentada en la conversación.

Workaround:
N/A.

Solución pendiente:
Verificar en `app/main.py` (`/api/wallpaper`) antes de asumir.

## ISSUE-005 - Migraciones de la versión SQL Server

Estado: INFORMACIÓN

Problema:
Existen dos familias de migraciones: `migrations/` (SQL Server, 0001–0017) y `migrations_mysql/` (MySQL, 0001–0006). La de SQL Server es legado histórico.

Causa conocida:
Migración paulatina (DEC-003).

Workaround:
Solo aplicar `migrations_mysql/`. `migrations/` es referencia histórica.

Solución pendiente:
Ninguna.