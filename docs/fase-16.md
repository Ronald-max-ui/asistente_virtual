# Fase 1.6: configuración comercial persistente

La fuente primaria es `backend/storage/commercial.sqlite3`. `PricingService` lee
una instantánea transaccional en cada consulta, valida sus registros y resuelve
el precio vigente con la fecha local de Lima. No lee importes del RAG, del modelo,
de los sidecars ni de un precio almacenado en frontend. No existe respaldo automático
al JSON: una base vacía o inválida impide obtener una tarifa cobrable.

## Arquitectura y archivos

- `backend/persistence/models.py`: DTO administrativos estrictos; reutiliza los
  estados, importes decimales y promociones ya validados en Fase 1.5.
- `backend/persistence/repository.py`: contratos de unidad de trabajo/repositorio,
  reemplazables por un adaptador PostgreSQL sin cambiar reglas comerciales.
- `backend/persistence/sqlite_repository.py`: todo el SQL, transacciones, referencias,
  unicidad y auditoría. Las columnas relacionales son autoritativas; el JSON interno
  conserva campos extensibles del DTO. Promociones se leen de su tabla.
- `backend/services/commercial_service.py`: creación/actualización y validación de
  programas, precios, campañas, selección de avatares y settings.
- `backend/services/pricing_service.py`: consulta vigente y cotización autorizada.
  Se conserva el lector legado **sólo con una ruta explícita**, para herramientas
  de compatibilidad/pruebas; la instancia de producción usa el repositorio.
- `backend/services/avatar_service.py`: proyección pública mínima.
- `backend/commercial_runtime.py` y `backend/config.py`: ruta y credencial del backend.
- `backend/api/commercial.py`: rutas separadas. `server.py` sólo incluye los routers;
  ActionService y ConsentService conservan sus validaciones aprobadas.
- `backend/migrate_commercial.py`: importación explícita, sin depender de Groq/ChromaDB.
- `avatar-kiosk/src/api/publicConfig.js` y `src/avatar/loader.js`: consulta del avatar
  seleccionado; ya no cargan una ruta VRM fija. El diseño y postura se conservan.
- `backend/tests/test_phase16.py`, `tests/test_support.py`, pruebas previas adaptadas
  a una base temporal y `avatar-kiosk/tests/publicConfig.test.js`: regresiones.
- `.gitignore`: excluye la copia del VRM del backend. La base ya estaba excluida
  mediante `backend/storage/`. Los binarios se provisionan fuera del código.

No se modifican los JSON ni el conocimiento institucional en esta fase. Sus enlaces
comerciales antiguos y la limpieza definitiva de conocimiento quedan para Fase 4.

## Tablas

| Tabla | Función |
|---|---|
| programs | Programa/carrera/curso, nombre, tipo, habilitación y archivo académico |
| program_aliases | Alias normalizados únicos entre programas |
| modalities | Modalidades propias por programa |
| shifts | Turnos propios por programa |
| prices | Programa + modalidad + turno + concepto, estado, monto exacto, moneda y campaña opcional |
| campaigns | Nombre, fechas inclusivas, habilitación y notas administrativas |
| promotions | Metadatos/promociones asociados a una tarifa, sin cálculo implícito |
| avatars | Registro de recursos locales VRM, habilitación y selección única |
| settings | Configuración general extensible en claves tipadas |
| configuration_migrations | Huella y marca de importación para no sobrescribir cambios |

Registros comerciales, promociones, avatares y settings tienen `created_at`,
`updated_at`, `created_by` y `updated_by`. Variantes/alias pertenecen al programa
y su auditoría se refleja en el registro padre. Actor inicial `migration`;
actor de API `admin-token`, todavía sin atribución a una persona.

## Inicializar y migrar

Desde la raíz:

```powershell
& backend/venv/Scripts/python.exe -B backend/migrate_commercial.py
& backend/venv/Scripts/python.exe -B backend/validate_pricing.py
```

