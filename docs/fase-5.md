# Fase 5: índice vectorial único, regeneración y validación

Revisión del 7 de octubre de 2026. Sólo se intervienen configuración, ingestión,
recuperación y readiness del conocimiento. PricingService, servicios comerciales,
sesiones, leads, vouchers, seguridad, acciones, audio, frontend y Markdown de
Fase 4 conservan sus contratos y políticas. No se inicia la Fase 6.

## Inventario previo, antes de modificar

| Ubicación | Colección | Chunks | Dimensión | Estado previo | Runtime anterior | Tratamiento |
|---|---|---:|---:|---|---|---|
| `D:/asistente_virtual/chroma_db` | `knowledge` | 0 | Sin dimensión | SQLite íntegro, colección vacía | Elegida al iniciar desde raíz con `./chroma_db` | Legado; no es fuente runtime |
| `D:/asistente_virtual/backend/chroma_db` | `knowledge` | 70 | 384 | SQLite íntegro; contenido anterior a Fase 4, incluidos importes, promociones y fechas | Elegida al iniciar desde backend | Respaldo histórico; no es fuente runtime |

La colección de backend contenía 6 fragmentos de admisión, 9 institucionales,
7 de Administración, 7 de Contabilidad, 9 de Gastronomía, 9 de Turismo,
6 de Bartender, 8 de Panadería y 9 FAQ. Sus metadatos incluían id, tipo,
categoría, título, fuente, tags, encabezados, modalidad, duración, ciclos y
fechas de inicio antiguas. Usaba distancia L2; no había manifiesto del modelo.
No se puede certificar el artefacto exacto que generó sus vectores antiguos.

El código declaraba FastEmbed con
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` en dos lugares.
El script usaba `./knowledge` y `./chroma_db`, borraba la colección y después
intentaba recrearla. Runtime usaba `./chroma_db`, podía crear una colección
vacía y efectuaba varias búsquedas por texto, repitiendo su embedding.

No se borró ni movió ninguna base antigua. El SQLite de la raíz ya está
versionado en Git: su retiro del repositorio y del despliegue requiere una
decisión posterior; no se ejecutó `git rm`.

## Ubicación y colección oficiales

La única raíz oficial por defecto es
`D:/asistente_virtual/backend/storage/knowledge_index`.
`CHROMA_DB_PATH` admite ruta absoluta o relativa **a backend**, nunca a cwd.
Se comporta igual desde raíz, backend, IDE, test runner o servicio. No se
buscan directorios alternativos cuando el configurado falla.

La colección oficial es **lia_knowledge**. Su identidad, modelo y dimensión
se validan explícitamente. Cambiarla a `knowledge`, cambiar de modelo o de
dimensión no se acepta silenciosamente: requiere migración de configuración
y código revisada. Una colección ausente no se crea al atender una consulta.

```text
storage/knowledge_index/
  active.json                         selector atómico, una sola generación activa
  generations/gen-<uuid>/
    chroma.sqlite3                    colección lia_knowledge
    <segmento>/...bin                  artefactos nativos HNSW
    manifest.json                     versión lógica e integridad
    evaluation.json                   consultas de aceptación
    embedding_integrity.npz           vectores canónicos, sin pickle
