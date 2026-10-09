# Fase 7 — Rendimiento y latencia

Implementada el 7 de octubre de 2026. No se inició la Fase 8. Se conservaron las reglas comerciales, DTO públicos, orden SSE, sesiones, consentimiento, pricing dinámico, modos web/kiosk y personas info/sales. No se modificó el VRM original ni el conocimiento, modelo, chunking o umbral del índice aprobado.

## Medición y alcance

La línea base se registró antes de cambiar el pipeline y frontend. Los archivos `fase-7-baseline.json`, `fase-7-assets-baseline.json` y `fase-7-browser-baseline.json` conservan esa medición. El benchmark de pipeline usa cinco respuestas idénticas, seis oraciones, LLM simulado de 20 ms por fragmento y TTS simulado de 100 ms por oración; incluye SQLite real y tracemalloc. Las cifras son medianas, no promesas de latencia de proveedores. Los temporizadores Windows y la carga local introducen variación.

El benchmark de navegador usa Chrome headless en localhost, un perfil temporal y GPU por software. La ocultación se simula mediante visibilitychange; también se comprueba reanudación. No constituye un perfil de GPU física ni una prueba de ocho horas. El instante del avatar indica que el modelo quedó incorporado a la escena; no certifica que todos sus píxeles ya hayan terminado de procesarse en GPU.

## Comparación del pipeline simulado

Todos los tiempos de esta tabla están en milisegundos. Primer texto/audio/acción y total parten del inicio de la operación, incluyendo bootstrap.

| Componente | Antes | Después |
|---|---:|---:|
| Bootstrap sesión | 5.57 | 7.47 |
| RAG simulado | 23.12 | 22.36 |
| Primer token LLM simulado | 29.07 | 28.76 |
| Consumo completo LLM | 867.83 | 248.94 |
| Primer texto SSE | 77.30 | 80.76 |
| Síntesis primera oración | 107.11 | 109.62 |
| Primer audio SSE | 193.82 | 192.48 |
| Suma de síntesis TTS | 657.72 | 651.12 |
| Último audio desde inicio | 932.27 | 438.39 |
| Primera acción | 939.75 | 444.17 |
| Petición completa | 964.12 | 463.64 |

La reducción principal corresponde al tiempo total y al último audio, al solapar generación y síntesis. La primera emisión de texto y el primer audio no muestran una mejora consistente en las muestras simuladas: sus pequeñas diferencias deben tratarse como variación y sobrecoste de coordinación, no como un avance demostrado. El tiempo LLM completo es el tiempo observado al consumir el stream e incluye backpressure; no significa que Groq compute tokens más rápido. La suma de duraciones de TTS puede superar su tiempo de pared porque dos síntesis se solapan.

RAG real: antes, arranque frío 2.536 s, consulta caliente 24.06 ms y embedding 9.58 ms. Después, arranque frío 3.477 s, consulta caliente 17.56 ms y embedding 13.30 ms. El arranque frío y embedding no mejoraron en esta muestra; no se cambió su modelo. Se comprobaron cinco consultas y exactamente cinco embeddings. La evaluación completa recupera correctamente las doce consultas positivas/negativas aprobadas. Continúan 66 chunks y 384 dimensiones en `lia_knowledge`.

## Proveedores reales y texto visible

Se ejecutó una consulta académica fija sin datos personales con Groq y Edge-TTS reales, y otra equivalente con calentamiento previo. Cada escenario tiene una muestra; la variación de red/proveedor impide atribuir toda la diferencia al código.

| Métrica | Índice frío | Índice precalentado |
|---|---:|---:|
| Bootstrap sesión | 235.93 ms | 7.98 ms |
| RAG | 5285.63 ms | 45.83 ms |
| Embedding | 13.53 ms | 10.53 ms |
| Groq primer token | 1624.04 ms | 981.29 ms |
| Groq total observado | 1686.13 ms | 1035.14 ms |
| Texto SSE | 7188.59 ms | 1073.73 ms |
| TTS primera oración | 1376.72 ms | 1209.23 ms |
| Primer audio SSE | 8561.35 ms | 2280.58 ms |
| Total petición | 8589.90 ms | 2309.17 ms |

