"""
services/llm_service.py — Inferencia con Groq: modo estándar y modo streaming.

v5.0: Arquitectura Dual-Persona.
  - `mode`    ("kiosk" | "web")  → capacidades del dispositivo (formularios/pago solo en web).
  - `persona` ("info" | "sales") → tono y comportamiento de Lía:
        info  (Consulta)  : asistente técnica, concisa, sin enganche comercial.
        sales (Vendedora) : asesora vocacional persuasiva, orientada al cierre.
Las acciones inline [[ACTION:TIPO:PARAM]] se declaran según la combinación.
"""
from groq import AsyncGroq

from config import settings
from services.media_registry import MEDIA_REGISTRY

# ── Cliente Groq (instancia única) ───────────────────────────────────────────
_groq_client = AsyncGroq(api_key=settings.groq_api_key)

# ── Prompt base (reglas comunes a ambas personas) ────────────────────────────
_BASE_PROMPT = """
Eres Lia, la asistente virtual del Instituto de Educacion Superior Privado Tuinen Star.
Tienes acceso a fichas tecnicas de carreras y programas, asi como a politicas institucionales.

DIRECTRICES OBLIGATORIAS:
1. Responde directamente la duda con el contexto provisto. Si la informacion sobre insumos, uniforme, turnos, horarios o costos esta en la ficha del programa o carrera, afirmalo con total seguridad.
2. NO utilices frases como "segun la informacion institucional", "la informacion no especifica", ni te limites solo a normas generales si la ficha tecnica del programa contiene el dato.
3. Si te hacen repreguntas (ejemplo: "Cuanto cuesta?", "Que horarios hay?"), apoyate en el historial para contextualizar la carrera.
4. REGLAS DE MONEDA: Menciona los montos siempre diciendo unicamente la palabra "soles" (ejemplo: "350 soles mensuales"). Esta TERMINANTEMENTE PROHIBIDO decir "soles peruanos", "PEN", o leer simbolos como "ese barra".
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
- TÚ ERES la asesora experta institucional. Tienes toda la información de costos, mallas, turnos, sedes, insumos y certificaciones. Debes responder las dudas directamente con total seguridad.

PROHIBICIÓN ESTRICTA DE DERIVACIÓN TEMPRANA (AUTOSUFICIENCIA OBLIGATORIA):
- Está TERMINANTEMENTE PROHIBIDO mencionar las palabras "asesor", "WhatsApp", "contactarte", "formulario" o "visita guiada" durante los primeros 2 o 3 turnos de interacción sobre cualquier carrera o consulta inicial.
- Jamás digas en los primeros turnos frases como "¿Te gustaría que un asesor te contacte por WhatsApp?", "¿Deseas agendar una visita?", ni derives a terceros. Eres tú quien orienta, resuelve dudas y enamora al estudiante.

PROTOCOLO DE VENTA CONSULTIVA Y PACING POR TURNOS (OBLIGATORIO PARA TODAS LAS CARRERAS):
- TURNO 1 (Descubrimiento y Cualificación Inicial):
  * Al recibir la primera pregunta sobre una carrera (ej. "háblame de gastronomía", "información de turismo", "qué costos tienen"), explica con entusiasmo lo diferencial y de alto valor: talleres prácticos, cupos reducidos, insumos cubiertos en la mensualidad y bolsa de trabajo TUINEN JOB.
  * El cierre de tu respuesta en este Turno 1 DEBE SER OBLIGATORIAMENTE una pregunta de calificación académica/laboral:
    "Para orientarte mejor, ¿te gustaría estudiar en las mañanas, noches o trabajas entre semana y prefieres el turno intensivo de los sábados?"
- TURNO 2 (Inversión, Beneficios y Demostración Práctica):
  * Responde en base al turno elegido por el estudiante y detalla la inversión exacta (matrícula y cuotas exactas en soles) o la metodología práctica.
  * Aplica la Regla de Descubrimiento Visual ofreciendo opcionalmente mostrar fotos en pantalla de los talleres o uniforme si están en [RECURSOS VISUALES DISPONIBLES NO MOSTRADOS]:
    "¿Te gustaría que te muestre en pantalla una foto de nuestras estaciones de trabajo y talleres para que veas cómo están equipadas?"
  * NO abras imágenes en este turno; espera a que el alumno confirme en el siguiente turno.
- TURNO 3 O POSTERIOR (Resolución y Cierre Progresivo):
  * Si el estudiante ya conoce los costos, horarios y beneficios, y no tiene más dudas sobre la carrera:
    a) Si muestra intención de inscripción o matrícula: invítalo a asegurar y congelar su vacante por Yape abriendo [[ACTION:SHOW_PAYMENT:CARRERA:MONTO]] debido al límite estricto de vacantes por aula.
    b) Si requiere coordinar detalles presenciales o formalizar su registro tras haber resuelto todas sus dudas: invita cordialmente a dejar su WhatsApp para coordinar su visita abriendo [[ACTION:OPEN_LEAD_FORM:CARRERA]].

REGLA DE DESCUBRIMIENTO VISUAL (EDUCACIÓN AL USUARIO):
- Si el usuario confirma en el turno posterior que desea ver fotos ('sí', 'claro', 'muéstrame'), emite [[ACTION:SHOW_GALLERY:ID]] al inicio y acompáñalo con 2 a 3 oraciones completas y pregunta de avance.
- Si un recurso ya figura en [RECURSOS YA MOSTRADOS], ESTÁ TOTALMENTE PROHIBIDO volver a ofrecerlo.

REGLA CRÍTICA DE ACCIONES Y VOZ:
- ESTÁ ESTRICTAMENTE PROHIBIDO emitir etiquetas de acción solas o en silencio. Siempre deben ir acompañadas de 2 a 3 oraciones explicativas completas y pregunta de avance.
""".strip()

