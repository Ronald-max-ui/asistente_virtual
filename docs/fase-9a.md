# Fase 9A — Identidad administrativa y auditoría

Implementada el 7 de octubre de 2026. No incluye dashboard ni editores de Fase 9B. No se crearon usuarios en las bases operativas existentes: bootstrap, mutaciones, comprobantes y E2E se probaron en SQLite temporal.

## Arquitectura

`AppServices.admin` compone `AdminService` con `SQLiteAdminRepository`. Los routers utilizan dependencias de autenticación y `permission(...)`; las reglas RBAC tienen una única definición en `security/admin_policy.py`. `CommercialService` conserva las reglas comerciales y escribe el cambio y su auditoría dentro de la misma transacción. `PricingService` conserva toda su autoridad; login/RBAC no intervienen en importes, campañas ni acciones del LLM.

Identidad y auditoría comercial viven en `commercial.sqlite3`, esquema 2. La revisión de comprobantes y su auditoría viven en `runtime.sqlite3`, esquema 2. La actualización desde esquema 1 es aditiva y transaccional: mantiene tablas/datos previos y añade tablas. No hay transacción que pretenda ser atómica entre dos bases. La consulta `/api/admin/audit` reúne y pagina las dos fuentes y resuelve el nombre del actor desde identidad. Los repositorios conservan contratos separados para un futuro adaptador PostgreSQL.

## Tablas nuevas

| Base | Tabla | Contenido |
| --- | --- | --- |
| Comercial | admin_roles | Identificadores de roles; política de permisos centralizada en backend |
| Comercial | admin_users | UUID, usuario/email normalizado, nombre visible, Argon2id, rol, enabled, created/updated/last_login y actores |
| Comercial | admin_sessions | ID público de revocación independiente del identificador opaco, hash del identificador, CSRF, usuario, expiraciones y revocación |
| Ambas | admin_audit_log | ID, actor, operación, recurso, timestamp, request_id, resultado y snapshots permitidos |
| Runtime | voucher_reviews | voucher_id, review_note, reviewed_by, reviewed_at |

No se almacena la cookie en claro. El token CSRF del patrón synchronizer sí reside en la base privada asociado a la sesión, separado de la cookie. `GET /me` no devuelve ninguno. Los hashes de contraseña sólo están en persistencia; los DTO públicos usan una lista explícita de campos.

## Roles y permisos

| Rol | Permisos |
| --- | --- |
| superadmin | Todos los permisos definidos, usuarios, revocación y auditoría |
| administrador | Lectura/escritura de programas, precios, campañas, avatares y settings; lectura de auditoría |
| admisiones | leads.read, programs.read, prices.read, campaigns.read |
| revisor_pagos | vouchers.read, vouchers.review |
| solo_lectura | Lectura de programas, precios, campañas, avatares, settings, leads y vouchers; no usuarios ni auditoría |

El rol `solo_lectura` incluye datos de prospectos y comprobantes: asignarlo sólo a personal autorizado a ver esos datos. `users.read`, `users.write`, `sessions.revoke` son exclusivos de superadmin. Ocultar controles no concede ni revoca permisos. Se consulta el usuario y el rol vigente en cada operación; no hay permisos copiados a una cookie.

No se permite deshabilitar o reducir el rol del último superadmin habilitado. Deshabilitar un usuario o cambiar su contraseña revoca todas sus sesiones. Reducir un rol afecta las solicitudes siguientes; no cancela retroactivamente una transacción ya autorizada y en ejecución.

## Contraseñas y sesiones

Argon2id mediante `argon2-cffi==25.1.0`: defaults de 64 MiB, 3 iteraciones y paralelismo 1. Configuración validada: memoria 19–128 MiB, iteraciones 2–6, paralelismo 1–4. Máximo 2 operaciones costosas de hashing/verificación por proceso. La contraseña tiene 12–256 caracteres y se rechazan repeticiones y patrones débiles conocidos; no es una comprobación contra un corpus completo de contraseñas filtradas.

Cookie host-only, HttpOnly, SameSite=Strict, Path=/api/admin. En producción: `__Secure-lia_admin_session`, Secure obligatorio y operaciones administrativas sólo bajo HTTPS. El identificador opaco se genera con 32 bytes aleatorios y se guarda en SQLite únicamente su SHA-256; ese hash identifica sesiones y no se usa para contraseñas. La sesión tiene 30 minutos de inactividad y 8 horas absolutas, configurables; nunca se prolonga más allá del límite absoluto. Se mantienen como máximo 10 sesiones por usuario. Las expiradas/revocadas se purgan al abrir nuevas sesiones.

