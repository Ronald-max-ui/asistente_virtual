# Fase 4: limpieza y normalización del conocimiento institucional

Revisión del 7 de octubre de 2026. Alcance: los nueve Markdown de
`backend/knowledge`, un validador y pruebas. No se modifica la configuración
comercial, las bases, los JSON de migración, los servicios de negocio, el
frontend ni el índice vectorial. No se inicia la Fase 5.

## Inventario y decisiones de contenido

La tabla recoge el inventario comunicado antes de editar. Los valores de origen
no son una oferta vigente. El texto completo anterior y sus hashes SHA-256 se
conservan en [fase-4-fuentes-originales.md](fase-4-fuentes-originales.md), fuera de
`backend/knowledge`; ese archivo histórico no debe indexarse.

Las rutas de la tabla son relativas a `backend/knowledge/`.

| Archivo | Dato | Valor anterior | Conflicto o riesgo | Fuente | Acción aplicada |
|---|---|---|---|---|---|
| `01_institucional/general.md` | Institución, sede y contacto | Licenciamiento MINEDU; Cusco; Bellavista 130/140; oficina Garcilaso 304; teléfono 949 355 435 | Repetidos en FAQ; oficina informativa podía confundirse con sede de clases | Estática, con revisión institucional | Fuente principal de institución/contacto; oficina diferenciada |
| `01_institucional/general.md` | Atención | Lunes a viernes, 08:00–13:00 y 14:00–19:00 | No son horarios de clases; requieren actualización si cambia la atención | Estable operativa | Se conservan exclusivamente como atención |
| `01_institucional/general.md` | Oferta y duración | Cuatro carreras, dos cursos; duraciones repetidas | Duplicación con fichas | Estática académica | Oferta enlazada; duración sólo en cada ficha |
| `01_institucional/general.md` | Inicio de clases | Carreras 5/10/2026; cursos 15 de noviembre sin año en el cuerpo | Fechas temporales; carreras ya iniciadas al revisar; curso incompleto | Temporal/dudosa | Se retiran del corpus permanente; valores archivados para revisión |
| `01_institucional/general.md` | Plataformas y beneficios | Meet en vivo/grabación; Q10; carnet, empleo, convenios, inglés/ofimática donde aplique | FAQ atribuía a Q10 almacenamiento de grabaciones sin fuente suficiente | Estática condicionada | Una fuente institucional; beneficios condicionados; sin atribución no confirmada |
| `01_institucional/admision_y_pagos.md` | Documentación | DNI inicial; regularización en 15 días; DNI, certificado, foto, partida | FAQ confundía iniciar trámite con reservar; lista general no confirmada para todos los cursos | Estática institucional | Fuente general para carreras; cursos remiten a ficha propia |
| `01_institucional/admision_y_pagos.md` | Reserva y comprobante | Reserva con matrícula; asesor confirma tras imagen | DNI solo no confirma reserva; recibir imagen no significa pago aprobado | Estática procedimental + tarifa dinámica | Reserva validada por admisión; comprobante pendiente de revisión; gratuidad efectiva no exige cobro |
| `01_institucional/admision_y_pagos.md` | Tarifas | Referencias a JSON por programa, sin importes | Fuente obsoleta desde Fase 1.6 | Dinámica: base comercial/PricingService | Referencia neutral al sistema vigente; pendiente no equivale a gratuito |
| `01_institucional/admision_y_pagos.md` | Canales | Yape 994 773 335; BBVA CCI 011-201-000100038687-18; BCP CCI 002-28500720927504553 | Repetidos en FAQ; necesitan ratificación si cambian los canales | Estable operativa, a ratificar | Se conservan una sola vez; no se añaden canales ni conciliación automática |
| `01_institucional/admision_y_pagos.md` | Continuidad | Mensualidades conservadas con continuidad; interrupción superior a un año implica condiciones vigentes | No existe precio individual histórico implementado para esta política | Estática documental, aplicación por confirmar | Se conserva con confirmación por admisión; nunca permite sobrescribir tarifa vigente |
| `02_carreras/administracion.md` | Formación | Gestión empresarial; casos, simulaciones y proyectos; campo laboral y título | Sin conflicto académico detectado | Estática | Se conserva y organiza por secciones |
| `02_carreras/administracion.md` | Modalidades/horarios | Presencial mañana; virtual noche; lunes a viernes 07:00–11:30 / 18:30–21:30 | Base habilita más turnos pero no determina combinaciones ni horarios | Modalidades aprobadas en base; horario por periodo | Se conservan presencial/virtual; horario queda pendiente por periodo |
| `02_carreras/contabilidad.md` | Formación | Software, casos, simulación, certificaciones progresivas; auditoría y campo financiero | Sin conflicto académico detectado | Estática | Se conserva; requisitos generales enlazados |
| `02_carreras/contabilidad.md` | Modalidades/horarios | Presencial mañana/tarde según ciclo; virtual noche; horas de mañana/noche como Administración | Turno tarde sin horario; turnos de base más amplios | Modalidades aprobadas en base; horario por periodo | Se conservan presencial/virtual; sin inventar combinaciones ni horas |
| `02_carreras/gastronomia.md` | Formación y materiales | Cocina práctica; hasta 25 estudiantes; tabla/cuchillo personal; uniforme, insumos y materiales al matricularse | Beneficios no deben perder su condición de matrícula | Estática específica | Contenido y condiciones conservados |
| `02_carreras/gastronomia.md` | Modalidad/horarios/sábado | Sólo presencial; mañana/noche L–V; sábado 08:00–18:30 | Horario por periodo; sábado no debe generalizarse | Modalidad aprobada + regla oficial específica | Sólo presencial; puede tener clases/actividades los sábados; sin hora temporal |
| `02_carreras/turismo.md` | Formación | Guía Oficial de Turismo; inglés/japonés; salidas de campo; certificaciones | No generalizar japonés a otras carreras | Estática específica | Contenido conservado en su ficha |
| `02_carreras/turismo.md` | Modalidades/horarios | Presencial mañana/tarde según ciclo; virtual noche | Mismo conflicto de disponibilidad que Contabilidad | Modalidades aprobadas; horario por periodo | Presencial/virtual; confirmación específica de turnos |
| Las cuatro fichas de carreras | Duración/ciclos/inicio | 2 años y medio, 6 ciclos; ciclo de 17 semanas/4,5 meses; inicio 2026-10-05 | Equivalencia semanas/meses no exacta; duración total depende del calendario; inicio temporal | Duración estática declarada; calendario temporal | Se conservan 2 años y medio y 6 ciclos; equivalencia no se afirma; inicio archivado |
| Las seis fichas | Tarifas | Una referencia `.pricing.json` por ficha; sin importes efectivos | JSON ya no es fuente primaria | Dinámica | Referencias sustituidas por enlace a pagos, sin valores |
| `03_cursos_cortos/bartender.md` | Formación/requisitos | 3 meses, presencial, sin experiencia; DNI/ficha; mixología, flair, mocktails, certificación y beneficios | Requisitos propios; certificado no equivale a título técnico | Estática específica | Se conserva, con reserva remitida a admisión |
| `03_cursos_cortos/bartender.md` | Horario/inicio | Exclusivamente sábados 09:00–12:00 o 15:00–18:00; YAML 2026-11-15, cuerpo 15 de noviembre | Exclusividad no aprobada; fecha corresponde a domingo | Temporal/dudosa | Posibilidad de sábados, sin exclusividad; fecha/horas archivadas |
| `03_cursos_cortos/panaderia_pasteleria.md` | Formación | 3 meses presencial; panes, fondant, buttercream, chantilly, cremas; perfil emprendedor; certificado | No hay requisitos documentales propios suficientemente especificados | Estática específica | Se conserva; no se inventa una sección de requisitos |
| `03_cursos_cortos/panaderia_pasteleria.md` | Horario/inicio | Exclusivamente sábados 08:00–12:00 o 14:00–18:00; mismo inicio 2026-11-15 | Exclusividad no aprobada; fecha domingo; año omitido en cuerpo | Temporal/dudosa | Posibilidad de sábados; confirmar edición; valores archivados |
| `04_faqs/preguntas_frecuentes.md` | Tarifas/promociones | Referencias a archivos comerciales/JSON | Reintroducía una fuente obsoleta | Dinámica | Consulta de tarifa actual; sin precios, descuentos ni campañas vigentes |
| `04_faqs/preguntas_frecuentes.md` | Requisitos, reserva, canales, fechas, beneficios, clases | Repetición de fichas; DNI como reserva; sábados exclusivos; grabaciones en Q10 | Contradicciones y mantenimiento múltiple | Resumen y enlaces a fuentes principales | Preguntas agrupadas, respuestas breves; reserva/revisión correctas; sábados específicos; fechas retiradas |

