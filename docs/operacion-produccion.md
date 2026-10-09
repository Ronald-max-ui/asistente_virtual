# Operación inicial de Lía

## Instalación y despliegue de una instancia

Verificado en Windows con Python 3.14.5 y Node 24.19.0. Usar estas versiones para reproducir la validación. Linux requiere su propia verificación de wheels/permisos. No se requiere Docker.

Arquitectura: Internet → reverse proxy HTTPS → frontend estático de Vite + Uvicorn ligado a loopback con **1 worker** → SQLite comercial y runtime privados, Chroma/modelo privados, comprobantes privados. La cola de sesiones y el rate limiter siguen siendo de una instancia. No aumentar workers sin introducir coordinación distribuida.

Desde la raíz de una instalación nueva:

```powershell
python -m venv backend/venv
backend/venv/Scripts/python.exe -m pip install -r backend/requirements.lock.txt
backend/venv/Scripts/python.exe -m pip check
npm --prefix avatar-kiosk ci
```

Crear `backend/.env` a partir de `.env.production.example`, reemplazando las credenciales **privadamente**, sin sobrescribir un entorno existente. No copiar secretos al frontend ni utilizar VITE_* para credenciales. Establecer dominio HTTPS real y permisos privados del almacenamiento. Por defecto las rutas se resuelven desde backend. Mantener `backend/storage` fuera del document root; el proxy sirve únicamente `avatar-kiosk/dist` y `/static` autorizado. En Windows restringir ACL a la cuenta del servicio y operadores de backup; en Linux directorios privados y cuenta dedicada. No publicar `.env`, backups, Markdown originales, JSON de migración, bases o comprobantes.

Provisionar el archivo VRM original aprobado en `backend/static/avatars/lia_original.vrm`; no utilizar un archivo público cualquiera ni sustituirlo sin revisión. El original validado tiene 17,729,200 bytes y SHA-256 `111229d8e6d45bca15422279bbb34a92fcd9bdb3f12236cf81a107c93f4a63e4`.

Provisionar ONNX: copiar el paquete aprobado `backend/storage/embedding_models` al almacenamiento privado nuevo, o descargar explícitamente el mismo modelo mediante el siguiente comando. El ensayo limpio usó **copias de los artefactos aprobados**, no una descarga nueva del modelo/VRM.

```powershell
backend/venv/Scripts/python.exe -B backend/provision_embeddings.py
backend/venv/Scripts/python.exe -B backend/migrate_commercial.py
backend/venv/Scripts/python.exe -B backend/validate_knowledge.py
backend/venv/Scripts/python.exe -B backend/rebuild_knowledge.py --build
backend/venv/Scripts/python.exe -B backend/rebuild_knowledge.py --check
backend/venv/Scripts/python.exe -B backend/rebuild_knowledge.py --evaluate
backend/venv/Scripts/python.exe -B backend/validate_production.py
npm --prefix avatar-kiosk run build
```

La migración es idempotente y no reemplaza cambios administrativos. Los JSON son exclusivamente una fuente de migración. No usar este procedimiento para sobrescribir bases existentes. `provision_embeddings.py` sólo prepara el caché; build/promoción del índice son explícitos. Volver a `CHROMA_LOCAL_FILES_ONLY=true` para runtime. Runtime inicializa su esquema automáticamente, sin borrar datos.

Backend, desde `backend/`:

```powershell
venv/Scripts/python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log
```

Usar supervisor del sistema para reinicio y parada ordenada. Configurar TLS y `deploy/nginx.conf.example` en el host destino, reemplazando dominio/certificados/root. Ejecutar **nginx -t** allí antes de activar: Nginx/TLS del servidor final no se desplegaron en este workspace. No confiar headers reenviados de Internet directamente; sólo del proxy local. El proxy conserva la IP real para rate limiting. SSE usa buffering/cache desactivados y timeout mayor que STREAM_TIMEOUT.

Producción debe usar mismo origen; dejar VITE_API_URL sin secreto y, normalmente, sin valor. Para separar dominios se deben revisar CORS y `connect-src` explícitamente. La CSP no permite eval ni scripts inline. Los estilos inline siguen necesarios por los modales existentes. Micrófono sólo self. El ejemplo configura nosniff, anti-framing, referrer policy, HSTS y gzip. Brotli es opcional si el módulo está instalado. HTML/favicon: revalidación; assets hash: 1 año/immutable; config: ETag/no-cache; avatar: URL versionada; chat, sesiones y admin: no-store. No poner un CDN con caché indiscriminada delante de API/SSE.

## Prewarm, readiness y recuperación

