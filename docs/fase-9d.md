# Fase 9D — Operación comercial

## Arquitectura y modelo

La UI de `/admin/` llama a `/api/admin/operations`; los DTO tipados validan entradas, `LeadOperationsService` verifica responsables/permisos contextuales y `LeadOperationsRepository` concentra SQL, transacciones y control de revisión. Captura pública, sesiones, pricing, campañas, voz y acciones conservan sus servicios actuales. No se envían mensajes a terceros.

`runtime.sqlite3` pasa de esquema 2 a 3 mediante migración aditiva e idempotente:

| Tabla | Responsabilidad |
|---|---|
| `leads` | Datos originales capturados por Lía, sin sobrescritura administrativa |
| `lead_tracking` | Estado administrativo, asignación, motivo de pérdida, conversión explícita, teléfono normalizado y revisión |
| `lead_activity` | Timeline inmutable con autor, fecha y notas/actividades de texto plano |
| `lead_tasks` | Seguimiento simple con responsable, vencimiento, tipo y estado |
| `vouchers` / `voucher_reviews` | Comprobante histórico y revisión administrativa existente |
| `operations` / `admin_audit_log` | Idempotencia y auditoría existente, ampliada con eventos operativos |

Cada lead existente recibe `new`, sin responsable, sin conversión y un evento de creación con su fecha original. La migración no interpreta el funnel como resultado comercial ni cambia sus datos capturados. Repetir inicialización no duplica eventos. Usuarios/RBAC siguen en la base comercial separada; la referencia entre ambas se valida en servicio, sin FK entre archivos SQLite.

## Estados y transiciones

`new` (Nuevo), `contacted` (Contactado), `interested` (Interesado), `follow_up` (Seguimiento), `enrollment_in_progress` (Matrícula en proceso), `converted` (Convertido), `lost` (Perdido).

Los estados no terminales permiten saltos razonables hacia los demás, salvo volver a Nuevo. Perdido permite reabrir como Contactado, Interesado, Seguimiento o Matrícula en proceso. Convertido es terminal en esta fase; una corrección requerirá un flujo explícito futuro. Guardar el mismo estado permite actualizar asignación. El backend devuelve los estados siguientes autorizados a la UI.

Motivos opcionales de pérdida: precio, no responde, otra institución, horario, modalidad, ya no interesado y otro. Otro requiere nota al seleccionarse; una modificación posterior queda como nueva actividad. No se interpreta HTML.

`discovery/value/lead_captured/closing` siguen siendo funnel conversacional independiente. Aprobar un voucher no convierte al prospecto. Convertir exige operación explícita de un usuario autorizado; conserva autor y fecha. No crea alumno ni matrícula académica.

## Asignación, notas y tareas

Sólo usuarios habilitados con `leads.write` pueden recibir asignación. Se conserva fecha de asignación. Mis prospectos filtra por el usuario actual; no se impone aislamiento por propietario. Notas, llamadas y WhatsApp manual son append-only; una corrección se registra como otra actividad. WhatsApp manual sólo documenta una gestión externa.

Tareas: `pending → completed` o `pending → cancelled`, sin recurrencia ni notificaciones. Vencimientos llegan con offset obligatorio y se muestran en America/Lima (UTC−05:00). Próximo seguimiento es el menor vencimiento pendiente. Hoy cuenta prospectos distintos con tarea pendiente hoy; atrasados son prospectos distintos con tarea pendiente anterior al instante actual. Pueden pertenecer a ambas categorías.

La ficha conserva identidad capturada, origen, fecha, modalidad, funnel, responsable, estado, próximos seguimientos, tareas y timeline. No incorpora historial conversacional. Muestra hasta 100 actividades recientes, con historial paginado adicional; tareas priorizan pendientes, con máximo 100 por ficha. Comprobantes sólo se incluyen con `vouchers.read`; imagen mediante endpoint protegido existente. Importe mostrado es el snapshot del upload, nunca el precio comercial actual.

Posibles duplicados se señalan por teléfono normalizado (dígitos, prefijo peruano 51 reconocido); no se unen ni eliminan registros automáticamente.

## API y concurrencia

| Endpoint relativo a `/api/admin/operations` | Permiso |
|---|---|
| `POST /leads/search` | leads.read |
| `GET /assignees` | leads.read |
| `GET /leads/{id}` | leads.read |
| `GET /leads/{id}/activities` | leads.read |
| `PUT /leads/{id}` | leads.write |
| `POST /leads/{id}/activities` | leads.write |
| `POST /leads/{id}/tasks` | leads.write |
| `POST /leads/{id}/tasks/{task_id}` | leads.write |
| `GET /analytics?period=7d|30d|month` | leads.read |
| `GET /voucher-counts` | vouchers.read |
| `POST /leads/export` | leads.export |

Se mantienen las rutas anteriores de lectura y revisión de comprobantes. Métodos modificadores requieren sesión/CSRF/Origin y `If-Match` + `Idempotency-Key`. Toda mutación verifica la revisión del lead en la misma transacción `BEGIN IMMEDIATE` que actualiza estado, evento y auditoría. Una revisión vieja devuelve 409; un reintento exacto con la misma clave devuelve su resultado sin duplicar. Clave reutilizada para otro contenido devuelve conflicto. Actualizar tareas/notas también incrementa la revisión del lead.