Login: mismo mensaje `Credenciales incorrectas` para usuario inexistente, contraseña incorrecta y usuario deshabilitado. Se verifica un hash ficticio para identidades inexistentes. Límites independientes: 10 intentos/minuto/IP y 5 intentos/5 minutos por cuenta normalizada; la cuenta usa un identificador hash en un almacén acotado en memoria. El límite cuenta también logins correctos, no crea bloqueos permanentes y se reinicia con el proceso. Conservamos una instancia y un worker; Redis/múltiples workers requerirán sustituir este almacén.

## CSRF y navegador

Login exige Origin exacto de `ALLOWED_ORIGINS` y rechaza contexto cross-site. Las mutaciones autenticadas con cookie requieren Origin permitido y `X-CSRF-Token` coincidente con el synchronizer token de la sesión. `GET /api/admin/auth/csrf` permite obtenerlo después de autenticar, con respuesta `no-store`; no es el identificador de sesión. Logout, cambios de contraseña, usuarios, configuración y revisión de vouchers están protegidos.

El cliente mínimo guarda sólo CSRF dentro de una closure. No usa localStorage/sessionStorage, token Bearer, JS inline, eval o HTML de datos. Cookie presente + Bearer no permite evadir CSRF ni recuperar una sesión inválida. El despliegue del panel es del mismo origen; no se añadió CORS con credenciales para orígenes externos.

## Endpoints

| Método/ruta | Política |
| --- | --- |
| POST /api/admin/auth/login | Origin, límites IP/cuenta, credenciales; cookie nueva |
| GET /api/admin/auth/me | Sólo sesión de navegador; id, display_name, role, permissions |
| GET /api/admin/auth/csrf | Sólo sesión; token CSRF separado |
| POST /api/admin/auth/logout | Sesión + CSRF; revocación backend y eliminación cookie |
| PUT /api/admin/auth/password | Sesión + CSRF; contraseña nueva; revoca sesiones |
| GET /api/admin/roles | users.read |
| GET/POST /api/admin/users | users.read / users.write |
| PUT /api/admin/users/{id} | users.write; nombre/rol/enabled |
| PUT /api/admin/users/{id}/password | users.write; reinicio de contraseña |
| GET /api/admin/users/{id}/sessions | sessions.revoke; IDs públicos, sin cookie/hash/CSRF |
| POST /api/admin/users/{id}/sessions/revoke | sessions.revoke; body {session_id} |
| POST /api/admin/users/{id}/sessions/revoke-all | sessions.revoke |
| GET/POST/PUT /api/admin/programs, prices, campaigns, avatars | .read / .write del recurso; contratos comerciales conservados |
| POST /api/admin/avatars/{id}/activate | avatars.write |
| GET/PUT /api/admin/settings | settings.read / settings.write |
| GET /api/admin/leads | leads.read, paginación acotada |
| GET /api/admin/vouchers | vouchers.read, paginación; sin rutas de archivos |
| POST /api/admin/vouchers/{id}/review | vouchers.review; {status, review_note?} |
| GET /api/admin/audit | audit.read; ambas bases, paginación |
| GET /admin/ | Login mínimo accesible, separado de Lía pública |

La revisión sólo admite `pending_review → approved` o `pending_review → rejected`. Las transiciones posteriores producen 409. La comprobación y actualización son una transacción `BEGIN IMMEDIATE`; dos revisores simultáneos no pueden confirmar decisiones diferentes. `review_note` es texto plano de hasta 1000 caracteres, sin HTML. Aprobar refleja una validación administrativa; no realiza conciliación bancaria ni confirma automáticamente una matrícula.

## Auditoría e historial comercial

Las escrituras exitosas de programas/precios/campañas/avatares/settings/usuarios/sesiones y revisiones generan registros. Los cambios comerciales y su auditoría hacen commit juntos; una excepción revierte ambos. El review y su auditoría también hacen commit juntos en runtime.