Development: opcional; production: default true, activarlo explícitamente con KNOWLEDGE_PREWARM=true. Tiene coste real de carga ONNX/Chroma: ~3 segundos en la muestra de esta máquina, no una garantía. Se ejecuta en background; `/health/live` sigue respondiendo. Mientras calienta, readiness es 503; después se valida el almacenamiento/configuración/conocimiento. Timeout de prewarm no convierte por sí solo un índice válido en inválido; `prewarm.status=failed` señala degradación. Una excepción local no-timeout durante prewarm marca knowledge invalid y readiness 503, incluso si el manifiesto aún es válido. Conocimiento realmente inválido siempre falla readiness; configuración production rechaza índice inválido o stale al arrancar. No se reconstruye ni cambia el conocimiento durante prewarm.

Monitorear `/health/live` y `/health/ready` sin rutas/PII. Proveedores son not_probed: una caída externa no inutiliza liveness. Eventos seguros: startup/shutdown, ready/degraded, knowledge_prewarm_ready/failed con duración, provider_timeout, errores por tipo y resultado de backup. Readiness muestra stale sin contenido; no almacenar respuestas de health con información interna añadida. No activar DEBUG de SDK ni access logs que incluyan secretos/PII. Correlación es request_id, nunca credencial de sesión.

Tras reinicio, bases comercial/runtime conservan campañas, configuración, sesión vigente y su historial acotado, lead y voucher. La credencial de la pestaña permite recuperar la misma sesión; no se restaura audio ni stream. Parada abrupta deja una reserva que vence en SESSION_REQUEST_LEASE_SECONDS (120 s); reemplazo explícito invalida operaciones anteriores. No reejecutar acciones viejas ni reintentar operaciones comerciales automáticamente. Reset limpia conversación, **no** elimina prospectos/comprobantes ni su asociación.

Errores de LLM/RAG/SSE: mensaje recuperable, acciones pendientes descartadas. TTS fallido: respuesta escrita completa; continuar. Sin reconocimiento o permiso de micrófono: texto, sin bucle de permisos. Sin avatar/WebGL: conversación disponible. Offline detiene interacción/audio; online recupera controles cuando terminó cancelación, sin reanudar el turno viejo. Si el arranque no completó configuración/sesión, usar Reintentar conexión.

## Backups y retención

Ejemplos: destinos nuevos en disco distinto, accesibles sólo a operadores:

```powershell
backend/venv/Scripts/python.exe -B backend/backup_commercial.py --output E:/lia-backups/commercial_FECHA.sqlite3
backend/venv/Scripts/python.exe -B backend/backup_runtime.py --output E:/lia-backups/runtime_FECHA
```

Se usa SQLite Backup API, no copia ordinaria de bases abiertas. Runtime incluye DB, imágenes relacionadas y manifiesto con hashes. Sugerencia inicial: diario y antes de despliegues/cambios comerciales importantes; 7 diarios + 4 semanales + 6 mensuales **como propuesta a aprobar y configurar externamente**, copias cifradas fuera del mismo disco y acceso restringido. Verificar integrity_check y hashes, y ensayar restauración en almacenamiento **nuevo**, nunca sobre producción en marcha. El backup no sustituye una política legal de conservación.

Restauración: detener backend, validar copia en directorio alternativo privado, provisionar imágenes del paquete/manifiesto junto a runtime, apuntar COMMERCIAL_DB_PATH/RUNTIME_DATABASE_PATH a las copias verificadas, verificar catálogo y asociaciones, provisionar avatar/modelo y reconstruir/verificar conocimiento desde fuentes aprobadas; readiness antes de volver a publicar. No restaurar DB aislada de sus imágenes. No se ejecutaron restauraciones destructivas. Conservar fuentes/manifiesto/modelo para regenerar Chroma; si se archiva una generación, hacerlo parada/snapshot consistente, no copiar SQLite abierto indiscriminadamente.

Configuración técnica de retención, **sin nuevo borrado automático**:

| Datos | Variable/propuesta | Condición |
|---|---|---|
| Conversación | RETENTION_SESSIONS_DAYS=2 | Propuesta de purga futura; expiración F3 ya limpia turnos de sesiones vencidas |
| Prospectos | RETENTION_LEADS_DAYS vacío | Requiere decisión comercial/legal; nombres, WhatsApp, programa/modalidad, notas/origen |
| Comprobantes | RETENTION_VOUCHERS_DAYS vacío | Asociación/importe oficial/status; no equivale a conciliación |
| Imágenes | Vinculadas a voucher | Nunca separar una eliminación de su relación y backups |
| Idempotencia | RETENTION_IDEMPOTENCY_DAYS=2 | Propuesta futura, no purgar claves de operaciones recuperables |
| Logs | RETENTION_LOGS_DAYS=30 | Propuesta para rotación del supervisor, sin prompts, teléfonos ni tokens |

