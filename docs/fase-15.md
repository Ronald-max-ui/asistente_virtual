# Fase 1.5: acciones estructuradas y tarifas dinámicas

> Registro de la fase aprobada. Desde Fase 1.6, la fuente primaria comercial es
> SQLite y los JSON son únicamente material de migración. Ver [Fase 1.6](fase-16.md).

El LLM produce `assistant_text` y solicitudes `structured_actions` separadas.
Las solicitudes usan las herramientas `show_gallery`, `show_contact` y
`show_payment`. Los modelos Pydantic de solicitud, acción final y transporte
JSON/SSE prohíben campos adicionales. La solicitud
de pago admite sólo programa, concepto, modalidad y turno: nunca importe, moneda,
QR, HTML ni campos arbitrarios.

`action_service.py` valida esquema, contexto, capacidades del dispositivo/persona,
consentimiento y catálogo vigente. `consent_service.py` conserva las políticas de
Fase 1. `pricing_service.py` carga los JSON de cada programa, valida vigencia y
construye la cotización. Ningún importe comercial se almacena como constante Python.

Las tarifas `pending` y `free` no generan acciones de pago. Se informan mediante
texto/audio y avisos JSON distintos. Sólo precios activos positivos autorizados
en PEN permiten el actual pago Yape. Descuentos por sí mismos no son cobrables.
El upload vuelve a validar el catálogo vigente, incluso si el modal es anterior.

## Contrato y streaming

Una solicitud de herramienta es, por ejemplo:

```json
{"program":"gastronomia","concept":"inscripcion","modality":"presencial"}
```

El backend genera la acción definitiva con `type`, programa, concepto, importe,
moneda, campaña, vigencia, modalidad/turno y QR. No envía observaciones ni metadatos
administrativos del catálogo dentro de la acción de pago. SSE conserva los eventos de texto
y audio por oración; luego emite `ui_action` con `action` como objeto JSON y
termina en `done`. El frontend usa un mapa de handlers conocidos y valida la
estructura del DTO recibido antes de esperar a que termine realmente la cola
de audio. Un tipo desconocido, campos adicionales, URL peligrosa o carga
incompleta sólo generan advertencia. No interpreta el texto como instrucciones.
Los eventos posteriores a `done` o `error` se ignoran.

`/chat` conserva `texto` y `audio_b64`, y añade `actions` y `notices`.
`/chat/stream` aplica exactamente la misma autorización. La escalación existente
de persona `info` a `sales` ante intención comercial se conserva en ambas rutas;
el kiosco sigue sin pago/contacto. Las galerías funcionan en ambos dispositivos
y personas. No se cambiaron estilos visuales del avatar ni los modales.

Los prompts activos ya no generan etiquetas. `llm_protocol.py` contiene el
adaptador **LEGADO TEMPORAL**: quita etiquetas completas, fragmentadas y truncadas,
descarta siempre su importe y convierte la intención al mismo esquema/política.
Si existe una llamada nativa, el adaptador legado no aporta acciones. Esto también
se aplica si los argumentos de la llamada están malformados o son rechazados:
no se usa una etiqueta antigua para intentar sustituir esa solicitud. La selección
es idéntica en `/chat` y `/chat/stream`. No existe una segunda política comercial
ni un ejecutor de etiquetas en frontend.
Se eliminó la deducción de acciones desde las palabras del modelo. El adaptador
puede retirarse cuando proveedores y conversaciones antiguos dejen de emitirlas.

## Fuente comercial y archivos

- `backend/services/action_service.py`: modelos estrictos y autorización única.
- `backend/services/consent_service.py`: función común de capacidades, usada al
  ofrecer herramientas y al autorizar; políticas y negaciones de Fase 1 conservadas.
- `backend/services/llm_protocol.py`: texto/acciones separados, herramientas
  fragmentadas y compatibilidad interna legada.
- `backend/services/pricing_service.py`: lectura dinámica, validación y respuestas
  comerciales desde la fuente actual, independientes del índice vectorial.
