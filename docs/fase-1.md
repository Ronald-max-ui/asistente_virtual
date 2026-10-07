# Fase 1 — Cambios y verificación

Esta fase corrige animación por inactividad, cola/callbacks de audio, URLs,
construcción de modales, consentimiento y tarifas. No inicia la Fase 2.

## Archivos

| Archivo | Cambio |
|---|---|
| `avatar-kiosk/src/avatar/animator.js` | Estado de `attractionAudioEnabled` accesible a la máquina de animación. |
| `avatar-kiosk/src/audio/player.js` | Reserva de posiciones antes de decodificar, múltiples callbacks, espera hasta finalizar SSE, cancelación de cargas y eventos viejos. |
| `avatar-kiosk/src/api/client.js` | URL común, acciones diferidas hasta terminar respuesta/audio, limpieza ante errores, recuperación del texto completo cuando falta TTS. |
| `avatar-kiosk/src/api/config.js` | Base única para API y medios, validación de HTTP(S), bloqueo de contenido mixto y URLs de medios externas o inseguras. |
| `avatar-kiosk/src/ui/overlays.js` | Escape de valores dinámicos, listeners en lugar de JavaScript inline, galería en kiosco, aviso de tarifa pendiente sin QR/upload. CSS conservado. |
| `backend/services/consent_service.py` | Petición explícita o afirmación a una oferta concreta; negaciones, postergaciones y ofertas ambiguas bloqueadas. |
| `backend/services/pricing_service.py` | Catálogo con inscripción confirmada y tarifas pendientes; filtrado de importes monetarios no autorizados para voz/subtítulos. |
| `backend/services/action_service.py` | Lista de acciones/recursos permitidos y validación por dispositivo/persona. |
| `backend/server.py` | Aplica la política a todas las vías de emisión SSE y al chat JSON; solo registra acciones aceptadas; comprueba catálogo al recibir comprobantes y conserva su concepto. |
| `backend/services/llm_service.py` | Reglas oficiales prioritarias para inscripción, tarifas pendientes y sábados; persona conservada en ambas rutas. |
| `avatar-kiosk/package.json` | Comando `npm test`, sin dependencias nuevas. |
| `backend/tests/test_phase1.py`, `test_phase1_api.py` | Políticas y regresiones HTTP con servicios simulados y escrituras interceptadas. |
| `avatar-kiosk/tests/phase1.test.js`, `overlays.test.js`, `client.test.js` | Audio, URLs, animación, modales y transporte SSE con navegador/audio simulados. |

La extracción de la política de acciones se limita a evitar que una vía del
stream omita una comprobación de seguridad. La separación general de rutas y
responsabilidades de `server.py` sigue reservada a la Fase 6.

## Configuración de frontend

En localhost/127.0.0.1/IPv6 local, la base por defecto es el mismo host en el
puerto 8000. En producción es el mismo origen del frontend; este despliegue
necesita enrutar `/chat`, `/api` y `/static` al backend.

Si el backend está en otro origen o prefijo, establecer `VITE_API_URL` antes
de compilar, por ejemplo `https://api.ejemplo.com/lia`. Chat, formularios y
medios usan esa misma base. Un frontend HTTPS exige una base HTTPS.

## Tarifas

Solo está confirmada oficialmente la inscripción: **80 soles**.

Pendientes de confirmación: matrícula y mensualidades de Gastronomía, Turismo,
Administración de Empresas, Contabilidad, Bartender y Panadería y Pastelería,
incluyendo variantes por modalidad/turno y descuentos. `None` en el catálogo
significa pendiente, nunca gratuito.

El modelo no controla el importe del modal. Mientras una matrícula siga
pendiente se muestra el aviso, sin QR ni subida de comprobante; una petición
directa de upload de esa matrícula devuelve 409. La inscripción de 80 permite
QR y recepción del comprobante, que no confirma automáticamente la matrícula.

Gastronomía, Panadería y Bartender pueden tener clases/actividades los sábados;
esta condición no se extiende a otras carreras. Las fichas y el índice aún no
se regeneraron: su revisión corresponde a las fases 4 y 5. El prompt de esta
fase contiene las correcciones oficiales prioritarias.

## Pruebas

Desde la raíz, en PowerShell:

```powershell
& 'backend/venv/Scripts/python.exe' -B -m unittest discover -s backend/tests -v
```

Desde `avatar-kiosk`:

```powershell
npm test
npm run build
```

Verificación: 19 pruebas de backend y 11 de frontend; compilación de producción,
sintaxis Python/JavaScript y `git diff --check`. Se prueban las combinaciones
web/kiosk e info/sales, acciones fragmentadas, fallos de TTS, entradas maliciosas,
negaciones, catálogo y cancelación de audio.

RAG/Groq/TTS se simulan en HTTP; las escrituras de comprobantes se interceptan.
No se usa red ni se modifica ChromaDB o almacenamiento real durante las pruebas.
Los tests de DOM y audio usan simulaciones, no un navegador/dispositivo real.
Queda pendiente una prueba manual de voz, autoplay y presentación en Safari/iOS
y en el equipo de kiosco con los proveedores reales.

## Riesgos y pendientes fuera de esta fase

- El consentimiento es conservador: expresiones ambiguas o con negaciones pueden
  requerir reformular la petición. Una afirmación breve exige una oferta única.
- El catálogo pendiente restringe pagos hasta la confirmación oficial.
- Concurrencia de peticiones y persistencia de sesiones siguen en la Fase 3.
- Límites, validación real de imágenes, CORS y logs siguen en la Fase 2.
- La compilación avisa de un bundle mayor que 500 kB; optimización en la Fase 7.
- No se cambiaron los scripts de audio ni la imagen `pago.webp` que ya tenían
  modificaciones locales antes de iniciar la fase.