Variables de entorno opcionales: `COMMERCIAL_DB_PATH` (por defecto
`storage/commercial.sqlite3`, relativo a `backend`, nunca al cwd) y
`ADMIN_API_TOKEN` (secreto de backend, nunca `VITE_*`, nunca en el repositorio).
La migración admite `--database RUTA`, `--knowledge RUTA` y `--skip-avatar-copy`
para validaciones con assets provisionados aparte. No es una sincronización.

Se importaron **6 programas, 42 tarifas, 0 campañas con fechas y 0 rechazos**:
seis inscripciones activas de S/ 80 y 36 tarifas pendientes. No se activaron
valores académicos antiguos. `confirmacion_inicial` se conserva como etiqueta
de procedencia del precio base: al no tener fechas, no se inventa una campaña.
Una segunda ejecución omite los seis programas sin duplicar ni sobrescribir
ediciones. Un programa importado se valida íntegramente y se confirma o revierte
en una transacción. Un rechazo en un programa no revierte otros ya importados:
revisar el informe y corregir los rechazos antes de operar.

Los seis `*.pricing.json` se conservan como compatibilidad/migración temporal.
Cambiar esos archivos **no cambia la tarifa runtime ni reaplica la importación**.
Una base existente sin marca de importación para un programa se rechaza, para
evitar sobrescribir datos administrados. Las ventanas completas en sidecars se
convierten en campañas; ventanas abiertas quedan como vigencia de precio base.
No se fabrican precios base de respaldo para una oferta que no los tenga.

Se copia el VRM existente a `backend/static/avatars/lia_original.vrm` y se registra
`lia_original`. La copia conserva el archivo original y no es un cambio visual.
Un despliegue nuevo debe migrar/provisionar assets antes de servir el frontend.
Respaldar y preservar la base en un volumen; no borrar storage al desplegar.

## Reglas de precio y campaña

- `active`: monto positivo confirmado; `free`: cero confirmado; `pending`: null;
  `inactive`: no participa en la resolución. Null jamás se convierte en cero.
- `amount` se envía como cadena decimal exacta (o entero); no float ni redondeos
  implícitos. Moneda de tres letras; el flujo Yape aprobado sólo cobra PEN positivo.
- Conceptos actuales: `inscripcion`, `matricula`, `mensualidad`,
  `mensualidad_contado`, `pago_contado`, `ciclo_completo`, `descuento`.
- `modality: null` / `shift: null` son cobertura de todas las variantes de ese
  programa, no un precio global compartido con otros programas.
- Precio base: `campaign_id: null`. Oferta: `campaign_id` del registro de campaña.
  Las fechas de una oferta pertenecen exclusivamente a esa campaña. Su alcance
  se define mediante las filas de precio asociadas, una por combinación necesaria.
- Una oferta vigente sustituye temporalmente el precio base. Antes/después de su
  intervalo aplica el base. Una oferta pending vigente impide cobrar, aunque exista
  un base confirmado: no se omite silenciosamente una configuración pendiente.
- Dos precios base o dos ofertas con concepto/programa/variantes intersectados y
  fechas intersectadas se rechazan con los IDs en conflicto. Se revisa también al
  editar fechas/habilitar campañas. Inicio/fin son inclusivos. Escrituras concurrentes
  se serializan antes de validar: no pueden confirmar dos ofertas incompatibles.
- Si falta variante y hay más de una resolución posible (incluyendo una combinación
  sin precio), se solicita modalidad/turno y se bloquea el cobro. No se adivina.
- Los descuentos porcentuales/fijos son metadatos, no autorización para restar
  importes automáticamente. Registrar el importe final confirmado de la oferta.

Ejemplo **ilustrativo**, no activado por la migración:

```json
{"id":"octubre_2026","name":"Octubre","starts_on":"2026-10-01","ends_on":"2026-10-31","enabled":true}
```

```json
{"id":"inscripcion_octubre_gastronomia","program":"gastronomia","modality":"presencial","shift":null,"concept":"inscripcion","amount":"0","currency":"PEN","status":"free","campaign_id":"octubre_2026"}
```

