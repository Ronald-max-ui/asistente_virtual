# Fase 8 — UX y preparación operativa

## Resultado y alcance

Implementada la preparación local y operativa; no se desplegó en Internet ni se construyó panel. Se conservaron acciones estructuradas, consentimiento, catálogo/campañas, SQLite separadas, sesiones/concurrencia/idempotencia, uploads seguros, web/kiosk, info/sales y SSE. No se modificaron los Markdown ni el índice oficial, modelo, 384 dimensiones, colección lia_knowledge o 66 chunks. La instalación limpia construyó un índice **nuevo temporal**, no reemplazó el vigente.

## UX, estados y recuperación

- `ui/state.js` es la única representación del estado visible: initializing, ready, listening, processing, responding, speaking, cancelling, offline y error. Controles bloqueados durante bootstrap/turno; reconexión no libera una cancelación pendiente ni cambia una respuesta activa por un evento online duplicado.
- Entrada por texto en web y kiosk cuando `settings.kiosk_text_enabled=true`; también se ofrece como fallback si falta voz o se deniega micrófono. Reutiliza consultarAsistente → SSE → ConversationService; produce audio cuando está disponible. No hay un flujo comercial alternativo ni framework nuevo.
- Detener respuesta limpia audio/acciones y cancela backend. Cancelación antes de recibir request_id incluye invalidación y reemplazo explícito de una posible reserva; no se habilita siguiente envío antes de terminar la cancelación. Navegar invalida el turno, incluso BFCache, conservando recursos para reanudación de la página.
- Fallos de LLM/RAG/SSE son recuperables y descartan acciones. No se reenvía una respuesta SSE interrumpida después de empezar a recibir eventos. TTS fallido conserva todo el texto; subtítulos preservan orden incluso con frases sin audio. Offline detiene reconocimiento/turno; online permite continuar sin reanudarlo silenciosamente.
- Avatar/configuración WebGL defectuosos no impiden conversación. Se liberan escenas inválidas o tardías. Configuración/sesión sí requieren arranque correcto y tienen botón Reintentar conexión. Avatar seleccionado cambia en config y tras reload, comprobado con API admin aislada.
- Favicon SVG local evita el 404 implícito. Nombre desde configuración; campos backend favicon_url y kiosk_text_enabled preparados, junto a logo/color/mensaje existentes. No se introdujo editor visual ni personalización completa.
- Modales: role dialog/aria-modal, nombre accesible, labels asociados, foco inicial tras transición, trap Tab/Shift+Tab, Escape seguro y retorno de foco. Cierre desactiva backdrop inmediatamente para no interceptar el siguiente clic. Escape/backdrop no cierran un upload activo; formularios evitan doble envío y mantienen Idempotency-Key.
- Prospecto registrado conserva marcador sin PII en la pestaña y no abre otro formulario para reemplazarlo. Backend sigue autoritativo. Upload muestra envío/validación y **Comprobante recibido y pendiente de revisión**, nunca pago confirmado. Correcciones comerciales requieren futuro flujo explícito.
- Subtítulos se posicionan sobre controles variables; inputs seleccionables, foco visible y viewport estrecho verificado, sin cambiar avatar/identidad visual.

## Producción y observabilidad

KNOWLEDGE_PREWARM default opcional en development y true en production; plantilla lo activa explícitamente. Background preserva liveness; readiness 503 mientras calienta. Logs de duración/éxito/fallo sin contenido. Timeout de prewarm conserva la validación local; error local no-timeout marca conocimiento invalid y readiness 503, aunque su manifiesto sea válido. No regeneración automática.

APP_ENV inválido se rechaza. Producción rechaza HTTP/origins localhost/loopback, credenciales ausentes/placeholder/débiles, bases/índice/modelo en rutas públicas e índice no ready. CLI validate_production devuelve sólo status/tipo de error; prueba con configuración real válida y credencial admin temporal, sin imprimir secretos. Scan del build no encontró las credenciales existentes.

Eventos operativos sanitizados: startup/shutdown, ready/degraded, knowledge_stale, prewarm con duración, provider_timeout y backup_result. No se añadieron prompts, teléfonos, nombres, cuerpos de comprobantes o Authorization a logs. Retención configurable sólo como propuesta: **ningún nuevo borrado automático**.

Reverse proxy de ejemplo: HTTPS, CSP sin unsafe-eval/scripts inline, Permissions-Policy micrófono self, nosniff, anti-framing/referrer/HSTS, gzip y Brotli opcional. HTML revalida; assets hash immutable; API config/avatares conservan política F7; conversaciones/sesiones/admin no-store. Se ensayó build de producción en Chrome bajo CSP; Nginx/TLS/ACL del destino requieren nginx -t y verificación allí.

## Instalación limpia y persistencia

Ensayo completado en Python 3.14.5 / Node 24.19.0: entorno Python vacío, pip install + pip check, npm ci sin node_modules previo, migración de seis JSON, segunda migración, validador, embeddings reales, build temporal/evaluación/check de índice, build frontend y Uvicorn con readiness ready/prewarm ready. Bases, modelo e imágenes separados del entorno real. ONNX y VRM provisionados mediante copias de artefactos aprobados; no se simuló una descarga nueva de estos assets. Lock generado desde ese entorno validado.

