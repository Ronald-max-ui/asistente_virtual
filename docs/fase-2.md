# Fase 2: seguridad de API y operación

Se conservan acciones estructuradas, ConsentService, ActionService, PricingService,
CommercialService, repositorios, SQLite, campañas y configuración pública del avatar.
No se implementan panel, login, roles, Redis, PostgreSQL ni Fase 3.

## Arquitectura y archivos

`backend/security/config.py` define límites y configuración; `rate_limit.py` ofrece
el contrato reemplazable por Redis y el contador en memoria; `http.py` implementa
middleware **ASGI puro** (sin buffer de respuesta SSE), headers, CORS, límites de
cuerpo, capacidad, correlación y errores. `inputs.py` contiene contratos Pydantic.
`auth.py` centraliza el Bearer administrativo temporal; `logging.py` emite únicamente
campos permitidos; `providers.py` acota esperas y cierra streams.
`storage.py` reutiliza escritura privada para prospectos y comprobantes. Se retiran
también logs de payloads SSE, IDs de sesión y argumentos de modales del frontend.

Se modifican `server.py` para integrar estos controles, `config.py`, los contratos
de acciones/LLM, modelos comerciales y proveedores Groq/RAG/TTS. Se añade
`services/voucher_service.py`, `services/health_service.py`, el backup administrativo,
`.env.example`, dependencia explícita Pillow y pruebas. El SQL continúa exclusivamente
en `persistence/sqlite_repository.py`. No se reescribe el flujo comercial.

## Límites por defecto

| Grupo | Ventana móvil por IP de conexión |
|---|---|
| `/chat` + `/chat/stream`, compartido | 30 / 60 segundos |
| `/api/leads` | 5 / 300 segundos |
| `/api/vouchers` | 5 / 300 segundos |
| `/api/admin/*` | 60 / 60 segundos, incluidos intentos fallidos |
| `/reset-session` | 10 / 60 segundos |
| `/api/config` + `/api/media` | 120 / 60 segundos |
| `/static/*` | 60 / 60 segundos |
| `/health`, `/health/live`, `/health/ready` | Sin rate limiting |

Los límites incluyen solicitudes inválidas para evitar evasión por errores de
validación. 429 incluye `Retry-After`. El store admite 10 000 claves activas,
rechaza nuevas claves al agotarse y elimina entradas vencidas; no expulsa contadores
activos. Reiniciar borra contadores. **Operar con un worker** hasta introducir un
store distribuido: varios procesos multiplican los límites. Ajustar ventanas para
redes NAT/kioscos compartidos. No usar ID de sesión controlado por cliente como IP.

Hay como máximo ocho solicitudes IA y cuatro uploads activos por proceso. Es un
límite de recursos, no el control de concurrencia por sesión de la futura Fase 3.
Se liberan al finalizar, fallar o cancelar. Tamaños reales se cuentan antes del
parser, incluso sin Content-Length o con transferencia chunked. No se admiten
Content-Encoding comprimidos. Headers de entrada: 16 KiB máximo dentro de ASGI;
el proxy/servidor también debe limitar headers antes de construir el scope.

| Entrada | Límite |
|---|---|
| Mensaje | 2 000 caracteres |
| Sesión | 128; caracteres de identificador, sin controles |
| Nombre | 120, sin caracteres de control |
| WhatsApp | 24, formato de dígitos/separadores; obligatorio en lead |
| Notas | 2 000 |
| Programa/comercial | 120; conceptos/variantes de solicitudes, 64 |
| Archivo original | 128; nombre seguro y una extensión admitida |
| Acciones | 8 por respuesta; 4 096 caracteres por argumentos de herramienta |
| Texto generado | 16 000, también en streaming |
| JSON/formularios ordinarios | 64 KiB |
| Administración | 256 KiB |
| Archivo y archivo normalizado | 5 MiB |
| Request multipart de voucher | 6 MiB, incluyendo campos/overhead |
| Imagen | 12 megapíxeles; lado máximo 6 000; sólo un frame |

Los modelos administrativos también acotan IDs, nombres y listas; las cantidades
monetarias conservan decimales exactos, hasta diez dígitos y dos decimales. Las
tarifas nunca se redondean ni se toman de un importe del modelo.

## Upload

1. Validar campos y consultar PricingService; `free` y `pending` bloquean el cobro.
2. Exigir coincidencia del monto declarado con la tarifa; éste nunca autoriza el monto.
3. Leer por bloques de 64 KiB hasta el máximo. Cerrar UploadFile incluso ante error.
4. Comprobar firma JPEG/PNG/RIFF-WebP, MIME y extensión coherentes. Rechazar traversal,
   dobles extensiones, formatos ajenos, archivos corruptos y animaciones.
5. Pillow abre sólo los tres formatos, comprueba dimensiones antes de cargar píxeles,
   ejecuta `verify()` y luego decodifica íntegramente con `load()`. Las advertencias
   de bomba de descompresión se convierten en rechazo. Se vuelve a codificar la imagen,
   sin metadatos, EXIF ni contenido añadido; el buffer de salida también está acotado.
