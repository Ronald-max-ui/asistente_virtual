# Fase 9C — Personalización de una instalación

Implementada sin multi-tenant, editor de prompts ni upload de VRM. Se conservan políticas comerciales, consentimiento, precios/campañas, sesiones, leads/vouchers, SSE y permisos de las fases aprobadas. No se añadieron dependencias.

## Configuración disponible

Apariencia contiene **Identidad**, **Asistente**, **Kiosk** y **Vista previa**. Nombre (120 caracteres), logo, favicon, color `#RRGGBB`, mensaje inicial de texto plano (500 caracteres), avatar instalado, voz y entrada escrita kiosk. Guarda explícitamente con `If-Match`; un registro modificado devuelve 409. Upload valida el archivo pero no activa el recurso: debe guardarse la selección. El panel conserva borradores en memoria y no almacena credenciales administrativas en storage.

`settings` de la base comercial sigue siendo fuente única. `VoiceService` obtiene la voz efectiva; `BrandingService` valida/provisiona archivos; repositorios contienen SQL. `AvatarService` proyecta exclusivamente campos públicos. El frontend no contiene copias editables de settings ni acceso a SQLite.

## API pública y cache

`GET /api/config` amplía de manera compatible:

```json
{
  "assistant": {
    "name": "Lía",
    "initial_message": "",
    "primary_color": null,
    "logo_url": null,
    "favicon_url": null
  },
  "avatar": {"id": "lia_original", "name": "Lía Original", "url": "/static/avatars/lia_original.vrm", "thumbnail_url": null, "description": ""},
  "voice": {"provider": "edge", "voice_id": "es-PE-CamilaNeural", "rate": "+10%", "pitch": "+0Hz", "volume": "+0%", "enabled": true, "status": "ready"},
  "features": {"kiosk_text_enabled": false},
  "visual": {"logo_url": null, "favicon_url": null, "primary_color": null, "initial_message": "", "kiosk_text_enabled": false}
}
```

`visual` se mantiene como proyección de compatibilidad del mismo registro, no como otra fuente editable. No hay claves, notas, credenciales ni rutas de disco. ETag cambia con contenido público/archivo avatar; logos, favicons y miniaturas usan revisiones determinísticas por archivo. El cargador VRM conserva su URL versionada mediante ETag. Config responde 304 cuando corresponde. Assets inmutables: caché anual; administración/conversaciones: no-store.

El frontend aplica nombre al título, encabezado y etiquetas accesibles, texto inicial mediante textContent y color mediante variables CSS. Elige texto negro/blanco por máxima relación de contraste, manteniendo el color elegido. Logo fallido se oculta; favicon conserva el fallback local si no se configura. Avatar fallido no cambia la base ni bloquea conversación. No se modifica el system prompt con el mensaje inicial ni se interpreta contenido como código.

## Branding y seguridad

Registro nuevo `branding_assets` en commercial.sqlite3 (schema 3): id, propósito, nombre interno único, MIME, SHA-256, ancho/alto, created_at y created_by. Archivos en el directorio privado `branding/` hermano de la base comercial. No se sirve storage completo.

- PNG/JPEG/WebP: firma, MIME y extensión coherentes, verificación y decodificación real, imagen estática; normalización elimina metadatos.
- Máximo 2 MiB de archivo/imagen normalizada, 2048 px por dimensión y 4 millones de píxeles. Request multipart máximo 3 MiB.
- Favicon cuadrado de hasta 512 px, normalizado a PNG.
- Nombres UUID generados por servidor; rechazo de traversal, doble extensión, corrupción, SVG y URLs externas.
- Escritura atómica y alta en registro; limpieza si falla persistencia. Ante desconexión, una operación acotada termina íntegramente o se limpia; una carga confirmada sin seleccionar permanece visible para administración.
- Endpoint público únicamente por nombre registrado, MIME conocido, nosniff, CSP restrictiva y caché immutable. No acepta rutas arbitrarias.

Endpoints adicionales:

| Endpoint | Permiso/uso |
|---|---|
| GET /api/admin/branding-assets | settings.read |
| POST /api/admin/branding-assets | settings.write + CSRF; multipart purpose/file |
| GET /static/branding/{filename} | imagen pública ya aprobada |
| GET /api/admin/voices | settings.read |
| POST /api/admin/voice-preview | settings.write + CSRF; parámetros tipados, frase fija |

Permisos existentes reutilizados; selección de avatar utiliza avatars.write. APIs de settings/avatares y controles HTTP existentes se conservan. Preview tiene 5 solicitudes por minuto y actor, rate administrativo por IP y cupo global de IA; uploads comparten cupo de uploads. No hay audio persistido ni texto libre de preview.

## Voz

