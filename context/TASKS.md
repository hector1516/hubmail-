# TASKS.md — HUBMail

## P0 - Crítico
- (ninguno)

## P1 - Importante
- Commitear y pushear el trabajo pendiente (zoom del detalle, toolbar móvil con iconos, barra de actividad). Ya desplegado; falta commit.
- Probar notificaciones push reales e2e en navegador (Chrome/Edge): suscribir, enviar correo de prueba a la cuenta, confirmar notificación y clic → abre la app.

## P2 - Normal
- Verificar comportamiento del zoom (`CSS zoom`) en los navegadores usados por los usuarios; si falla en alguno, migrar a `transform: scale` con ajuste de altura.
- Confirmar con el usuario si la barra de actividad debe quedar visible también sobre el detalle de mensaje en móvil (hoy queda detrás del pane a pantalla completa).

## P3 - Futuro
- Rotar VAPID keys, JWT secret y credenciales por defecto para eliminar secretos del repo (ver SECURITY.md).
- Actualizar documentación/archivos al incorporar nuevos módulos (contactos, filtros, etc. ya existen en `app/` y `static/`).