El LLM conserva únicamente identificadores; esquema → ActionService → ConsentService
→ PricingService → acción final. JSON/SSE y comprobantes siguen revalidando la tarifa.

## API

| Método y ruta | Uso |
|---|---|
| GET `/api/config` | Público: nombre, avatar seleccionado y claves visuales públicas |
| GET `/api/admin/{programs,prices,campaigns,avatars}` | Listado administrativo |
| GET `/api/admin/{recurso}/{id}` | Registro con auditoría |
| POST `/api/admin/{recurso}` | Crear; ID existente devuelve conflicto |
| PUT `/api/admin/{recurso}/{id}` | Actualizar registro completo; ID debe coincidir |
| POST `/api/admin/avatars/{id}/activate` | Selección atómica, desactiva el anterior |
| GET/PUT `/api/admin/settings` | Leer/reemplazar settings tipados |

Modalidades, turnos y alias se editan dentro del programa; promociones dentro del
precio. Para desactivar se actualiza `enabled`, `status` o `active` según recurso;
no hay eliminación física que rompa referencias. Para dividir un precio comodín,
desactivar primero la fila base y registrar los precios específicos autorizados.
Las actualizaciones parciales de listas no se fusionan: enviar el registro completo
sin los campos de auditoría, que el servidor controla.

Toda ruta admin requiere `Authorization: Bearer <ADMIN_API_TOKEN>`. Sin token
configurado devuelve 503; sin credencial válida, 401. No es el login definitivo:
proteger el acceso administrativo en infraestructura y sustituir el token compartido
por identidad/roles en la fase de seguridad. Errores de esquema: 422; conflictos:
409; registro inexistente: 404. OpenAPI describe los DTO estrictos disponibles.

`/api/config` nunca devuelve campañas, tarifas históricas, notas, auditoría,
configuración interna de voz ni extensiones. Avatares admiten únicamente rutas
locales `/static/avatars/<nombre>.vrm`; provisionar el archivo antes de seleccionarlo.
La subida/validación de assets y URLs externas queda fuera de esta fase. Una selección
deshabilitada se rechaza; para desactivar el actual debe seleccionarse otro antes.
Una base todavía sin inicializar deja `avatar: null` y el frontend muestra un error
controlado. El cambio se observa al cargar de nuevo el frontend;
no hay reemplazo en caliente de una escena 3D abierta ni build necesario.

## Validación y límites

```powershell
& backend/venv/Scripts/python.exe -B -m unittest discover -s backend/tests -v
cd avatar-kiosk
npm test
npm run build
```

Pruebas con bases temporales y Groq/RAG/TTS simulados: migración, idempotencia,
aislamiento por programa/modalidad/turno, estados, campañas futuras/vencidas,
límites inclusivos, conflictos concurrentes, rollback, promociones, API protegida,
selección única de avatar, proyección pública, cambios observados por JSON/SSE,
montos del modelo ignorados y comprobantes bloqueados para free/pending. Se conservan
las regresiones web/kiosk, info/sales, consentimiento y orden audio/acciones.

Pendientes expresos: panel visual, login/roles, backups automatizados, historial
inmutable de cambios comerciales, subida de assets, PostgreSQL y fases posteriores.
SQLite es apropiado para esta instancia local; revisar concurrencia/operación antes
de escalar. No se ha hecho una prueba visual real del avatar ni una prueba con servicios
externos en vivo. La advertencia de tamaño del bundle corresponde a la futura Fase 7.

Resultado de cierre: **66 pruebas backend y 20 frontend aprobadas**, incluidas las
regresiones anteriores. `npm run build` correcto (bundle 780.87 kB; advertencia
de tamaño mayor a 500 kB), 33 archivos Python analizados por AST, sintaxis de todos
los JavaScript de `src`/`tests` correcta y `git diff --check` sin errores. Migración
real e idempotencia validadas; SHA-256 del VRM copiado igual al original.