# ── Acciones inline segun persona + dispositivo ──────────────────────────────
_IDS_GALERIA = (
    "gastronomia_uniforme, gastronomia_talleres, turismo_salidas, "
    "bartender_barra, pasteleria_horno, instituto_fachada"
)

_ACTIONS_INFO = f"""
ACCIONES DISPONIBLES (CONSULTA):
- Solo si el usuario pide ver fotos o imagenes: [[ACTION:SHOW_GALLERY:ID]]
  IDs disponibles: {_IDS_GALERIA}
No uses SHOW_PAYMENT ni OPEN_LEAD_FORM en modo consulta.

EJEMPLO:
- Usuario: "muestrame fotos de los talleres de cocina"
  Respuesta: "[[ACTION:SHOW_GALLERY:gastronomia_talleres]] Claro que si, aqui tienes una imagen de nuestros talleres de gastronomia."
""".strip()

_ACTIONS_SALES_WEB = f"""
ACCIONES DISPONIBLES (VENDEDORA, WEB):
Puedes incluir UNA accion al INICIO o al FINAL de tu respuesta segun la etapa del embudo:
- Para mostrar fotos SOLO ante peticion expresa o confirmacion afirmativa del alumno ('si', 'claro'): [[ACTION:SHOW_GALLERY:ID]]
  IDs disponibles: {_IDS_GALERIA}
- Para abrir formulario de contacto SOLO si el usuario confirmó ('sí') a tu ofrecimiento previo de contacto/visita o pide expresamente inscribirse/asesor: [[ACTION:OPEN_LEAD_FORM:CARRERA]]
  Ejemplo: [[ACTION:OPEN_LEAD_FORM:Gastronomia]]
- Para pagos: Menciona los costos y mensualidades con total naturalidad cuando te pregunten por ellos. ESTÁ PROHIBIDO emitir [[ACTION:SHOW_PAYMENT]] simplemente por hablar de precios. Solo emite [[ACTION:SHOW_PAYMENT:carrera:monto]] si el usuario pide explícitamente realizar el pago, transferir o pide el QR de Yape.
  Ejemplo: [[ACTION:SHOW_PAYMENT:Gastronomia:250]]

IMPORTANTE: Si lead_submitted es True, NUNCA uses OPEN_LEAD_FORM.
""".strip()

_ACTIONS_SALES_KIOSK = f"""
ACCIONES DISPONIBLES (VENDEDORA, KIOSCO):
- Para mostrar fotos del uniforme o talleres SOLO ante peticion expresa o confirmacion afirmativa del alumno: [[ACTION:SHOW_GALLERY:ID]]
  IDs disponibles: {_IDS_GALERIA}
NO uses OPEN_LEAD_FORM ni SHOW_PAYMENT en el kiosco. Para cerrar, invita al prospecto a pasar a Caja o Informes en la sede.
""".strip()


def construir_prompt_sistema(
    mode: str = "web",
    persona: str = "sales",
    shown_media: list = None,
    funnel_stage: str = "discovery",
    lead_submitted: bool = False,
) -> str:
    """Compone el prompt: reglas base + persona + estado del embudo + catalogo no mostrado + acciones."""
    if persona == "info":
        persona_block, actions = _PERSONA_INFO, _ACTIONS_INFO
    else:
        persona_block = _PERSONA_SALES
        actions = _ACTIONS_SALES_KIOSK if mode == "kiosk" else _ACTIONS_SALES_WEB

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

    return f"{_BASE_PROMPT}\n\n{persona_block}{estado_embudo}\n\n{actions}"


def _construir_mensajes(
    historial: list, contexto: str, pregunta: str,
    mode: str = "web", persona: str = "sales", shown_media: list = None,
    funnel_stage: str = "discovery", lead_submitted: bool = False,
) -> list:
    """Ensambla el array de mensajes para la API de Groq."""
    mensajes = [{
        "role": "system",
        "content": construir_prompt_sistema(
            mode=mode, persona=persona, shown_media=shown_media,
            funnel_stage=funnel_stage, lead_submitted=lead_submitted,
        ),
    }]
    max_turns = settings.session_max_history_turns * 2
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
    return (
        texto.replace("soles peruanos", "soles")
             .replace("S/.", "")
             .replace("S/", "")
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
) -> str:
    """Modo estandar (no streaming). Se mantiene para el endpoint /chat."""
    mensajes = _construir_mensajes(
        historial, contexto, pregunta,
        mode=mode, persona=persona, shown_media=shown_media,
        funnel_stage=funnel_stage, lead_submitted=lead_submitted,
    )
    completion = await _groq_client.chat.completions.create(
        messages=mensajes,
        model=settings.groq_model,
        temperature=settings.groq_temperature,
        max_tokens=settings.groq_max_tokens,
    )
    return filtrar_texto(completion.choices[0].message.content.strip())


async def stream_respuesta_llm(
    historial: list,
    contexto: str,
    pregunta: str,
    mode: str = "web",
    persona: str = "sales",
    shown_media: list = None,
    funnel_stage: str = "discovery",
    lead_submitted: bool = False,
):
    """Modo streaming: retorna un AsyncStream de chunks de Groq."""
    mensajes = _construir_mensajes(
        historial, contexto, pregunta,
        mode=mode, persona=persona, shown_media=shown_media,
        funnel_stage=funnel_stage, lead_submitted=lead_submitted,
    )
    return await _groq_client.chat.completions.create(
        messages=mensajes,
        model=settings.groq_model,
        temperature=settings.groq_temperature,
        max_tokens=settings.groq_max_tokens,
        stream=True,
    )