Los snapshots son una lista permitida: importes/estado/campaña/variantes, datos institucionales necesarios, valor de promociones y selección de avatar. No incluyen password_hash, contraseñas, cookie, CSRF, headers, secretos, notas del revisor, imágenes o rutas privadas del comprobante. Los intentos rechazados generan eventos técnicos sanitizados; no se registran payloads fallidos en auditoría. Los actores humanos son UUID de usuario; `legacy-token`, `bootstrap-cli` y `recovery-cli` identifican explícitamente procesos sin identidad humana.

El historial de tarifas usa snapshots before/after append-only. Consultarlos no modifica el catálogo ni activa una tarifa antigua. Triggers impiden UPDATE/DELETE accidentales de audit log. No es una bitácora criptográficamente firmada ni resistente a un atacante con control del archivo SQLite: proteger permisos del sistema, backups y cuentas del servidor.

## Bootstrap y migración Bearer

Desarrollo: abrir `http://127.0.0.1:8000/admin/` después de crear el superadmin. La plantilla `.env.example` incluye explícitamente los Origins de Vite y del backend en 8000. Si se reutiliza una `.env` anterior, añadir el Origin exacto del login servido por backend a `ALLOWED_ORIGINS`; no usar comodines. Producción usa únicamente el Origin HTTPS institucional.

En un terminal interactivo:

```powershell
backend/venv/Scripts/python.exe backend/create_admin.py --database D:/ruta/privada/commercial.sqlite3
```

Se solicitan usuario, nombre y contraseña dos veces con getpass. No acepta contraseña como argumento, no imprime la contraseña, rechaza terminal no interactivo y sólo crea el primer usuario si no existe otro. Después, los superadmins crean usuarios vía API con CSRF. No hay contraseña por defecto ni administrador creado automáticamente al arrancar.

`ADMIN_LEGACY_TOKEN_ENABLED=true` conserva Bearer para scripts/pruebas existentes; sin token válido no hay acceso y las escrituras se auditan como `legacy-token`. No atribuir esas operaciones a una persona. El login nuevo nunca usa ese mecanismo. La plantilla de producción recomienda `ADMIN_LEGACY_TOKEN_ENABLED=false` y `ADMIN_API_TOKEN=`. Si aún se necesitan scripts, habilitarlo explícitamente con un secreto fuerte, HTTPS, control de acceso y plan de retiro. Los tests/E2E públicos aún prueban esa compatibilidad.

## Backup y restauración

`backup_commercial.py` usa SQLite Backup API: incluye catálogo, usuarios, roles, sesiones y auditoría comercial en una instantánea consistente. `backup_runtime.py` incluye comprobantes, revisiones/auditoría runtime e imágenes con manifiesto. Ningún script copia una SQLite abierta como archivo ordinario ni restaura sobre datos activos. Los comandos de backup abren el origen en modo read-only y no actualizan su esquema implícitamente.

```powershell
backend/venv/Scripts/python.exe backend/backup_commercial.py --database D:/privado/commercial.sqlite3 --output D:/backups/commercial_fecha.sqlite3
backend/venv/Scripts/python.exe backend/verify_admin_backup.py --database D:/backups/commercial_fecha.sqlite3
backend/venv/Scripts/python.exe backend/backup_runtime.py --database D:/privado/runtime.sqlite3 --vouchers D:/privado/vouchers --output D:/backups/runtime_fecha
```

Los backups incluyen hashes y CSRF de sesiones: restringir ACL, cifrar almacenamiento externo, evitar directorios públicos y controlar quién puede descargarlos. No se exportan contraseñas ni tokens a archivos separados. Mantener ambas bases y las imágenes como un conjunto operativo; verificar quick_check, foreign_key_check y hashes del manifiesto. La verificación comercial nueva abre la base en modo read-only y verifica identidad/auditoría sin devolver hashes.

Restauración manual: detener servicio, conservar una copia de seguridad del estado actual, verificar snapshots, restaurar a rutas privadas y respetar la guía operativa. **Antes de reabrir tráfico**, revocar todas las sesiones del backup:

```powershell
backend/venv/Scripts/python.exe backend/create_admin.py --database D:/privado/commercial.sqlite3 --revoke-all-sessions
```

La revocación queda auditada y evita resucitar sesiones previamente cerradas/revocadas. No ejecutamos restauraciones destructivas durante pruebas. Retención administrativa propuesta mediante `RETENTION_ADMIN_USERS_DAYS` y `RETENTION_ADMIN_AUDIT_DAYS`; sin eliminación automática. Revisar obligaciones y política institucional antes de implementarla.