Ambas respuestas generaron 48 tokens según usage del proveedor. El calentamiento previo costó 3.66 s y se contabiliza fuera de la petición: desplaza el coste al inicio, no lo elimina. `KNOWLEDGE_PREWARM=true` lo habilita; su default es false para conservar el arranque previo. Usa el índice validado existente y tiene timeout; jamás construye ni promueve una generación. Un fallo produce un evento técnico seguro y readiness sigue comprobando el índice.

En una conversación real de navegador kiosk (otra consulta académica): primer texto SSE 7.65 s, primera respuesta visible y primer audio reproducido 9.96 s, transporte terminado 9.94 s y reproducción finalizada 21.39 s. Los subtítulos mantienen la sincronización aprobada con audio; primer texto recibido no equivale a primer texto visible. No existe baseline real previo comparable para esta conversación de navegador, ni una distribución de latencias de producción.

## Cuellos de botella y optimizaciones

- La síntesis antes bloqueaba la lectura de nuevas oraciones. `OrderedSpeechPipeline` produce y sintetiza por separado, con dos workers y dos posiciones pendientes por defecto. El máximo observado fue cuatro tareas de audio y dos síntesis activas. El consumidor entrega text/audio en orden de oración; acciones y done conservan su posición posterior. Las acciones del frontend además esperan la finalización real de reproducción.
- Cancelar cierra productor, síntesis, fuente y stream, y libera la sesión. Una prueba detectó una tarea activa al cerrar un consumidor; se corrigió cancelando todas juntas. No se persiste una respuesta incompleta ni se ejecutan acciones canceladas.
- El frontend espera capacidad antes de consumir más audio SSE: ocho buffers pendientes, además del que se reproduce. Esto aplica backpressure; no agrega un transporte distinto ni descarta frases para acelerar. Los timeouts existentes siguen limitando una operación bloqueada.
- El segmentador incremental reconoce .?! y conserva decimales, abreviaturas e inicios de listas. Sintetiza oraciones completas o el resto al terminar, no fragmentos por token. El ensamblado mantiene el límite de 16.000 caracteres.
- Chroma, colección y embedder se reutilizan. La validación completa del manifiesto se cachea como máximo dos segundos y se invalida mediante cambios de archivos; readiness y comprobaciones administrativas mantienen verificación completa sin esta caché. No se añadió caché global de consultas ni precios.
- Las consultas cortas con programa y tema explícitos evitan reformulación adicional; las preguntas de seguimiento ambiguas conservan la llamada. Hay comparación de contexto con/sin historial y pruebas de la política, además de evaluación real del índice. Una reformulación real de seguimiento tardó 513.65 ms y resolvió el programa esperado; es una muestra, no un percentil. Ese coste adicional se conserva cuando aporta contexto y se evita en preguntas explícitas.
- Se conservó el cliente Groq compartido entre conversación y reformulación, con cierre en lifecycle. Edge-TTS 7.2.8 crea/cierra ClientSession por síntesis y toma propiedad del connector; compartirlo directamente sería inseguro. Se conservó su implementación y se solapa trabajo con concurrencia limitada, sin parchear el SDK.

## Métricas seguras

`PerformanceTrace` y eventos de bootstrap registran únicamente campos técnicos numéricos finitos y correlation/request_id generado por backend: bootstrap/preparación, RAG, embedding, reformulación, apertura/primer token/total LLM, TTS, primer texto/audio, acciones, total, bytes y picos de cola/concurrencia. Las métricas de texto visible, reproducción y transporte se registran separadamente en frontend como diagnóstico numérico. Cuando el transporte/proveedor no permite medir un componente, no se inventa el valor.

No se registran prompts, mensajes, nombres, teléfonos, audio, credenciales ni Authorization. Los benchmarks usan textos sintéticos y almacenamiento conversacional temporal; el ensayo de navegador creó una sesión anónima de prueba mediante la API normal, sin leads ni vouchers. No existe nuevo endpoint público de métricas.

## Bundle, carga inicial y media

| Transferencia JS | Antes | Después |
|---|---:|---:|
| Entrada principal | 783.17 KB | 24.59 KB |
| JS crítico total, incluidas dependencias | 783.17 KB | 773.47 KB |
| Gzip nivel 9 crítico | 194.76 KB | 193.23 KB |
| JS total, incluidos módulos diferidos | 783.17 KB | 787.87 KB |
| Mayor chunk | 783.17 KB | 610.23 KB |

