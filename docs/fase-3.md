# Fase 3: sesiones y persistencia operativa

## Arquitectura

`commercial.sqlite3` conserva exclusivamente configuración comercial. La nueva
`storage/runtime.sqlite3` contiene sesiones y operación conversacional/comercial.
No hay SQL operativo en `server.py`. `SessionManager` usa el contrato
`RuntimeRepository` y `SQLiteRuntimeRepository`; `OperationalService` coordina
prospectos, archivos y comprobantes. Las reglas de consentimiento, acciones y
tarifas permanecen en los servicios de las fases anteriores.

Tablas operativas:

| Tabla | Contenido |
| --- | --- |
| sessions | ID, hash de credencial, fechas, expiración, operación activa/lease, persona, etapa, lead_id, medios mostrados |
| turns | Pares usuario/asistente completos, request_id único y fecha |
| leads | ID generado, sesión opcional, nombre, WhatsApp normalizado, programa, modalidad, origen, notas y fechas |
| vouchers | ID generado, sesión/lead, programa/modalidad/turno/concepto, importe y moneda oficiales, campaña/ID, referencia privada, estado y fechas |
| operations | Clave de idempotencia por sesión/tipo, huella, resultado mínimo y fecha |

SQLite emplea WAL, claves foráneas, `synchronous=FULL`, locking de cinco segundos
y transacciones `BEGIN IMMEDIATE`, con rollback incluso ante cancelación. No se
almacenan audio, Base64, payloads del proveedor ni credenciales en texto claro.
Los IDs comerciales son instantáneas históricas: no necesitan una FK entre bases.

## Identidad y protocolo

`POST /api/session` acepta `{ "session_id": "opcional" }` y devuelve un ID y una
credencial opaca de 256 bits. Un ID existente exige su `X-Session-Token`; conocer
el ID nunca autoriza acceso. La respuesta tiene `Cache-Control: no-store`.
El navegador guarda ID y token en `sessionStorage`, separados del token admin.
No se introdujeron cookies, login ni autorización comercial por nombre/teléfono.

`/chat`, `/chat/stream`, reset y cancelación exigen la credencial. Los formularios
que incluyen sesión también la exigen. Por compatibilidad, los formularios sin
sesión pueden crear registros **sin asociación**; no consultan sesiones por teléfono
ni asocian un `lead_id` proporcionado sin credencial. El frontend actualizado siempre
envía sesión y credencial. Integraciones antiguas de chat deben adoptar bootstrap.

SSE conserva texto → audio por oración → acciones → done; todos sus eventos
incluyen el mismo `request_id` generado por backend. JSON también lo incluye.
El header `X-Operation-ID` identifica el stream desde su apertura. El ID de
correlación HTTP de Fase 2 sigue siendo independiente. CORS permite explícitamente
`X-Session-Token` e `Idempotency-Key` y expone `X-Operation-ID`.

## Concurrencia y cancelación

Una reserva transaccional permite como máximo una interacción vigente por sesión.
Una segunda consulta recibe 409. `replace_active: true` invalida la anterior antes
de reservar otra. Sesiones distintas pueden generar respuestas simultáneamente.
El snapshot de historial se obtiene después de reservar, evitando lecturas viejas.

Cada emisión SSE y cada escritura final comprueba propiedad, expiración y lease.
Un request antiguo no puede modificar historial ni liberar una reserva nueva.
El registro local de tareas permite detener Groq/TTS inmediatamente en el mismo
proceso. El stream del proveedor se cierra y la liberación condicional se protege
frente a cancelación del task group de Starlette. Sólo se guarda un turno cuando
su respuesta completa está preparada; los streams fallidos no guardan texto parcial.

`POST /api/session/cancel` acepta `session_id` y opcional `active_request_id`.
Con ID, una cancelación tardía no cancela una operación posterior. Sin ID, cancela
la interacción vigente. El cliente usa ID cuando lo conoce y aborta su conexión;
una consulta nueva solicita reemplazo explícito. Generaciones locales descartan
eventos, audio y callbacks antiguos. Los bytes ya entregados por la red no pueden
revocarse; el cliente impide ejecutar sus acciones tras cancelación/reemplazo.

En un reinicio abrupto no se recuperan requests en curso: la reserva huérfana vence
en 120 segundos como máximo. Historial completo y vínculo comercial sí sobreviven.
Otro proceso comprueba la propiedad persistida, pero no puede cancelar una tarea
del proceso anterior inmediatamente. Para esta etapa, despliegue recomendado con
**un worker**: también conserva los límites en memoria de Fase 2. Coordinación
distribuida y cancelación entre procesos quedan para una futura capa Redis.

## Límites y expiración

| Variable | Default | Uso |
| --- | --- | --- |
| RUNTIME_DATABASE_PATH | storage/runtime.sqlite3 | Ruta privada, nunca dentro de static |
| SESSION_TTL_SECONDS | 1800 | Inactividad, renovada por interacción/formulario/reset |
| SESSION_LIFETIME_SECONDS | 86400 | Vida absoluta de credencial/sesión |
| SESSION_CLEANUP_INTERVAL | 60 | Limpieza periódica |
| SESSION_PERSISTED_TURNS | 12 | Máximo de pares completos en disco |
| SESSION_HISTORY_MAX_CHARS | 24000 | Límite aproximado de caracteres del historial |
| SESSION_MAX_HISTORY_TURNS | 4 | Últimos pares enviados al modelo |
| SESSION_REQUEST_LEASE_SECONDS | 120 | Reserva máxima; debe superar STREAM_TIMEOUT |