No hay jobs de purga comercial nuevos. Reset no es eliminación de datos personales. Determinar retención, base legal y procedimiento de eliminación antes de comercialización.

## Ensayos reproducibles

```powershell
backend/venv/Scripts/python.exe -B backend/verify_clean_install.py --output docs/fase-8-clean-install.json --lock-output backend/requirements.lock.txt
backend/venv/Scripts/python.exe -B backend/verify_restart.py --output docs/fase-8-restart.json
backend/venv/Scripts/python.exe -B backend/browser_e2e.py --production-build --rounds 5 --output docs/fase-8-production-e2e.json
backend/venv/Scripts/python.exe -B backend/browser_e2e.py --mode kiosk --real-avatar --duration-seconds 10800 --output docs/kiosk-soak-local.json
```

La instalación crea entorno Python y proyecto Node temporales, instala paquetes desde cero, copia artefactos aprobados, migra dos veces, construye/evalúa Chroma real, compila e inicia backend/readiness. No copia bases reales. requirements.lock.txt fue generado por pip freeze del entorno limpio cuya instalación/pip check/índice fueron validados. No agregar dependencias manualmente allí; actualizar mediante ensayo limpio revisado.

E2E usa Chrome real, HTTP/servicios/repositorios/validación de imagen reales y proveedores simulados. DBs privadas temporales, fixture PNG válido, audio WAV decodificable. Incluye cancelación, errores, datos/pago desde catálogo, upload pendiente, reset, offline/online, foco/Escape y cambio de avatar. No simula que SpeechRecognition existe; reporta disponibilidad nativa sin validar dictado físico. El fixture E2E jamás es una aplicación de producción.

Soak: ejecutar 3+ horas en el equipo final, repetir ciclos, comprobar suspensión/reanudación, cancelar en varios momentos, alternar error/red, variar info/sales y estados. Herramienta guarda muestras de heap durante el ensayo; detener si crece de forma sostenida tras GC. El ensayo automático corto **no prueba ausencia de leaks**. Complementar con DevTools (heap snapshots/listeners/AudioBuffers/WebGL) y consumo del proceso/GPU/temperatura del sistema; observar memoria después de periodos de reposo, no sólo picos.

## Checklist física previa a comercializar

Para Chrome desktop, Chrome Android, Safari iOS y equipo kiosk final registrar versión/OS/resultado, sin inventar soporte:

- HTTPS y certificado; carga inicial/caché/reload, avatar original y fallback defectuoso; config/ETag/cambio de avatar.
- Autoplay tras gesto real; AudioContext resume/auriculares/altavoz; audio ordenado, subtítulos completos si TTS falla.
- SpeechRecognition realmente disponible; permiso permitido/denegado, ausencia de micrófono, sin pedirlo en bucle; texto y envío por Enter.
- Detener antes de headers, durante Groq, TTS y reproducción; siguiente pregunta; offline/online sin acciones viejas.
- Modales por teclado y lector de pantalla: foco inicial, Tab/Shift+Tab, Escape, foco de vuelta; upload activo no cierra por Escape.
- Mobile: teclado virtual, orientación, safe area, scroll del modal, zoom; no atribuir la emulación de 390px a una prueba física.
- Web: lead doble clic/retry sin duplicado; voucher JPG/PNG/WebP válido, archivo erróneo, pendiente de revisión; nunca Pago confirmado por imagen.
- Kiosk: texto configurable, voz y atracción, formularios/pagos inline deshabilitados, varias horas de funcionamiento, ocultar/reanudar.
- Reinicio del servicio con sesión/lead/voucher existentes en entorno aislado; health, base comercial, índice y avatar; backup/restauración alternativa.

Pendientes de entorno: Nginx/TLS/ACL/firewall del host definitivo, Linux si se elige, hardware real y navegadores móviles, seguimiento prolongado y proceso administrativo de revisión de vouchers. ADMIN_API_TOKEN sigue temporal: HTTPS y acceso restringido; login/roles/cookies y CSRF asociado corresponden al futuro panel, no a esta fase.


## Lía Admin — Fase 9A

La identidad nominal usa cookie HttpOnly y sesión server-side con RBAC/CSRF. Preparar `/admin/` bajo el mismo origen HTTPS que la API y aplicar la actualización de `deploy/nginx.conf.example`. Crear el primer superadmin con `backend/create_admin.py` desde terminal interactivo; nunca pasar contraseñas por argumentos ni configurar usuarios por defecto. La plantilla de producción desactiva `ADMIN_LEGACY_TOKEN_ENABLED` y deja `ADMIN_API_TOKEN` vacío. Habilitar Bearer sólo para compatibilidad explícita de herramientas, con plan de retiro.