## Comparación comercial y dudas administrativas

La base se consultó en modo sólo lectura. Se encontraron seis programas activos
con rutas académicas correctas, seis tarifas activas y 36 pendientes. No se
modificó ningún registro, precio ni campaña. La inscripción vigente conserva el
valor de la base; no se escribe ningún importe efectivo en el conocimiento.

| Programa | Modalidades aprobadas | Turnos registrados en la base |
|---|---|---|
| Administración | Presencial, virtual | mañana, tarde, noche, lunes_viernes |
| Contabilidad | Presencial, virtual | mañana, tarde, noche, lunes_viernes |
| Gastronomía | Presencial | mañana, tarde, noche, lunes_viernes, sábados |
| Guía Oficial de Turismo | Presencial, virtual | mañana, tarde, noche, lunes_viernes |
| Bartender | Presencial | mañana, tarde, noche, lunes_viernes, sábados |
| Panadería y Pastelería | Presencial | mañana, tarde, noche, lunes_viernes, sábados |

Los turnos de la base son una lista por programa; no describen un calendario
ni una relación completa modalidad-turno. No equivalen a aprobación de todas
las combinaciones. `lunes_viernes` y `sabados` expresan días, mientras que
mañana/tarde/noche expresan franjas: esa mezcla requiere revisión administrativa.
Se conservó la configuración actual sin generalizar horarios en los Markdown.

