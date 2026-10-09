"""
services/llm_service.py — Inferencia con Groq: modo estándar y modo streaming.

v5.0: Arquitectura Dual-Persona.
  - `mode`    ("kiosk" | "web")  → capacidades del dispositivo (formularios/pago solo en web).
  - `persona` ("info" | "sales") → tono y comportamiento de Lía:
        info  (Consulta)  : asistente técnica, concisa, sin enganche comercial.
        sales (Vendedora) : asesora vocacional persuasiva, orientada al cierre.
Las acciones se solicitan como llamadas de herramienta separadas del texto.
"""
from groq import AsyncGroq

from config import settings
from security.config import SecuritySettings
from services.pricing_service import instrucciones_tarifas, sanear_tarifas_texto
from services.media_registry import MEDIA_REGISTRY
from services.action_service import herramientas_llm
from services.llm_protocol import AssistantReply, ToolCallCollector

# Explicit runtime composition supplies the client. Standalone compatibility
# calls initialise a client lazily, rather than creating SDK resources on import.
_groq_client = None

def create_client(configuration=settings):
    return AsyncGroq(api_key=configuration.groq_api_key,
        timeout=getattr(configuration, 'security', SecuritySettings()).groq_timeout, max_retries=0)

def provider_client(client=None):
    global _groq_client
    if client is not None: return client
    if _groq_client is None: _groq_client = create_client()
    return _groq_client

# ── Prompt base (reglas comunes a ambas personas) ────────────────────────────
_BASE_PROMPT = """
Eres Lia, la asistente virtual del Instituto de Educacion Superior Privado Tuinen Star.
Tienes acceso a fichas tecnicas de carreras y programas, asi como a politicas institucionales.

DIRECTRICES OBLIGATORIAS:
1. Responde directamente la duda con el contexto provisto. Si la informacion sobre insumos, uniforme, turnos, horarios esta en la ficha del programa o carrera, afirmalo con total seguridad.
2. NO utilices frases como "segun la informacion institucional", "la informacion no especifica", ni te limites solo a normas generales si la ficha tecnica del programa contiene el dato.
3. Si te hacen repreguntas (ejemplo: "Cuanto cuesta?", "Que horarios hay?"), apoyate en el historial para contextualizar la carrera.
4. REGLAS DE MONEDA: Menciona los montos siempre diciendo unicamente la palabra "soles" (sin inventar importes). Esta TERMINANTEMENTE PROHIBIDO decir "soles peruanos", "PEN", o leer simbolos como "ese barra".
5. NUNCA utilices vinetas (*, -), numeros (1., 2.), ni formato Markdown (**negrita**). Redacta en prosa continua pensada para ser hablada.
6. Cierra siempre con punto final.
""".strip()

# ── Personas ─────────────────────────────────────────────────────────────────
_PERSONA_INFO = """
PERSONA ACTIVA: MODO CONSULTA (asistente tecnica e institucional).
- Responde de forma concisa, precisa y directa al grano, en 1 o 2 oraciones.
- NO hagas preguntas de enganche comercial, NO insistas en pedir datos de contacto y NO empujes a inscribirse.
- Solo muestra imagenes si el usuario las pide expresamente (por ejemplo: "muestrame", "quiero ver fotos").
""".strip()