- `backend/services/llm_service.py`: herramientas y prompts sin importes fijos.
- `backend/server.py`: integración de ambos endpoints y revalidación de comprobantes.
- `avatar-kiosk/src/api/client.js`: despacho de objetos tipados; cola de audio de
  Fase 1 conservada.
- `avatar-kiosk/src/api/actions.js`: handlers explícitos y validación del contrato
  de transporte; ninguna resolución de tarifas o consentimiento en frontend.
- `avatar-kiosk/src/ui/overlays.js`: campos del contrato nuevo, variantes en upload
  y escape de datos dinámicos; estilos y listeners seguros conservados.
- Seis `*.pricing.json` junto a los Markdown de las carreras/cursos: única fuente
  por programa. Inicialmente inscripción confirmada y demás conceptos pendientes.
- Ocho Markdown: únicamente reemplazo de importes/promociones duplicados por
  referencias comerciales; contenido académico conservado.
- `backend/validate_pricing.py`: validación administrativa sin servidor, red ni RAG.
- Pruebas backend/frontend y [guía administrativa](tarifas-dinamicas.md).

## Validación y límites

Las regresiones cubren campos arbitrarios/importes del modelo, inscripción desde
catálogo, pending/free sin QR/upload, negaciones, tipos desconocidos, XSS, ambos
modos/personas, herramientas fragmentadas, orden SSE y paridad con `/chat`.
También cubren cambios en caliente, campañas futuras/vencidas, fechas inclusivas,
modalidades/turnos, estados inválidos, campañas superpuestas, recuperación de un
JSON inválido y rechazo de importes antiguos en comprobantes.

Pruebas con Groq, RAG y TTS simulados: no se consumen llamadas comerciales ni se
regenera ChromaDB. Las pruebas frontend usan DOM/WebAudio simulados, sin afirmar
validación física de micrófono, avatar o dispositivos móviles. Las herramientas
siguen el [protocolo documentado por Groq](https://console.groq.com/docs/tool-use/overview).
Falta una prueba manual conectada al proveedor antes del despliegue.

El nuevo contrato exige desplegar juntos backend/frontend. No se ha desplegado,
creado PR ni realizado commit. Se preservan los cambios previos de TTS y medios.
La alerta de bundle superior a 500 kB continúa pendiente de Fase 7. Rate limiting,
CORS, archivos, sesiones/persistencia, ChromaDB y refactorización general siguen
fuera de esta fase. No se avanzó a Fase 2.

Resultado de validación: 50 pruebas backend y 15 frontend aprobadas; seis catálogos
validados; `npm run build`, sintaxis Python/JavaScript/JSON y `git diff --check`
correctos. No se detectaron regresiones en esta cobertura automatizada. El build
conserva la advertencia del bundle de aproximadamente 780 kB.

## Esquemas finales

| Tipo | Solicitud del LLM | Acción definitiva del backend |
|---|---|---|
| `show_gallery` | `resource_id` | `resource_id`, `resource` con título, descripción y URL del registro |
| `show_contact` | `program` opcional | `program`, `program_label` normalizados |
| `show_payment` | `program`, `concept`, `modality`/`shift` opcionales | IDs y etiquetas, modalidad/turno, `amount`, `currency`, `status`, `campaign`, `starts_on`, `ends_on`, `confirmed`, `qr_url`, `payment_number` |

Todos incluyen `type`, y sólo admiten los campos de su esquema. Las restricciones
comerciales se resuelven en servicios; la validación frontend únicamente comprueba
el contrato emitido, sin inventar importes ni volver a decidir consentimiento.
Las herramientas disponibles en los prompts se obtienen de ActionService y de
la función de capacidades de ConsentService; no hay una lista de restricciones
independiente por prompt. La autorización final vuelve a comprobar consentimiento.

`mode_switch` es un evento de sistema tipado para `info`/`sales`. No es una acción
solicitable por el modelo. `text`, `audio`, `ui_action`, `notice`, `done` y `error`
también tienen esquemas de transporte explícitos. `/chat` publica el esquema de
sus acciones finales en OpenAPI, conservando `texto` y `audio_b64` por compatibilidad.

No se avanzó a Fase 1.6 ni Fase 2.