## Despliegue y pruebas

Añadido `/admin/` al proxy de `deploy/nginx.conf.example`. HTTPS termina en el reverse proxy y Uvicorn confía exclusivamente en su proxy local: `--proxy-headers --forwarded-allow-ips=127.0.0.1`, loopback y un worker. La validación de producción exige Secure, límites válidos, Origins HTTPS exactos y la configuración segura anterior. Las rutas API/admin usan no-store y el HTML login CSP sin unsafe-eval. El acceso desde otro origen no es parte del despliegue actual.

Comandos reproducibles:

```powershell
backend/venv/Scripts/python.exe -B -m unittest discover -s backend/tests
npm --prefix avatar-kiosk test
backend/venv/Scripts/python.exe -B backend/admin_e2e.py --output docs/fase-9a-admin-e2e.json
backend/venv/Scripts/python.exe -B backend/browser_e2e.py --production-build --rounds 3 --output docs/fase-9a-public-e2e.json
backend/venv/Scripts/python.exe -B backend/rebuild_knowledge.py --check
backend/venv/Scripts/python.exe -B backend/rebuild_knowledge.py --evaluate
npm --prefix avatar-kiosk run build
backend/venv/Scripts/python.exe -B backend/scan_secrets.py
git diff --check
```

La instalación limpia también se verificó: dependencias Python nuevas (incluido Argon2id), lock, npm ci, migración idempotente, índice temporal real, evaluación, build y health ready con prewarm. El provisionador copia ahora también `static/admin/`.

Resultado: 213 tests backend (186 previos + 27 nuevos) y 44 frontend (41 previos + 3 admin), sin fallos. E2E Chrome administrativo: 9 controles; E2E público: 18 controles/3 conversaciones. Producción: 8 casos aceptados/rechazados según política. Backup online y verificación read-only probados con bases temporales. Índice oficial ready y evaluación académica aprobada. Build conserva la advertencia previa de Three.js de 610.23 KB; no cambió el avatar ni el frontend público. Detalle de validaciones en los JSON de esta fase.

## Archivos de Fase 9A

Nuevos: `security/admin_policy.py`, `security/admin_config.py`, `domain/admin.py`, `persistence/admin_repository.py`, `persistence/admin_schema.py`, `persistence/audit.py`, `persistence/sqlite_admin_repository.py`, `services/admin_service.py`, `api/admin_identity.py`, `create_admin.py`, `verify_admin_backup.py`, `scan_secrets.py`, `static/admin/{index.html,admin.css,adminClient.js,admin.js}`, `admin_e2e.py`, `tests/admin_e2e_app.py`, `tests/test_phase9a.py`, `avatar-kiosk/tests/admin.test.js` y este informe/resultados.

Actualizados: `server.py`, `app_services.py`, `config.py`, `production.py`, `security/{auth,http,config,rate_limit,frontend}.py`, `persistence/{repository,sqlite_repository,sqlite_runtime_repository,sqlite_backup}.py`, `services/commercial_service.py`, `retention_policy.py`, requisitos/lock y plantillas env, `backup_commercial.py` y `backup_runtime.py`; fixtures históricos/E2E y cleanup de `browser_e2e.py`, provisionador `verify_clean_install.py`; proxy Nginx y guía operativa. Ningún Markdown académico, índice, VRM, CSS público ni precio operativo fue editado en esta fase.

## Pendientes antes de comercializar

Crear el superadmin real y usuarios nominales mediante proceso institucional; revisar asignaciones de roles, especialmente lectura de PII. Configurar y probar HTTPS/ACL/backup cifrado/restore en el servidor final; no se certificó Nginx/TLS real desde este entorno. Retirar Bearer después de migrar herramientas. La protección contra fuerza bruta está encapsulada en memoria para una sola instancia y no sobrevive reinicios; almacenamiento distribuido queda fuera de esta fase. No hay MFA, recuperación automática por email, detección de contraseñas filtradas ni reautenticación adicional para operaciones sensibles. El cambio de contraseña propio requiere sesión válida y CSRF; la recuperación privilegiada pertenece a superadmin. No se implementó panel completo ni Fase 9B.
