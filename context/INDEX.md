# ÍNDICE DE MEMORIA DEL PROYECTO — HUBMail

> Memoria externa portable. Una IA puede entrar al proyecto leyendo estos archivos sin necesidad de la conversación original.

| Archivo | Contenido |
|---|---|
| PROJECT.md | Qué es el proyecto, propósito, alcance, tecnologías |
| ARCHITECTURE.md | Cómo está construido (componentes, DBs, flujos) |
| RULES.md | Reglas obligatorias / recomendadas / prohibidas |
| DECISIONS.md | Decisiones importantes de arquitectura |
| STATE.md | Estado actual (completado / en desarrollo / pendiente) |
| TASKS.md | Trabajo pendiente priorizado |
| ISSUES.md | Problemas conocidos |
| SETUP.md | Cómo levantar/ejecutar/desplegar |
| SECURITY.md | Seguridad, credenciales, riesgos |
| INTEGRATIONS.md | Servicios externos (IMAP/SMTP/Cloudflare/push) |
| CHANGELOG.md | Cambios recientes de contexto |

## LECTURA RECOMENDADA

Siempre:
- INDEX.md
- PROJECT.md
- RULES.md
- STATE.md

Solo cuando sea necesario:
- ARCHITECTURE.md
- DECISIONS.md
- INTEGRATIONS.md
- SETUP.md
- SECURITY.md
- ISSUES.md
- TASKS.md

## Datos clave de referencia rápida

- App: FastAPI (Python 3.11) + frontend vanilla JS, en Docker, puerto **8502**.
- Servidor prod: `172.26.90.159` (contenedor `hubmail`, host Windows con plink SSH).
- URL pública: `https://hubmail.ecc-sa.com.mx` (Cloudflare Tunnel → `http://localhost:8502`).
- BD principal: **MySQL** `HUBMAIL`. BD de usuarios: **SQL Server** `ECCSA_Admon_Pruebas`.
- Regla crítica: todo lo que escriba a IMAP pasa por la **cola de 5 min** (HUBMAIL_PendingOps).
- Git: `origin = https://github.com/hector1516/hubmail-.git` (rama `main`).