Búsquedas por nombre/teléfono viajan en cuerpo POST, nunca querystrings. Filtros: estado, programa, modalidad, responsable, fechas y accesos rápidos. Se conserva offset para volumen inicial: páginas de 20, límite API 100, offset máximo 10000. No se descargan todos los leads para filtrar. CSV filtra en backend, máximo 1000 filas, sin notas/timeline/conversación. Celdas peligrosas (=,+,-,@, tab/CR/LF) se prefijan con apóstrofo. Exportación auditada sin copiar filtros personales.

RBAC: admisiones gana únicamente `leads.write`; solo_lectura mantiene lectura; superadmin y administrador pueden exportar. Administrador recibe gestión de leads. Revisor de pagos mantiene permisos existentes; ver/revisar vouchers sigue requiriendo sus permisos. No se conceden permisos de usuarios, settings o precios a admisiones.

## Dashboard y analítica

Tarjetas reales: nuevos hoy, nuevos 7 días, seguimientos pendientes hoy, atrasados, creados en periodo y conversiones registradas. La tarjeta de comprobantes pendientes conserva su permiso específico. Tablas ligeras por programa, origen y estado actual de leads creados en periodo, más conversiones registradas por programa.

7 días comprende hoy y los seis días anteriores; 30 días hoy y los 29 anteriores; este mes desde día 1, en Lima. Creaciones se filtran por `created_at`; conversiones por `converted_at`. No se muestra tasa de conversión, porque no se definió una cohorte institucional. Contadores de voucher son por estado actual, sin alterar sus transiciones terminales.

## Auditoría, índices y privacidad

Auditoría registra cambios de tracking, nota/llamada/WhatsApp manual, creación/completado/cancelación de tarea, conversión, exportación y revisión. Snapshots permiten sólo estado, IDs de responsables, motivo estructurado, revisión, fechas y metadatos de tareas. Excluyen nombre, teléfono y contenido de nota. Timeline sí contiene texto administrativo y por ello es PII sujeto a `leads.read`. La revisión del voucher mantiene su auditoría previa.

Índices nuevos: estado, responsable, teléfono normalizado, creación/programa del lead, timeline por lead/fecha, tareas por estado/vencimiento y lead, vouchers por estado/fecha y lead. Las pruebas verifican query plans para estado y vencimiento. No se cambia SQLite/WAL ni se añade almacenamiento distribuido.

## Backup y retención

`backup_runtime.py` ya obtiene snapshot consistente vía SQLite Backup API y copia vouchers referenciados; incorpora automáticamente las tablas nuevas. `verify_runtime_backup.py <directorio>` verifica read-only hash, integridad/FK, tablas operativas, tracking de cada lead y archivos del manifiesto. No restaura ni modifica la fuente. Usuarios y configuración conservan backup comercial/branding independiente.

Estados y asignaciones son registros comerciales; notas/timeline/tareas contienen potencial PII. `RETENTION_LEAD_ACTIVITY_DAYS` y `RETENTION_LEAD_TASKS_DAYS` son propuestas opcionales; no ejecutan borrado. No confundir reset conversacional con eliminación comercial. Respaldos/logs tienen su clasificación anterior; proteger acceso, cifrar fuera del disco y verificar regularmente. No se introduce retención automática.

## Archivos afectados

Nuevos: DTO de operaciones, esquema/adaptador runtime de tracking, servicio/API operativa, módulo UI de prospectos/analítica, pruebas 9D, runner comercial y verificador runtime de backups. Modificados: inicialización/captura/revisión runtime, RBAC, allowlist de auditoría, registro router, errores HTTP, cliente admin, Dashboard/Prospectos/Comprobantes/CSS, E2E Chrome, instalador limpio, retención y plantillas de entorno. Ningún archivo académico ni precio ni índice oficial cambia en esta fase.

## Validación y pendientes

Los resultados finales se registran en los JSON `fase-9d-*` de esta carpeta. Se ejecutan suites backend/frontend, E2E administrativo y público Chrome, E2E comercial/CSV/dashboard/backup, concurrencia real en SQLite y dos identidades HTTP, instalación limpia, producción, evaluación/check RAG, sintaxis, build, escaneo de secretos y diff check.

Pendientes de operación: prueba prolongada en hardware kiosk/tablet/móvil real; definir cohorte de conversión y proceso de corrección de convertidos; paginación de tareas/vouchers si un lead supera 100; responsables actualmente listados hasta 100 usuarios; exportación de más de 1000 y offset mayor de 10000 requieren diseño explícito. No hay merge automático, calendario completo, workers ni integraciones externas. Fase 10 no iniciada.

## Resultados finales

249 tests backend y 63 frontend aprobados. E2E Chrome administrativo: 56 comprobaciones; público: 18 comprobaciones en tres rondas. Comercial: 11 casos; concurrencia: 2 casos. Instalación limpia: 13 pasos, readiness ready. Producción: 9 verificaciones. RAG: 12 consultas, índice ready. Backup runtime verificado read-only: 1 lead, 1 tracking, 9 actividades, 1 tarea y 1 voucher; backup comercial incluido en verificación de producción. Sintaxis: 133 archivos Python y 36 JavaScript. Build aprobado, sin secretos detectados y diff check limpio. Sin regresiones pendientes detectadas; permanece advertencia de tamaño del chunk Three.js. Resumen reproducible: [fase-9d-validation.json](fase-9d-validation.json).