La expiración se comprueba en cada operación, sin esperar al cleanup. La limpieza
revoca el token, cancela tareas y borra turnos/medios. Conserva sesiones mínimas
referenciadas por leads/vouchers; elimina sesiones sin datos comerciales y claves
de chat/reset/cancel expiradas. No recicla una sesión con datos comerciales para
otra persona. El frontend crea una identidad nueva cuando la anterior expiró.

## Prospectos, comprobantes, embudo e idempotencia

El lead se guarda y se asigna a `session.lead_id` en la misma transacción. Una sesión
representa un prospecto: no permite sustituirlo silenciosamente por otro. Cambiar
de persona requiere una identidad nueva; el reset conversacional no cambia dueño.

El voucher revalida la tarifa antes y después de validar la imagen, conservando
los controles de Fase 2. `free` y `pending` no admiten upload. El importe efectivo
y campaña salen de PricingService, nunca del modelo ni del RAG. La asociación
capturada al empezar se vuelve a comprobar al guardar; discrepancias de lead,
programa o modalidad se rechazan. Imagen y registro reciben IDs del servidor. Un
fallo de transacción elimina la imagen recién escrita. No se generan nuevos JSON
de metadata: SQLite es la fuente primaria. Los JSON históricos existentes no se
eliminan ni se importan con asociaciones inferidas; requieren migración revisada.

Estados de comprobante: `pending_review`, `approved`, `rejected`, restringidos por
la base. La API de upload sólo crea `pending_review`. La revisión administrativa
no se implementa en esta fase y recibir un archivo no confirma matrícula pagada.

Eventos del backend definen el embudo:

- respuesta completa: `discovery` → `value`;
- formulario válido: `discovery`/`value` → `lead_captured`;
- oferta de pago autorizada o comprobante vinculado: `lead_captured` → `closing`.

El modelo no puede enviar una etapa. Respuestas posteriores no retroceden estados.
Reset limpia conversación/medios y vuelve a discovery si no hay lead, o a
lead_captured si hay lead. Conserva registros comerciales y referencias históricas.

El cliente envía `Idempotency-Key` (1–128 caracteres, letras/dígitos/guion/underscore).
Mismo tipo/sesión/clave y contenido devuelve el mismo lead/voucher. Contenido
distinto con esa clave devuelve 409. Las transacciones resuelven también reintentos
simultáneos, escribiendo un único archivo. Cada reintento de upload vuelve a
revalidar la tarifa y el archivo. Las claves comerciales sobreviven al reinicio.
Sin clave, integraciones heredadas no tienen garantía de deduplicación.

Chat usa `idempotency_key` en JSON; una clave ya reservada devuelve 409 y nunca
regenera acciones sensibles. No se almacena audio para replay. Cancelación y reset
aceptan `Idempotency-Key`; repetir reset no borra un turno nuevo. El reset también
acepta la clave del contrato JSON de chat. Los formularios mantienen su clave en
reintentos sin cambios y bloquean doble envío mientras la petición está activa.

## Privacidad, readiness y backup

Datos personales persistidos: nombre, WhatsApp, notas del lead y texto limitado de
la conversación. Vouchers contienen referencia de imagen, metadatos comerciales
y vínculo al prospecto; las imágenes pueden incluir información personal. Todo
queda fuera de static/Git. Logs conservan únicamente identificadores técnicos y
datos sanitizados de Fase 2. No se añaden logs de teléfonos, tokens o prompts.
La retención/eliminación comercial debe implementarse explícitamente mediante
el repositorio en una fase posterior; reset/cleanup nunca son una eliminación legal.

`/health/ready` añade `checks.runtime`: integridad, FK y presencia de tablas de
sesiones/leads/vouchers/operaciones, sin IDs, rutas o datos personales públicos.

Backup comercial: el script de Fase 2 se conserva. Backup operativo independiente:

```powershell
backend/venv/Scripts/python.exe -B backend/backup_runtime.py
```

También acepta `--database`, `--vouchers` y `--output`. Usa SQLite Backup API para
la base abierta, luego copia sólo imágenes del snapshot. Las imágenes son
inmutables; un manifiesto incluye hashes de base y archivos. Falla si falta una
imagen, el destino existe o es público. No publica una copia incompleta. Ambos
backups contienen información privada y necesitan permisos restringidos y cifrado
al transportarlos. Los archivos JSON anteriores requieren respaldo separado hasta
revisar su migración. No copiar ordinariamente bases abiertas ni sólo su archivo WAL.

Restauración: detener backend, verificar hashes y `PRAGMA quick_check` /
`foreign_key_check` en una copia, preparar una ubicación privada nueva con la base
e imágenes del mismo paquete, ajustar las rutas y reiniciar. Conservar el estado
anterior como rollback; no superponer archivos WAL/SHM antiguos ni sobrescribir
la base activa. Ninguna prueba ejecuta una restauración destructiva.

## Verificación y pendientes

Suite anterior de Fases 1–2, tests HTTP con credenciales reales, concurrencia SQLite
desde conexiones independientes, cierre Groq/TTS, historial, expiración, leases,
reinicio, idempotencia concurrente, asociaciones, rollback, embudo y backup.
Frontend cubre generaciones, IDs, cancelación de audio/acciones y reemplazo;
las matrices web/kiosk e info/sales anteriores se conservan.

Sin login/panel/Redis/PostgreSQL/CRM/ChromaDB. No hubo cambios de estilos/avatar.
Pendientes operativos: ensayo en navegador con proveedores reales y desconexión
de red, política de retención comercial, migración revisada de JSON históricos,
programación externa de backups y coordinación distribuida cuando se escale.