Decisiones pendientes:

1. Ratificar la edición/calendario actual: 2026-10-05 ya pasó; 2026-11-15 es
   domingo y contradice el antiguo anuncio de cursos exclusivamente sabatinos.
   No se ha elegido otra fecha ni corregido el año por suposición.
2. Confirmar horarios y combinaciones de modalidad/turno por programa. Los
   antiguos valores están archivados; no constituyen oferta vigente.
3. Ratificar duración de ciclo (17 semanas frente a 4,5 meses) y calendario de
   seis ciclos en 2 años y medio. No se modificó la duración declarada del programa.
4. Confirmar requisitos particulares de Panadería y Pastelería y alcance de
   los documentos generales respecto a cada curso.
5. Ratificar canales bancarios, horario de atención, licenciamiento, beneficios
   y convenios actuales. Se conserva la información institucional documental;
   esta fase no constituye verificación externa de sus afirmaciones.
6. Confirmar cómo se aplica la continuidad de cuotas a cada estudiante. La
   política documental no se convierte en una regla de precio implementada.

## Precios, promociones y fuentes principales

El inventario inicial ya no tenía importes monetarios explícitos ni campañas
de precio concretas en los nueve Markdown: **cero importes numéricos eliminados**.
Se retiraron nueve referencias `.pricing.json` y se corrigieron referencias
genéricas a archivos comerciales. Los seis JSON permanecen intactos para
migración/compatibilidad de Fase 1.6; no son el catálogo efectivo.

PricingService sigue obteniendo precios/campañas de los repositorios comerciales.
ActionService construye pagos autorizados después de las validaciones y
consentimiento. VoucherService revalida la tarifa y persiste el importe oficial.
Las respuestas de precio de `/chat` y `/chat/stream` conservan la política
existente que sustituye cifras del modelo/RAG por la respuesta comercial
autorizada. Se agregó una regresión con RAG contaminado que comprueba los dos
endpoints, las acciones y un upload. No se duplican políticas en los documentos.

| Tema | Fuente principal |
|---|---|
| Institución, contacto, sedes, plataformas, beneficios comunes | `01_institucional/general.md` |
| Admisión, requisitos generales, reserva, canales y revisión de comprobantes | `01_institucional/admision_y_pagos.md` |
| Formación, duración, modalidad y condiciones propias | Una ficha por carrera/curso |
| Importes, campañas y promociones vigentes | Base comercial mediante PricingService |
| Fechas y horarios de una edición | Confirmación administrativa por periodo; no hay un calendario nuevo en esta fase |
| FAQ | Resumen enlazado; sin réplicas de teléfonos, cuentas, requisitos detallados ni fechas |