6. Consultar nuevamente la tarifa después del procesamiento; un cambio devuelve 409.
7. Guardar imagen y metadatos bajo UUID completo generado por servidor, extensión
   derivada del formato, temporales privados, fsync y renombrado. Si falla la operación,
   eliminar temporales y archivos parciales. Nada se guarda bajo `/static`.

No se usa el nombre del navegador para construir destinos. No hay OCR, scripts ni
ejecución del contenido. Se aplica la orientación EXIF antes de retirar metadatos.
Reencodificar puede modificar compresión: revisar legibilidad de comprobantes móviles.
Dos archivos no constituyen una transacción de filesystem: el cleanup cubre excepciones,
pero una caída abrupta del proceso puede dejar una imagen huérfana; conciliación futura.
Los decodificadores nativos tienen superficie de ataque: mantener Pillow actualizado;
aislamiento en proceso/contenedor es un endurecimiento adicional para alta exposición.

## CORS y headers

Usar `ALLOWED_ORIGINS`, lista exacta separada por comas. Ya no se usa `CORS_ORIGINS=*`.
Desarrollo admite explícitamente localhost:5173 y 127.0.0.1:5173. Producción exige
`APP_ENV=production`, orígenes HTTPS y ninguna ruta/slash final/credencial/wildcard.
Origen no autorizado: 403, incluso antes de escribir formularios. CORS no es autenticación:
curl/bots sin Origin requieren igualmente límites y, en administración, el token.
No se permiten credenciales cookie CORS; Bearer usa Authorization explícito. Preflight
admite GET/POST/PUT y headers Content-Type, Authorization y X-Request-ID. Expone
X-Request-ID y Retry-After. Los errores reciben también CORS para orígenes permitidos.

El backend entrega nosniff, DENY/frame-ancestors none, no-referrer, Permissions-Policy
con micrófono self y cámara/geolocalización/pagos deshabilitados. HSTS sólo cuando ASGI
reconoce HTTPS. CSP del backend es `default-src 'none'`: sus respuestas son API/assets,
no el documento del frontend. **No bloquea los fetch de VRM, audio o SSE** del documento
Vite. Swagger/ReDoc tienen una excepción sólo de desarrollo; docs/OpenAPI se deshabilitan
en producción. CSP no sustituye autenticación.

El hosting separado del frontend debe enviar headers propios. Plantilla compatible
con el build actual, sustituyendo el origen API real (no copiar el placeholder):

```text
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' blob: https://API_ORIGIN; img-src 'self' data: blob: https://API_ORIGIN; media-src 'self' blob: https://API_ORIGIN; worker-src 'self' blob:; font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'
Permissions-Policy: microphone=(self), camera=(), geolocation=(), payment=()
```

Los estilos inline existentes requieren la excepción de estilos; no se autoriza eval
ni JavaScript inline en el frontend. Vite HMR de desarrollo requiere su websocket local
y política de desarrollo aparte; no activar HMR en producción. Estos headers del hosting
deben validarse en el navegador real antes del despliegue.

## Administración, secretos, CSRF y logs

`security/auth.py` compara hashes SHA-256 de longitud fija con compare_digest, acota
el candidato y no registra credenciales. Sin token configurado: 503; token incorrecto
o ausente: 401. Mantener ADMIN_API_TOKEN privado, aleatorio, largo y sólo en backend;
En producción se rechaza un token configurado con menos de 32 caracteres, más de
512 o que conserve el placeholder. Rotarlo reemplazando el secreto del despliegue.
Este actor compartido **no proporciona
identidad, roles ni revocación individual**. Preparado como dependencia reemplazable.

Bearer no es una credencial adjuntada automáticamente por el navegador: no se añade
un mecanismo CSRF innecesario ahora. Al introducir cookies/sesiones, implementar token
CSRF, verificación de Origin, SameSite/Secure/HttpOnly y renovar CORS de credenciales
con orígenes exactos. HTTPS es obligatorio para la administración y el frontend.

El ejemplo `backend/.env.example` contiene únicamente placeholders. Nunca copiar
GROQ_API_KEY o ADMIN_API_TOKEN a variables VITE, Git, settings públicos o respuestas.
`.env`, storage y backups permanecen ignorados. La ruta comercial se rechaza si
queda dentro de static. Usar un usuario de servicio sin permisos innecesarios;
Windows requiere ACL del directorio privado para ese usuario. POSIX aplica 0600 a
base/archivos privados. No exponer storage desde proxy/CDN.

Los eventos contienen ID generado por servidor, grupo de endpoint, estado, tipo de
error, UUID de registro, bytes/duración cuando corresponde. Nunca prompts, teléfonos,
respuestas, headers Authorization, excepción completa, rutas o SQL. Logs verbosos de
SDKs se desactivan y el diagnóstico pasa por eventos permitidos. Desactivar access logs
de Uvicorn/proxy que registren querystrings o cuerpos; redactar Authorization en proxy.