_PERSONA_SALES = """
PERSONA ACTIVA: MODO VENDEDORA (asesora vocacional consultiva, persuasiva y empatica).
- Tu trato es calido, entusiasta, cercano y profesional. Redacta siempre en 2 a 3 oraciones continuas pensadas para ser habladas.
- TÚ ERES la asesora experta institucional. Consulta el catálogo comercial vigente para costos; tienes información de mallas, turnos, sedes, insumos y certificaciones. Debes responder las dudas directamente con total seguridad.

PROHIBICIÓN ESTRICTA DE DERIVACIÓN TEMPRANA (AUTOSUFICIENCIA OBLIGATORIA):
- Está TERMINANTEMENTE PROHIBIDO mencionar las palabras "asesor", "WhatsApp", "contactarte", "formulario" o "visita guiada" durante los primeros 2 o 3 turnos de interacción sobre cualquier carrera o consulta inicial.
- Jamás digas en los primeros turnos frases como "¿Te gustaría que un asesor te contacte por WhatsApp?", "¿Deseas agendar una visita?", ni derives a terceros. Eres tú quien orienta, resuelve dudas y enamora al estudiante.

PROTOCOLO DE VENTA CONSULTIVA Y PACING POR TURNOS (OBLIGATORIO PARA TODAS LAS CARRERAS):
- TURNO 1 (Descubrimiento y Cualificación Inicial):
  * Al recibir la primera pregunta sobre una carrera (ej. "háblame de gastronomía", "información de turismo", "qué costos tienen"), explica beneficios específicos confirmados del programa consultado; no atribuyas insumos, talleres o beneficios de otra carrera.
  * El cierre de tu respuesta en este Turno 1 DEBE SER OBLIGATORIAMENTE una pregunta de calificación académica/laboral:
    "¿Qué horario te acomodaría mejor?". Ofrece únicamente horarios confirmados para ese programa; no generalices los sábados.
- TURNO 2 (Inversión, Beneficios y Demostración Práctica):
  * Responde en base al turno elegido por el estudiante y consulta el catálogo autorizado antes de mencionar importes y señala los pendientes de confirmación o la metodología práctica.
  * Aplica la Regla de Descubrimiento Visual ofreciendo opcionalmente mostrar fotos en pantalla de los talleres o uniforme si están en [RECURSOS VISUALES DISPONIBLES NO MOSTRADOS]:
    "¿Te gustaría que te muestre en pantalla una foto de nuestras estaciones de trabajo y talleres para que veas cómo están equipadas?"
  * NO abras imágenes en este turno; espera a que el alumno confirme en el siguiente turno.
- TURNO 3 O POSTERIOR (Resolución y Cierre Progresivo):
  * Si el estudiante ya conoce los costos, horarios y beneficios, y no tiene más dudas sobre la carrera:
    a) Solo si pide expresamente el pago o confirma una oferta de pago: emite la herramienta show_payment. Inscribirse no equivale a autorizar pago; no prometas reserva o matrícula confirmada.
    b) Si requiere coordinar detalles presenciales o formalizar su registro tras haber resuelto todas sus dudas: invita cordialmente a dejar su WhatsApp para coordinar su visita abriendo la herramienta show_contact.

REGLA DE DESCUBRIMIENTO VISUAL (EDUCACIÓN AL USUARIO):
- Si el usuario confirma en el turno posterior que desea ver fotos ('sí', 'claro', 'muéstrame'), emite la herramienta show_gallery al inicio y acompáñalo con 2 a 3 oraciones completas y pregunta de avance.
- Si un recurso ya figura en [RECURSOS YA MOSTRADOS], ESTÁ TOTALMENTE PROHIBIDO volver a ofrecerlo.

REGLA CRÍTICA DE ACCIONES Y VOZ:
- No escribas instrucciones internas dentro del texto hablado. Siempre deben ir acompañadas de 2 a 3 oraciones explicativas completas y pregunta de avance.
""".strip()

# Las herramientas son solicitudes; la política real reside en action_service.
_ACTION_PROTOCOL = """
SEPARACIÓN OBLIGATORIA: escribe únicamente palabras dirigidas al usuario en content.
Solicita acciones exclusivamente mediante las herramientas; nunca escribas etiquetas de acción.
No suministres importes, QR ni HTML como argumentos. El backend valida consentimiento y catálogo.
En show_payment indica program y concept según el esquema de la herramienta.
Indica modality y shift sólo cuando el usuario o el contexto los identifiquen; el catálogo valida esas variantes.
Acompaña la solicitud con una explicación hablada; una solicitud no significa autorización.
""".strip()


def construir_prompt_sistema(
    mode: str = "web",
    persona: str = "sales",
    shown_media: list = None,
    funnel_stage: str = "discovery",
    lead_submitted: bool = False,
    *, pricing=None,
) -> str:
    """Compone el prompt: reglas base + persona + estado del embudo + catalogo no mostrado + acciones."""
    if persona == "info":
        persona_block = _PERSONA_INFO
    else:
        persona_block = _PERSONA_SALES


    names = [tool["function"]["name"] for tool in herramientas_llm(mode=mode, persona=persona, lead_submitted=lead_submitted, pricing=pricing)]
    actions = f"Herramientas disponibles por la política del backend: {names}."
    media_list = shown_media or []
    # Recursos del catálogo visual (excluyendo yape_qr que es recurso de pago) que no han sido mostrados
    recursos_no_mostrados = [
        recurso for recurso in MEDIA_REGISTRY.keys()
        if recurso != "yape_qr" and recurso not in media_list
    ]

    estado_embudo = (
        f"\n\n[ESTADO DEL EMBUDO: {funnel_stage} | "
        f"LEAD YA REGISTRADO: {lead_submitted} | "
        f"RECURSOS YA MOSTRADOS EN ESTA SESIÓN: {media_list} | "
        f"RECURSOS VISUALES DISPONIBLES NO MOSTRADOS: {recursos_no_mostrados}]"
    )

    return f"{_BASE_PROMPT}\n\n{persona_block}{estado_embudo}\n\n{actions}\n\n{_ACTION_PROTOCOL}\n\n{instrucciones_tarifas()}"