Three.js ocupa 610.23 KB y VRM 138.65 KB; npm verifica una sola versión de Three.js, deduplicada en las dependencias VRM. La atribución inicial mediante sourcemap identificó 2.29 MB de fuentes Three.js y 0.99 MB VRM sin minificar; esos valores no equivalen a bytes de transferencia.

No hay una reducción masiva de JS: el total aumenta ligeramente por diagnóstico/coordinación y separación. El beneficio es diferir 14.40 KB de modales y poder reutilizar chunks estables de Three/VRM entre publicaciones. La advertencia Vite de chunk superior a 500 KB permanece y no se ocultó.

HTML/CSS, configuración pública, conversación/reconocimiento y avatar siguen siendo críticos. Los modales se importan al solicitar una acción autorizada, con comprobación de vigencia también después de resolver el import. Galerías no se descargan antes de solicitarse; imágenes usan loading=lazy y decoding=async. No se cambiaron CSS, diseño ni apariencias.

## Avatar y render

VRM: 17.729.200 bytes, exactamente el mismo SHA-256 de baseline. Tres mallas, 17 materiales y 29 imágenes. El cálculo de texturas RGBA sin mipmaps/geometría es 124.257.024 bytes (118.5 MiB), una estimación y no una medida de VRAM real.

Arranque local kiosk: DOM listo 370.4 → 199.1 ms; avatar incorporado 1.025 → 0.801 s. Descarga VRM 293.7 → 240.1 ms. Carga/parseo/materiales en conjunto 553.2 ms y preparación de escena 29.9 ms; el material y GPU no se perfilan independientemente con precisión. La instrumentación de compileShader/texImage2D es tiempo de envío CPU, no tiempo GPU.

Recarga con caché: avatar 0.688 s, descarga desde disco del navegador, cero bytes de red del VRM frente a 17.729.965 bytes con headers en carga fría. En modo web el avatar también cargó correctamente (0.878 s en otra muestra local). Estas cifras de localhost no representan conexión móvil.

Render oculto: 5.208 llamadas de dibujo en cuatro segundos antes; cero después, con reanudación comprobada. Se conserva la cadencia visible, lipsync por intensidad, respiración, mirada, parpadeo y atracción. No se redujo FPS visible ni resolución de texturas sin comparar calidad.

## Caché y cleanup

`/api/config` conserva el DTO público pequeño (~156 bytes), usa ETag y revalidación no-cache. Su tiempo en la muestra local bajó de 70.2 a 16.4 ms; no se atribuye esa diferencia completa a caché porque el perfil inicial estaba vacío. La revisión incluye configuración pública y tamaño/mtime del avatar; frontend deriva ?v=hash solo tras validar URL y ETag. VRM versionado tiene caché larga; recursos no versionados revalidan. No se cachean chats, sesiones, leads, vouchers ni administración.

En el hosting de frontend se debe aplicar a assets con hash `Cache-Control: public, max-age=31536000, immutable`, gzip/brotli y revalidación del HTML. Vite genera assets versionados, pero el servidor Python usado para diagnóstico no configura ese hosting de producción. No se modificó infraestructura de despliegue.

Audio libera buffers y nodos, callbacks de cola y AudioContext al salir; cancelar libera waiters y timers de reintento inmediatamente. El render libera RAF/listeners y temporizador de atracción. Controles eliminan listeners y handlers de reconocimiento. pagehide fuera de BFCache cancela petición, dispone VRM y renderer y elimina resize; BFCache conserva recursos para reanudación. Un VRM que termina de cargar después de dispose se descarta y libera. Las marcas de rendimiento del loader se reemplazan, evitando acumulación.

Pruebas de 100 ciclos de audio, render y controles no acumulan callbacks/listeners activos. Benchmark de 100 turnos sobre una sesión persistente: 12 turnos retenidos, cero tareas de sesión pendientes, 1.25 MiB de incremento Python trazado y 1.31 MiB de pico. El script también retiene sus muestras numéricas; esto no demuestra ausencia total de leaks nativos. Heap JS al arranque pasó aproximadamente 55.7 a 58–60 MB en muestras aisladas: no se demostró reducción de memoria. Falta soak de varias horas en hardware kiosk físico.

## Presupuestos de verificación local

Basados en las medidas obtenidas, para el mismo escenario/equipo: pipeline simulado primer texto <=100 ms, primer audio <=230 ms y total <=600 ms; RAG caliente <=35 ms; JS crítico <=780 KB sin comprimir y <=195 KB gzip nivel 9; avatar local frío <=1.3 s. Son objetivos de diagnóstico con margen, no garantías ni límites de seguridad. Para Groq/Edge y redes reales falta una muestra mayor y percentiles antes de definir SLO. El calentamiento opcional debe contabilizarse como tiempo de startup.