Los backups comerciales ahora incluyen usuarios, roles, sesiones y audit log; los runtime incluyen revisiones y audit log de vouchers. Son datos personales y material sensible: proteger ACL/cifrado/retención y verificarlos mediante `verify_admin_backup.py` y el manifiesto runtime. Tras restaurar, con servicio detenido y antes de exponer tráfico, ejecutar `create_admin.py --database <ruta-privada> --revoke-all-sessions`; una restauración podría recuperar sesiones antiguas. No eliminar automáticamente auditoría o usuarios. Guía completa: [fase-9a.md](fase-9a.md).


## Personalización de la instancia (Fase 9C)

Apariencia administra identidad, logo, favicon, color, mensaje inicial, selección de avatar y voz. La base comercial es la fuente única; recargar el navegador aplica branding y una conversación nueva captura la voz vigente. Las variables TTS_VOICE/TTS_RATE sólo inicializan una configuración de voz aún vacía. No sobrescriben una elección guardada.

Los archivos de branding viven en `commercial.sqlite3` → registro `branding_assets`, y en el directorio privado hermano `branding/`. Sólo el endpoint `/static/branding/{nombre_generado}` sirve imágenes registradas. El reverse proxy existente dirige `/static/` al backend; **no montar storage como directorio público**. No cambiar CSP: admite imágenes propias y audio blob; no requiere unsafe-eval. Archivos inmutables tienen caché anual; config usa ETag y revalidación; operaciones admin siguen no-store.

Backup comercial con branding (sustituye el backup de sólo DB para recuperaciones completas):

```powershell
backend/venv/Scripts/python.exe backend/backup_personalization.py --database backend/storage/commercial.sqlite3 --output D:/backups/lia/config-20261009
backend/venv/Scripts/python.exe backend/backup_personalization.py --check D:/backups/lia/config-20261009
```

Destino nuevo, privado y fuera del directorio de assets. SQLite Backup API obtiene un snapshot consistente; luego copia las imágenes inmutables que ese registro referencia, comprueba SHA-256, integridad y claves foráneas. Incluye usuarios y auditoría. El backup runtime/vouchers permanece independiente. Copiar respaldos fuera del disco, proteger acceso y verificar periódicamente; no se añade borrado automático.

Restauración: detener Uvicorn y escrituras administrativas; verificar el manifiesto; conservar respaldo previo; restaurar `commercial.sqlite3` y `branding/` del **mismo snapshot**, con permisos privados; no conservar WAL/SHM viejos al sustituir una base detenida. Iniciar, comprobar readiness, login y assets seleccionados. No restaurar automáticamente ni sobre una base abierta. Avatares instalados y modelo/índice mantienen su procedimiento de provisión; no están embebidos en este backup de branding.

El despliegue limpia dependencias, inicializa DB, provisiona VRM aprobado/modelo local e índice, ejecuta build una vez. Personalización posterior no requiere compilación ni regeneración RAG. `verify_clean_install.py` valida este flujo en directorio temporal y añade pruebas de personalización/backup. SVG subido y VRM subido no se admiten. Inventario read-only de un VRM: `inspect_avatar.py archivo.vrm` no constituye autorización para aceptar modelos no confiables.

## Operación comercial (Fase 9D)

La migración runtime 2→3 es aditiva: conserva captura y comprobantes, inicializa tracking Nuevo y timeline de creación. Respaldar antes de actualizar el servicio; iniciar y comprobar readiness. No es necesario regenerar RAG ni recompilar por cada cambio operativo.

El backup runtime consistente incluye seguimiento, asignaciones, actividades, notas y tareas, además de vouchers/auditoría/idempotencia. Verificación adicional read-only:

```powershell
backend/venv/Scripts/python.exe backend/verify_runtime_backup.py D:/backups/lia/runtime-20261009
```

No copiar SQLite abierta directamente ni restaurar durante pruebas. Restauración con servicio detenido y DB/vouchers del mismo snapshot verificado; conservar copia previa y permisos privados, retirar WAL/SHM antiguos únicamente en el procedimiento de base detenida. Comercial/branding mantiene su backup independiente.

Notas, timeline y tareas son datos personales administrativos. Variables RETENTION_LEAD_ACTIVITY_DAYS y RETENTION_LEAD_TASKS_DAYS sólo definen propuestas técnicas; no borran datos. No hay mensajes externos ni conversión automática por aprobación de voucher. Guía de API, estados, roles y límites: [fase-9d.md](fase-9d.md).