Errores 400/401/403/404/409/413/422/429/500/502/503/504 usan mensajes controlados.
422 no devuelve el input ni ctx Pydantic. No se reflejan errores de proveedor. SSE,
una vez iniciado, comunica un evento `error` y no ejecuta acciones pendientes; ya
no puede cambiar su HTTP 200. El frontend aprobado limpia cola/audio al recibir error.

## Timeouts y health

Request body: 15 s; Groq: 25 s, sin reintentos automáticos del SDK; RAG total: 15 s;
TTS: 20 s (conexión 10 s, buffer 5 MiB); inactividad del stream proveedor: 25 s;
stream completo: 90 s. Se cierra el stream en éxito, error y cancelación. Un timeout
TTS conserva el texto y permite continuar, como en fases aprobadas. Timeouts no matan
trabajo CPU ya iniciado en threads: límites de tamaño/capacidad acotan el trabajo local.

`GET /health` y `/health/live`: proceso vivo. `/health/ready`: integridad/referencias
de la base, configuración inicial, archivo del avatar seleccionado y PricingService
funcional; 503 si falla. Precios pendientes no invalidan una configuración correcta.
Groq/TTS se informan como `not_probed`: no se llama al proveedor ni se tumba readiness
por una caída temporal externa. No expone rutas, claves ni datos comerciales.

## SQLite, backup y restauración

WAL, foreign_keys ON, synchronous FULL, timeout de locking cinco segundos configurable
hasta 30, transacciones con rollback y cierre de conexiones. Errores SQL no llegan al
cliente. WAL presupone disco local; no usar un filesystem de red sin comprobar soporte.
El backup utiliza la API de SQLite, no una copia ordinaria mientras hay escrituras;
comprueba integridad/referencias, publica sin sobrescribir y limpia temporales.

```powershell
& backend/venv/Scripts/python.exe -B backend/backup_commercial.py
# O elegir un nuevo destino privado:
& backend/venv/Scripts/python.exe -B backend/backup_commercial.py --output backend/storage/backups/commercial_manual.sqlite3
```

Restauración manual, **sin ejecutar durante pruebas**: detener backend y cualquier
proceso escritor; preservar la base actual y sus sidecars WAL/SHM como conjunto privado;
validar integridad del backup; retirar el conjunto actual de la ruta de servicio y colocar
el snapshot consistente en la ruta configurada sin sidecars anteriores. Aplicar ACL,
iniciar y comprobar `/health/ready` y tarifas/avatares. No sobrescribir una base abierta
ni mezclar un backup con WAL antiguo. El script nunca restaura ni borra datos.
Definir retención y copiar backups a almacenamiento separado antes de comercializar;
un backup en el mismo disco no protege contra pérdida del disco.

## Despliegue y alcance de validación

Mantener el backend en interfaz privada detrás de proxy HTTPS. Por ejemplo, desde backend:

```text
uvicorn server:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log --no-proxy-headers --limit-concurrency 64 --timeout-keep-alive 5
```

Si hay proxy, activar headers de proxy **sólo con IPs exactas del proxy confiable** mediante
`--proxy-headers --forwarded-allow-ips <IPs>`, nunca `*`; éste debe sobrescribir los headers
recibidos del cliente. La aplicación no interpreta X-Forwarded-For por su cuenta. Así
ASGI puede conocer IP y HTTPS reales. Configurar también límites de body/header, timeouts
y capacidad en el proxy. No publicar el puerto interno ni confiar en headers de clientes.

Las pruebas usan proveedores simulados y bases temporales. Se conserva la suite aprobada
de acciones, campañas, avatar, web/kiosk e info/sales. Se prueban límites, MIME/extensión,
firmas, corrupción, dimensiones/animación, traversal, limpieza, revalidación de precios,
auth, secretos, CORS, errores, logs, timeout/cleanup, readiness y backup íntegro.
No sustituyen una prueba de navegador bajo los headers reales del hosting ni una prueba
de carga/penetración del despliegue. Esas validaciones y la gestión de datos personales,
retención y acceso a comprobantes deben completarse antes de comercialización pública.

Resultado de cierre: **92 pruebas backend y 20 frontend aprobadas**, incluidas las
fases 1, 1.5 y 1.6. Build correcto (780.82 kB; advertencia de tamaño del bundle),
validación sintáctica Python/JavaScript y `git diff --check` sin errores. Se creó un
backup consistente local; las pruebas validaron snapshots mientras había una
transacción abierta, sin incluir datos no confirmados. No se ejecutó restauración.

Referencias para los controles: Pillow documenta las comprobaciones de imagen y
protección contra bombas de descompresión en su [guía de seguridad](https://pillow.readthedocs.io/en/stable/handbook/security.html).
Los timeouts/reintentos del proveedor siguen las opciones del [SDK oficial Groq](https://github.com/groq/groq-python).
El middleware mantiene las características de streaming de [ASGI en Starlette](https://www.starlette.io/middleware/).