Lista explícita: Camila (es-PE-CamilaNeural), Alex (es-PE-AlexNeural), Dalia (es-MX-DaliaNeural). Identificadores documentados en [Microsoft Speech](https://learn.microsoft.com/azure/cognitive-services/speech-service/language-support?tabs=tts); disponibilidad futura de Edge no se garantiza.

Provider fijo edge; rate y volume con signo de -50% a +50%, pitch de -100Hz a +100Hz, enabled booleano. No SSML ni claves arbitrarias. Parámetros llegan a Edge Communicate.

Una migración inicial conserva TTS_VOICE/TTS_RATE si voice está vacío. Una elección existente nunca se sobrescribe. Una voz heredada fuera de lista queda preservada, con advertencia y texto disponible; el administrador debe elegir explícitamente. Cada turno captura una snapshot al comenzar: cambiar voz no mezcla síntesis en curso. Deshabilitada/invalidada/fallo de proveedor produce respuesta escrita y mantiene políticas/orden de acciones aprobados, sin elegir voz aleatoria.

Probar voz usa exclusivamente “Hola. Estoy lista para ayudarte.”. Audio en memoria, timeout, cleanup de Blob URL y cancelación de reproducción al navegar/cerrar sesión; respuestas tardías de preview se descartan. No se usa Three.js en preview administrativo.

## Avatar

Registros existentes son compatibles; se añaden thumbnail_url opcional y description (500 caracteres). Tarjetas muestran miniatura/fallback, nombre y selección activa. Operador instala VRM aprobado; panel selecciona. Archivo original intacto.

Inventario real: **17.729.200 bytes, GLB 2, 3 mallas, 17 primitives/materiales, 29 texturas, 456 targets sumados por primitive, texturas hasta 2048×2048, sin imágenes externas**. Extensiones KHR_texture_transform, KHR_materials_unlit, VRMC_vrm, VRMC_springBone y VRMC_materials_mtoon. Detalle en fase-9c-avatar.json. `inspect_avatar.py` es read-only y NO un validador suficiente de modelos hostiles.

Para upload futuro faltan validación completa de accessors/buffers, límites de vértices/targets/resources, extensiones permitidas, rechazo de referencias externas, decodificación acotada de texturas y prueba aislada de render/compatibilidad/licencia. No se añade un endpoint inseguro de VRM.

## Auditoría y backup

settings.save guarda before/after filtrado de nombre, logo/favicon, color, mensaje, avatar y parámetros de voz. Upload registra evento sin binario; selección de avatar conserva auditoría existente. Nunca passwords, tokens, secretos o archivos en log.

`backup_personalization.py` usa SQLite Backup API y copia imágenes inmutables referenciadas por el snapshot; manifiesto con SHA-256, verificación de SQLite/FK y registro. Incluye usuarios/auditoría comercial. Falla y limpia destino nuevo ante asset faltante/inconsistente. `--check` verifica sin restaurar. Runtime/vouchers conservan backup independiente. Instrucciones de restauración detenida y permisos en operacion-produccion.md. No se borra automáticamente ningún asset ni dato comercial.

## Pruebas y evidencias

- Backend completo: **238 pruebas**, incluyendo 12 nuevas de personalización/seguridad/voz/backup.
- Frontend: **58 pruebas**; URLs seguras, contraste, aplicación dinámica, CSRF/multipart, If-Match y cleanup.
- Admin Chrome E2E: **48 comprobaciones** en DB temporal, incluido logo/favicon reales, guardar identidad/voz, ETag, reload público **sin otro build**, conversación nueva con voz seleccionada, precios/campañas efectivos, permisos y revisión de voucher.
- Public Chrome E2E: **18 comprobaciones, 3 rondas**, con build temporal y CSP real; avatar fallback, voz/texto, cancelación, errores, lead/voucher y reset.
- Voice E2E: **5 escenarios** HTTP/SQLite + adaptador sintético y parámetros del SDK.
- Edge real: 2 muestras sin PII; Camila 19.440 bytes/1547 ms, Alex 22.752 bytes/1457 ms. Audio no guardado. Muestras de conectividad, no garantía de producción.
- Instalación limpia: **12 pasos aprobados**, pip, pip check, npm ci, migración dos veces, modelo local provisionado, índice real temporal/evaluación, build, pruebas de personalización y readiness/prewarm.
- Producción/backup administrativo: **9 comprobaciones**. Backup branding: integridad, usuarios/auditoría, hash, ausencia de archivos y tampering cubiertos en regresiones temporales.
- RAG: ready, 66 chunks/384 dimensiones, evaluación **12 casos** aprobada. No regenerado el índice oficial.
- Build, Python/JavaScript, secret scan y git diff --check aprobados. Three.js conserva advertencia de chunk de 610,23 KB ya existente.

Reportes: fase-9c-admin-e2e.json, fase-9c-public-e2e.json, fase-9c-voice-e2e.json, fase-9c-real-voice.json, fase-9c-clean-install.json, fase-9c-production-validation.json, fase-9c-rag-evaluation.json, fase-9c-syntax.json y fase-9c-secret-scan.json. Captura de Apariencia: fase-9c-appearance.png.

## Archivos y pendientes

Nuevos: domain/voice.py; services/voice_service.py, branding_service.py, public_assets.py; persistence/branding_repository.py; api/personalization.py; backup_personalization.py; inspect_avatar.py; voice_e2e.py; tests/test_phase9c.py; static/admin/appearanceScreen.js; frontend ui/branding.js y tests/personalization.test.js.

Modificados: composición/providers/conversation/TTS; modelos/repositorios/auditoría; AvatarService/CommercialService; server/security HTTP; adminClient/admin/commercialScreens/CSS; main/HTML/CSS/accesibilidad públicos; fixtures/E2E, validación de instalación, tres expectativas antiguas de pruebas, ejemplos de entorno y documentación operativa. No cambia PricingService, reglas de pago/campañas, esquema de runtime ni RAG.

Pendientes antes de comercializar: escoger branding institucional final; verificar voces en red/equipo final; probar tablet/móvil/kiosk prolongado; practicar recuperación de backup en una instancia aislada; plan de retención de assets no seleccionados mediante una fase explícita. No se autoriza eliminación automática ni se prueba restauración destructiva. No se implementan personalidades libres ni cambio de avatar en caliente. Se detiene en Fase 9C.