## Archivos de la fase

Backend nuevos: services/performance.py, speech_pipeline.py, sentence_segmenter.py; security/static.py; benchmark_pipeline.py, benchmark_browser.py; tests/test_phase7.py.

Backend ajustados: conversation_service.py, llm_protocol.py, providers.py, llm_service.py, rag_service.py, knowledge_index.py, knowledge_retrieval.py, app_services.py, server.py, config.py, runtime_config.py, security/logging.py y http.py, api/public_config.py y sessions.py, .env.example, requirements.txt. La única dependencia directa añadida es websockets ya instalado, para diagnóstico CDP opcional; no hay nuevo proveedor funcional.

Frontend nuevos: avatar/renderLoop.js, ui/lazyOverlays.js, tests/performance.test.js, scripts/analyze-build.mjs, vite.config.js. Ajustados: api/actions.js, client.js, publicConfig.js; audio/player.js; avatar/animator.js y loader.js; ui/controls.js y overlays.js; main.js, package.json y fixtures de pruebas. Cambios aprobados de fases anteriores permanecen en el working tree y no se atribuyen a esta fase.

## Comandos reproducibles desde la raíz

```powershell
backend/venv/Scripts/python.exe -B backend/benchmark_pipeline.py --runs 5 --rag --output docs/benchmark.json
backend/venv/Scripts/python.exe -B backend/benchmark_pipeline.py --stress 100 --output docs/stress.json
backend/venv/Scripts/python.exe -B backend/benchmark_pipeline.py --real --runs 1 --prewarm --rewrite --output docs/real.json
backend/venv/Scripts/python.exe -B -m unittest discover -s backend/tests -v
backend/venv/Scripts/python.exe -B backend/rebuild_knowledge.py --evaluate
backend/venv/Scripts/python.exe -B backend/rebuild_knowledge.py --check
backend/venv/Scripts/python.exe -B backend/validate_knowledge.py
npm --prefix avatar-kiosk test
npm --prefix avatar-kiosk run build
node avatar-kiosk/scripts/analyze-build.mjs
# Con backend:8000 y frontend:5173 locales ya disponibles; Chrome Windows instalado:
backend/venv/Scripts/python.exe -B backend/benchmark_browser.py --reload --output docs/browser.json
# Opción --conversation hace una consulta sintética mediante proveedores reales.
git diff --check
```

Los modos simulados no llaman Groq/Edge; --rag sí genera embeddings locales reales contra el índice activo. --real requiere credenciales backend y acceso de red, pero no imprime claves ni prompts. El perfil Chrome es temporal y el proceso propio se termina al finalizar; el helper actual presupone Chrome instalado en su ruta estándar de Windows.

## Validación y pendientes

176 pruebas backend completas aprobadas, incluidas concurrencia real de repositorio y regresiones Fases 1–6; 33 frontend aprobadas; 12 consultas RAG reales aprobadas; knowledge validator nueve archivos sin errores/advertencias; índice ready; npm build aprobado con la advertencia Three.js indicada. Validación sintáctica Python/JavaScript y git diff --check completadas. Se añadieron regresiones para primera oración medida correctamente aunque otra termine antes, orden/concurrencia/backpressure/cancelación TTS, audio inicial antes de terminar LLM, segmentación, cache/manifiesto, precalentamiento lifecycle, import cancelado, cleanup y timers.

No se aplicaron compresión KTX/Draco, reducción de texturas/mallas/morphs, cambio de Groq, transporte binario, nuevo lipsync ni limitación de FPS visible. Esas opciones necesitan comparación visual o decisiones de contrato. Base64 mantiene 33.36% de sobrecoste: 30.720 bytes originales → 40.968 en benchmark; JSON parse y atob para 5 KB tardaron ~0.003 y ~0.007 ms combinados en Chrome local. Se preserva SSE aprobado. La latencia externa y el coste de VRM/texturas siguen siendo los principales pendientes para pruebas en producción/hardware real. Se observó también la solicitud implícita de favicon.ico con 404 en el servidor local, ya presente en baseline; no afectó conversación ni avatar y queda para configuración de branding/despliegue. No se avanzó a la Fase 8.