```

Las generaciones son inmutables a nivel de contenido académico y operaciones
de negocio: runtime no inserta/borrar documentos. Chroma puede escribir buffers
nativos al abrirlos/reconstruir su representación en memoria; no se presenta
como una base físicamente de sólo lectura.

## Fuentes, chunking y embeddings

`SOURCES` en `services/knowledge_index.py` enumera explícitamente los nueve
Markdown autorizados de `backend/knowledge`. Un Markdown añadido requiere
revisión y registro explícito. La regeneración rechaza fuentes Markdown no
registradas; el checker las detecta como cambio del corpus. Nunca se indexan
JSON comerciales, SQLite, documentación, archivos históricos, backups, logs,
pruebas ni temporales. No se cambió ningún Markdown en esta fase.

Se conserva la división por encabezados Markdown y el límite de **800
caracteres**, con **80 caracteres de solapamiento** para secciones largas.
Se unen subtítulos H3 vecinos del mismo documento/H2 si juntos caben en 800
caracteres. Nunca se unen programas ni archivos. Título y jerarquía se incluyen
en el texto de entrada al embedding para que una sección corta conserve su
identidad. El texto académico almacenado permanece separado de las instrucciones
de sistema y no recibe datos comerciales dinámicos.

Cada fragmento conserva source_id, tipo, categoría, título, heading, fuente,
hash de contenido y program_id para carreras/cursos. Se mantienen id/tags y
metadatos h1/h2/h3 para los consumidores existentes.

El resultado final es **66 chunks de nueve fuentes**. La versión de chunking es
`markdown-headings-800-overlap80-merged-h3-title-v4`.
Cada ficha y documento institucional aporta siete chunks; la FAQ aporta diez.
Los fragmentos finales tienen entre 106 y 787 caracteres, con media de 380,7.
La generación promovida es `gen-c0da458fc3a24a759ac692531c536591`;
su manifiesto está en
`backend/storage/knowledge_index/generations/gen-c0da458fc3a24a759ac692531c536591/manifest.json`.

Se conserva FastEmbed **0.8.1**, el modelo multilingüe existente, y **384
dimensiones**. El índice nuevo usa distancia **coseno**: los umbrales L2 de
colecciones antiguas no se reutilizan. Modelo/dimensión se comprueban en el
manifiesto y en vectores de documentos/consulta.

La caché por defecto es `backend/storage/embedding_models`, privada y
determinística. Se provisionó copiando el modelo ya disponible localmente;
no se descargó otro modelo. `CHROMA_LOCAL_FILES_ONLY=true` evita descargas
durante el uso normal. En otra máquina hay que provisionar esa caché antes de
construir/servir consultas. Para una descarga administrativa controlada se puede
usar temporalmente `CHROMA_LOCAL_FILES_ONLY=false` en el proceso de construcción,
y volver a true para el servidor. No se introducen dependencias nuevas; se fijan
las versiones ya instaladas de ONNX Runtime 1.30.0 y NumPy 2.5.3 para reproducir
el cálculo validado.

## Construcción y promoción

1. Validar conocimiento con el mismo validador de Fase 4 y lista de fuentes.
   Un error aborta antes de modificar el directorio del índice.
2. Adquirir `rebuild.lock` exclusivo. Nunca hay dos constructores promoviendo
   simultáneamente. Crear una carpeta candidata con UUID, sin tocar la activa.
3. En un proceso separado, fragmentar, calcular embeddings reales, crear una
   única colección e indexar. Registrar hashes de fuentes; si cambian durante
   la construcción, abortar. Evaluar recuperación y escribir manifiesto.
4. Cerrar ese proceso y reabrir el candidato en otro proceso: verificar vectores
   persistidos y repetir las consultas contra el almacenamiento reabierto.
5. Con handles cerrados, sellar artefactos y verificar SQLite, colección,
   dimensión, cantidad, metadatos, hashes, fuentes y aceptación.
6. Sustituir sólo `active.json` mediante archivo temporal, flush/fsync y
   `os.replace` dentro del mismo volumen. No se renombran carpetas abiertas.

Cada consulta captura una generación; una promoción no mezcla fragmentos de
dos versiones en esa consulta. La siguiente consulta detecta el selector nuevo.
Un fallo de validación, embeddings, recuperación, reapertura, timeout o promoción
conserva el selector anterior. El script nunca borra la base activa. Los candidatos
fallidos y las generaciones anteriores se conservan para diagnóstico/revisión.

El constructor tiene timeout de 600 segundos y la verificación posterior de
180 segundos. Un lock tras cierre abrupto no se elimina automáticamente: comprobar
el PID/ausencia de constructor antes de retirarlo manualmente. La promoción es
local; no se prometen coordinación distribuida ni tolerancia total a pérdida de
energía del sistema de archivos.

## Manifiesto, integridad y readiness

El manifiesto registra schema_version, generated_at, modelo/dimensión, versiones
de librerías, hashes de artefactos del modelo, versión/parámetros de chunking,
lista/hash SHA-256 de fuentes, colección, métrica, cantidad/hash de chunks,
integridad de vectores y resultados de evaluación. No contiene secretos.

La comprobación usa SQLite de sólo lectura para evitar crear colecciones vacías.
Verifica integridad estructural, una colección exacta, dimensión, cantidad,
metadatos, hash del contenido y log persistido de embeddings. Los vectores
canónicos se almacenan comprimidos en NPZ sin pickle y se cotejan con Chroma al
reabrir/promover y al cargar una generación en runtime. La comparación numérica
permite únicamente la pequeña normalización coseno del motor (rtol 1e-5,
atol 1e-6). Se verifican tamaños de artefactos HNSW y hash del encabezado;
no se hashean buffers nativos completos con posiciones reservadas no utilizadas,
porque esos bytes pueden cambiar legítimamente al abrir Chroma.

Cambiar Markdown, añadir uno nuevo o faltar una fuente marca **stale**. Ausencia, corrupción,
colección vacía/incompatible o manifiesto inválido marca **invalid**. Ambos estados
se distinguen: **invalid** impide consultas RAG; **stale** conserva disponible el
índice activo previamente validado mientras se corrige una fuente o reconstrucción.
Así un Markdown inválido no deja al asistente sin su último índice funcional.
No se promueve un candidato stale ni se usa otra base como respaldo automático.
`--check` y readiness comprueban además los vectores obtenidos por el motor real,
sin cargar embeddings ni consultar Groq/TTS.

`/health/ready` devuelve únicamente `knowledge: {status: ready|stale|invalid}` y
el booleano de knowledge en checks, sin rutas, nombres de archivos, hashes ni
fragmentos. **Comprobación real: HTTP 200, status ready, todos los checks true**
(comercial, configuración, avatar, PricingService, runtime y knowledge).
Groq/TTS permanecen not_probed. Stale se comunica sin sacar de servicio un índice
íntegro: readiness sigue operativa; `--check` devuelve 1 para bloquear un despliegue
desactualizado. Invalid devuelve readiness 503. Liveness conserva su independencia.

## Recuperación y evaluación real

Configuración: top_k **6**, max_context_chunks **6**, distancia coseno máxima
**0.65**. No se agregan fragmentos por debajo de la relevancia establecida ni
se rellena con otros programas cuando falta información. El umbral es una
distancia, no una probabilidad ni un porcentaje de precisión.

Se priorizan nombres explícitos de programas sobre alias inferidos (japonés no
desplaza una mención explícita de Administración). Las preguntas institucionales
generales no heredan el programa de un turno anterior. Para requisitos, contacto
o beneficios asociados a un programa se conservan fragmentos institucionales
de apoyo: hasta cuatro del programa y dos de la fuente institucional pertinente,
respetando el límite total. No se consultan otros programas como complemento.

Una consulta genera **un solo embedding**. La búsqueda principal y la de apoyo
reciben exactamente el mismo vector. La ampliación de vocabulario para modalidad,
ubicación, contenido y tarifas expresa temas de búsqueda; no proporciona una
respuesta, importe o modalidad efectiva. No hay caché global de consultas.

| Consulta | Fuente esperada | Resultado de aceptación |
|---|---|---|
| ¿Qué se aprende en Administración? | Administración / carreras | Recupera formación correspondiente |
| ¿Gastronomía es virtual? | Gastronomía / carreras | Recupera presencial y negación de virtualidad |
| ¿Qué idiomas enseña Turismo? | Turismo / carreras | Recupera inglés y japonés |
| ¿Necesito experiencia para Bartender? | Bartender / cursos | Recupera ausencia de experiencia previa necesaria |
| ¿Qué aprenderé en Panadería? | Panadería y Pastelería / cursos | Recupera contenidos, incluida decoración con fondant |
| ¿Dónde queda el instituto? | Institucional general | Recupera Bellavista y oficina Garcilaso |
| ¿Qué documentos necesito para matricularme? | Admisión | Recupera DNI y certificado de estudios |
| ¿Qué documentos necesito para Gastronomía? | Gastronomía + apoyo de Admisión | Recupera documentación sin otro programa |
| ¿Administración enseña japonés? | Administración | No introduce japonés desde Turismo |
| ¿Contabilidad tiene clases los sábados como Bartender? | Contabilidad o abstención por umbral | Sin fragmentos irrelevantes; no atribuye sábados de Bartender |
| ¿Bartender puede tener actividades los sábados? | Bartender | Recupera posibilidad, sin exclusividad |
| ¿Cuál es el precio de matrícula? | Admisión | Referencia al sistema comercial, ningún importe |

Se comprueban fuente, categoría, programa, contenido esperado y ausencia de
contenido prohibido; no basta con devolver algún texto. La comparación negativa
de Contabilidad permite abstención y se documenta como tal, no como recuperación
positiva. Estas pruebas evalúan recuperación, no respuestas generadas por Groq.
Los **12 casos pasaron** en la construcción, tras reabrir el candidato y mediante
el servicio runtime real. El resultado por fuente/distancia/criterio se conserva
en [fase-5-evaluacion.json](fase-5-evaluacion.json). Once consultas recuperan sus
fuentes permitidas; la comparación negativa de Contabilidad devuelve cero chunks.

PricingService sigue siendo autoritativo. No se indexan importes/campañas; las
regresiones de Fase 4 inyectan precios antiguos en RAG y demuestran que JSON,
SSE, acciones y vouchers conservan importes de la base comercial.

## Comandos administrativos

Desde raíz del proyecto:

```powershell
backend/venv/Scripts/python.exe -B backend/validate_knowledge.py
backend/venv/Scripts/python.exe -B backend/rebuild_knowledge.py --validate-only
backend/venv/Scripts/python.exe -B backend/rebuild_knowledge.py --build
backend/venv/Scripts/python.exe -B backend/rebuild_knowledge.py --check
backend/venv/Scripts/python.exe -B backend/rebuild_knowledge.py --evaluate
```

Desde backend, usar `venv/Scripts/python.exe -B rebuild_knowledge.py ...`.
En Linux utilizar el ejecutable Python del entorno instalado y las mismas opciones.
Una operación inválida devuelve código 1; sólo check ready/evaluación aprobada
devuelven 0. No se requiere Groq API key para estos comandos. `ingest.py` queda
como entrada legada: --dry-run valida, y el comando antiguo sin argumentos delega
en la construcción segura. Ya no existe el borrado de colección anterior.

Variables documentadas en `backend/.env.example`: CHROMA_DB_PATH,
CHROMA_COLLECTION_NAME, CHROMA_EMBEDDING_MODEL, CHROMA_EMBEDDING_DIMENSION,
CHROMA_MODEL_CACHE, CHROMA_LOCAL_FILES_ONLY, CHROMA_EMBEDDING_THREADS,
CHROMA_TOP_K, CHROMA_MAX_CONTEXT_CHUNKS y CHROMA_MAX_DISTANCE. CHROMA_K se
reemplaza por los parámetros explícitos anteriores. El nombre de colección/modelo
debe coincidir con los valores admitidos. No son secretos ni variables VITE_*.

## Archivos y pendientes

Nuevos: knowledge_config.py, rebuild_knowledge.py, services/knowledge_index.py,
services/knowledge_retrieval.py, services/knowledge_evaluation.py y
tests/test_phase5.py. Modificados: config.py, ingest.py, services/rag_service.py,
services/health_service.py, .env.example y requirements.txt. El fixture de
recuperación de test_phase4.py se adapta al contrato KnowledgeIndex conservando
la prueba de fuentes académicas sin proveedores. Este informe y sus resultados
reales se guardan en docs; nunca se indexan.

Las dos bases legacy pueden retirarse manualmente después de validar el nuevo
despliegue y confirmar que ningún proceso antiguo las usa. No deben copiarse al
despliegue nuevo. Los candidatos fallidos/generaciones anteriores también pueden
retirarse posteriormente comprobando active.json, con procesos detenidos; ninguna
limpieza se ejecuta en esta fase. No editar active.json manualmente ni usar una
generación stale como rollback sin restaurar/revisar sus fuentes compatibles.

Los backups comerciales y operativos siguen intactos. El índice es reproducible
desde Markdown/código/modelo: conservar esos artefactos o reconstruirlo en destino.
Si se necesita respaldar el índice completo, detener los procesos que lo abren
y copiar la generación con su manifiesto/vectores; no hacer una copia ordinaria
de un Chroma abierto. No se restauró ni sobrescribió ninguna base comercial.

Pendientes: validar en el sistema operativo de despliegue final, ampliar la
evaluación con preguntas reales, ajustar umbral con ese conjunto y planificar
retención manual de generaciones. Recomendado un proceso de backend para este
Chroma local; no se implementa coordinación distribuida. Un modelo/versiones
incompatibles exige nueva validación. La advertencia de bundle y la deprecación
de asyncio.iscoroutinefunction dentro de Chroma quedan documentadas; no se
cambian dependencias para una versión futura de Python en esta fase.

Referencias utilizadas para confirmar APIs:
[cliente Python de Chroma](https://docs.trychroma.com/reference/python) y
[modelos de FastEmbed](https://qdrant.github.io/fastembed/examples/Supported_Models/).

## Verificaciones finales

No se llama a Groq ni TTS para medir recuperación. Las suites preservan pruebas
de Fases 1–4 y añaden seguridad de construcción/promoción, cwd, hashes/stale,
fuentes no autorizadas, cambios de corpus, corrupción/vacío/incompatibilidad,
embedding único con búsquedas de apoyo, disponibilidad del índice vigente y
construcción/reapertura/evaluación real en procesos aislados.

| Comprobación | Resultado |
|---|---|
| Validador de conocimiento y modalidades comerciales | 9 archivos; 0 errores; 0 advertencias |
| Construcción real + verificación reabierta | 66 chunks; una colección lia_knowledge; aprobado |
| Evaluación real | 12/12 casos de aceptación aprobados, incluida una abstención negativa |
| Readiness real | HTTP 200; knowledge ready; todos los checks true |
| Backend completo | 152 pruebas aprobadas, incluidas Fases 1–4 y 21 nuevas de Fase 5 |
| Frontend completo | 26 pruebas aprobadas |
| npm run build | Correcto; advertencia anterior de bundle de 783,12 kB |
| Sintaxis Python | 59 archivos correctos, excluyendo el entorno virtual |
| Sintaxis JavaScript | 16 archivos de src/tests correctos |
| git diff --check | Código 0; sólo avisos LF/CRLF de Git |
| check desde raíz y backend | Misma generación oficial, ready |

Hay una advertencia de deprecación de Chroma para Python
3.16 futuro; se trabaja con el entorno Python actual, sin alterar librerías por
esa advertencia.