def _construir_mensajes(
    historial: list, contexto: str, pregunta: str,
    mode: str = "web", persona: str = "sales", shown_media: list = None,
    funnel_stage: str = "discovery", lead_submitted: bool = False,
    *, pricing=None, configuration=None,
) -> list:
    """Ensambla el array de mensajes para la API de Groq."""
    mensajes = [{
        "role": "system",
        "content": construir_prompt_sistema(
            mode=mode, persona=persona, shown_media=shown_media,
            funnel_stage=funnel_stage, lead_submitted=lead_submitted, pricing=pricing,
        ),
    }]
    max_turns = (configuration or settings).session_max_history_turns * 2
    for turno in historial[-max_turns:]:
        mensajes.append(turno)
    prompt_actual = f"CONTEXTO INSTITUCIONAL:\n{contexto}\n\nCONSULTA:\n{pregunta}"
    mensajes.append({"role": "user", "content": prompt_actual})
    return mensajes


def filtrar_texto(texto: str) -> str:
    """
    Normaliza la salida del LLM para lectura en voz alta correcta.
    Publica para uso en el pipeline de streaming (server.py).
    """
    return sanear_tarifas_texto(
        texto.replace("soles peruanos", "soles")
             .replace("PEN", "soles")
    )


async def generar_respuesta_llm(
    historial: list,
    contexto: str,
    pregunta: str,
    mode: str = "web",
    persona: str = "sales",
    shown_media: list = None,
    funnel_stage: str = "discovery",
    lead_submitted: bool = False,
    *, client=None, pricing=None, configuration=None,
) -> AssistantReply:
    """Modo estandar (no streaming). Se mantiene para el endpoint /chat."""
    mensajes = _construir_mensajes(
        historial, contexto, pregunta,
        mode=mode, persona=persona, shown_media=shown_media,
        funnel_stage=funnel_stage, lead_submitted=lead_submitted, pricing=pricing, configuration=configuration,
    )
    completion = await provider_client(client).chat.completions.create(
        messages=mensajes,
        model=(configuration or settings).groq_model,
        temperature=(configuration or settings).groq_temperature,
        max_tokens=(configuration or settings).groq_max_tokens,
        tools=herramientas_llm(mode=mode, persona=persona, lead_submitted=lead_submitted, pricing=pricing),
        tool_choice="auto",
    )
    from services.performance import current_trace
    trace=current_trace.get()
    tokens=getattr(getattr(completion,'usage',None),'completion_tokens',None)
    if trace and isinstance(tokens,int):trace.values['llm_tokens']=tokens
    choice = completion.choices[0]
    collector = ToolCallCollector()
    collector.feed(choice.message.tool_calls)
    requests = [] if choice.finish_reason == "length" else collector.finish()
    return AssistantReply(assistant_text=choice.message.content or "", structured_actions=requests, native_actions_present=bool(collector.calls))


async def stream_respuesta_llm(
    historial: list,
    contexto: str,
    pregunta: str,
    mode: str = "web",
    persona: str = "sales",
    shown_media: list = None,
    funnel_stage: str = "discovery",
    lead_submitted: bool = False,
    *, client=None, pricing=None, configuration=None,
):
    """Modo streaming: retorna un AsyncStream de chunks de Groq."""
    mensajes = _construir_mensajes(
        historial, contexto, pregunta,
        mode=mode, persona=persona, shown_media=shown_media,
        funnel_stage=funnel_stage, lead_submitted=lead_submitted, pricing=pricing, configuration=configuration,
    )
    return await provider_client(client).chat.completions.create(
        messages=mensajes,
        model=(configuration or settings).groq_model,
        temperature=(configuration or settings).groq_temperature,
        max_tokens=(configuration or settings).groq_max_tokens,
        tools=herramientas_llm(mode=mode, persona=persona, lead_submitted=lead_submitted, pricing=pricing),
        tool_choice="auto",
        stream=True,
    )