Recuperación comprobada mediante reinicio abrupto de Uvicorn y también reinstanciación de repositorio en almacenamiento temporal: conserva sesión/credencial vigente, lead, voucher y relaciones; reset conserva lead/voucher y limpia historial. Config comercial/índice/avatar persisten como archivos/DB aprobados. No se recuperan requests/audio: tras caída abrupta vence lease de 120 s o se reemplaza explícitamente. Backups existentes usan SQLite Backup API; runtime incluye imágenes y manifiesto. Guía detalla restauración alternativa sin sobrescribir producción, frecuencia/retención propuesta y almacenamiento fuera del disco.

## Archivos de esta fase

| Área | Archivos |
|---|---|
| Arranque/config/health | backend/server.py, config.py, runtime_config.py, security/config.py, api/health.py |
| Producción/operación nuevos | backend/production.py, validate_production.py, retention_policy.py, provision_embeddings.py, verify_clean_install.py, security/frontend.py, requirements.lock.txt |
| Config pública | backend/persistence/models.py, services/avatar_service.py |
| Backups | backend/backup_commercial.py, backup_runtime.py (evento de éxito seguro) |
| Entorno/despliegue | backend/.env.example, .env.production.example; deploy/nginx.conf.example |
| Frontend | avatar-kiosk/index.html, public/favicon.svg, src/main.js, style.css, ui/state.js, ui/controls.js, ui/overlays.js, ui/modalAccessibility.js, api/client.js, api/publicConfig.js, avatar/loader.js, audio/player.js |
| Pruebas/herramientas | backend/tests/test_phase8.py, tests/e2e_app.py, tests/restart_app.py, browser_e2e.py, verify_restart.py; avatar-kiosk/tests/client.test.js, overlays.test.js, performance.test.js, publicConfig.test.js, phase8.test.js |
| Evidencia y documentación | docs/fase-8*.json, fase-8.md, operacion-produccion.md |

No dependencias directas nuevas. requirements.lock.txt fija también las transitivas del entorno limpio; requirements.txt sigue declarando dependencias del proyecto. No esquemas SQLite nuevos: settings JSON permite los nuevos campos sin alterar datos existentes.

## Pruebas y resultados

- Suite backend completa: **186 pruebas**, conserva Fases 1–7 y añade producción, prewarm, TTS/LLM, retención, caché/CSP y E2E HTTP con persistencia.
- Suite frontend: **41 pruebas**, incluye fallback sin voz/denegación, texto kiosk, estados/reconexión, cancelación temprana, foco y cleanup VRM.
- E2E Chrome web, 5 rondas: bootstrap, texto/audio, cancelar/nueva consulta, TTS/LLM fallidos, lead, pago catálogo, PNG real validado pendiente, reset, offline/online, avatar cambiado/reload. E2E build producción añade CSP, teclado/foco, upload activo y viewport 390px. Bases temporales y proveedores simulados, sin falsear reconocimiento de voz.
- Kiosk con avatar original: **50 rondas / 42.7 s**, heap muestreado ~73.5–76.0 MB y ~38.0 MB tras GC; freeze/resume y offline/online aprobados. Muestra corta, GPU de software, no prueba ausencia de leaks ni funcionamiento de varias horas en hardware final.
- Reinicio de proceso real: turno completo recuperado, stream parcial no confirmado, lease huérfano reemplazado explícitamente, credencial/lead/voucher/imagen/catálogo/avatar/índice recuperados, reintentos idempotentes y reset sin borrar información comercial. Evidencia: fase-8-restart.json.
- RAG real: **12/12 evaluaciones**, mismas fuentes/metadatos y negativas. check ready; conocimiento 9 archivos, 0 errores/advertencias.
- Benchmark simulado 5 muestras: primer texto 71.862 ms, primer audio 176.424 ms, total 448.485 ms (medianas). No comparar estos valores con proveedores reales como si fueran el mismo escenario.
- Build producción aprobado; advertencia previa de Three.js ~610 KB persiste (no regresión funcional ni ocultación de warning).
- Sintaxis Python/JavaScript y git diff --check aprobados. Escaneo de secretos del frontend aprobado. Ninguna restauración destructiva ni cambios en datos operativos reales.

## Proveedores reales

Tres consultas sintéticas sin PII con Groq/Edge-TTS; prewarm 2997.1 ms. Milisegundos desde petición salvo first token relativo a apertura del proveedor:

| Muestra | Groq first token | First text | First audio | Total | Completada |
|---|---:|---:|---:|---:|---|
| 1 | 1127.2 | 1219.0 | 2463.9 | 2489.1 | True |
| 2 | 485.0 | 574.8 | 1732.5 | 1754.9 | True |
| 3 | 468.0 | 536.5 | 1693.9 | 1726.8 | True |

3/3 completadas, sin fallos observados. No garantía/SLO de producción. Datos técnicos en fase-8-real-providers.json, sin prompts/audio ni credenciales.

## Pendientes antes de comercializar

Checklist física para Chrome Android, Safari iOS, desktop y equipo kiosk; prueba 3+ horas y memoria/GPU real; TLS/Nginx/permisos/firewall del host; restauración ensayada en host alternativo; aprobación de retención/legalidad y proceso humano de revisión de vouchers. Panel/login/roles/CSRF con cookies siguen posteriores. No se avanzó al panel.

Guía detallada: [operacion-produccion.md](operacion-produccion.md). Evidencia: fase-8-clean-install.json, fase-8-production-validation.json, fase-8-production-e2e.json, fase-8-browser-e2e.json, fase-8-kiosk-soak.json, fase-8-rag-evaluation.json, fase-8-benchmark.json, fase-8-real-providers.json y fase-8-validation.json.

Lock: 107 paquetes del entorno limpio.