Las fichas usan Descripción, Duración, Modalidades, Qué aprenderás, Campo laboral,
Requisitos cuando están documentados e Información adicional. Panadería conserva
Perfil del estudiante; no se añaden secciones vacías ni datos inventados. Se
conservan únicamente los metadatos mínimos que utiliza la recuperación:
id/tipo/categoría/título/tags. No se introducen configuraciones administrativas.

No se detectaron Markdown vacíos, de Vite/default, duplicados íntegros o sin
contenido útil dentro de `backend/knowledge`. **No se propone eliminar ninguno
de los nueve documentos**. Las fechas, horarios históricos y referencias a JSON
son contenido retirado, conservado en el archivo de revisión. No se borraron
archivos dudosos ni los JSON de migración.

## Validador y regresiones

`backend/validate_knowledge.py` no importa proveedores, embeddings ni ChromaDB.
Detecta importes y promociones monetarias/porcentuales, gratuidad comercial
incondicional, referencias comerciales antiguas, metadatos dinámicos, fechas
incompletas/formatos inesperados/imposibles, enlaces/anchors/assets locales
inexistentes, referencias sin definición, rutas fuera de raíz, encabezados e
identidades duplicados, archivos vacíos y UTF-8 inválido. Las fechas ISO válidas
emiten advertencia de revisión: una fecha histórica puede ser legítima. No
verifica disponibilidad de enlaces externos ni exactitud semántica institucional.

Devuelve 1 ante problemas críticos y 0 cuando no hay errores. Opción `--json`
para herramientas; `--commercial-db` compara identidades, tipo y modalidades
usando SQLite de sólo lectura, sin crear bases ni migrar. La lista de turnos se
inventaría en este informe; el validador no infiere horarios desde ella.

```powershell
backend/venv/Scripts/python.exe -B backend/validate_knowledge.py
backend/venv/Scripts/python.exe -B backend/validate_knowledge.py --commercial-db backend/storage/commercial.sqlite3
backend/venv/Scripts/python.exe -B -m unittest discover -s backend/tests
```

Si se configura otra ruta comercial, pasar esa ruta a `--commercial-db`.

Las 13 regresiones nuevas cubren el corpus completo y discrepancias de modalidad,
errores del validador y códigos de salida, preservación de fragmentos académicos
y metadatos, regla de sábados y FAQ, PricingService sin lectura de Markdown,
precios obsoletos del RAG frente a JSON/SSE/vouchers y enrutamiento de recuperación
por los seis programas. La fragmentación utiliza las funciones puras del loader
existente; la búsqueda usa un almacén simulado con fragmentos reales. No se
generan embeddings ni se evalúa todavía la calidad semántica del índice real.

## Resultado y límites operativos

Resultados de cierre:

| Comprobación | Resultado |
|---|---|
| Validador con comparación comercial de sólo lectura | 9 archivos; 0 errores; 0 advertencias |
| Suite backend completa | 131 pruebas aprobadas, incluidas Fases 1–3 y las 13 nuevas |
| Suite frontend completa (`npm test`) | 26 pruebas aprobadas |
| `npm run build` | Correcto; advertencia previa de bundle de 783,12 kB superior a 500 kB |
| Sintaxis Python mediante AST, sin bytecode | 53 archivos correctos, excluyendo entorno virtual |
| Sintaxis JavaScript mediante `node --check` | 16 archivos de `src` y `tests` correctos |
| `git diff --check` | Código 0; sólo avisos de conversión LF/CRLF en cambios anteriores |

El frontend no recibió cambios en esta fase. Las pruebas no invocaron proveedores
externos ni comprobaron el índice vectorial real. La advertencia del bundle queda
para la fase de rendimiento prevista; no se optimiza en esta revisión.

El índice existente sigue conteniendo su versión anterior hasta la Fase 5.
Por eso aún puede recuperar información académica temporal antigua; la política
de precios vigente permanece protegida por PricingService. No afirmar que el
RAG real ya utiliza las fichas actualizadas antes de regenerar/consolidar el
índice. No se cambió ChromaDB, el diseño visual, el avatar o los flujos SSE.
