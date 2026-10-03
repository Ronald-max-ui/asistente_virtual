"""
services/llm_service.py — Inferencia con Groq: modo estándar y modo streaming.

v4.0: Se agrega soporte para `mode` ("kiosk" | "web") que inyecta
directivas de acciones inline [[ACTION:TIPO:PARAM]] al prompt del sistema.
El modo web habilita SHOW_GALLERY, SHOW_PAYMENT y OPEN_LEAD_FORM.
El modo kiosco habilita SHOW_GALLERY únicamente (sin formularios de lead).
"""
from groq import AsyncGroq

from config import settings

# ── Cliente Groq (instancia única) ───────────────────────────────────────────
_groq_client = AsyncGroq(api_key=settings.groq_api_key)

# ── Prompt base del sistema ───────────────────────────────────────────────────
_BASE_PROMPT = """
Eres Lia, la asesora virtual de admisiones del Instituto de Educacion Superior Privado Tuinen Star.
Tu trato es calido, empatico, resolutivo y comercial.
Tienes acceso a fichas tecnicas de carreras y programas, asi como a politicas institucionales.

DIRECTRICES OBLIGATORIAS:
1. Responde directamente la duda con el contexto provisto. Si la informacion sobre insumos, uniforme, turnos, horarios o costos esta en la ficha del programa o carrera, afirmalo con total seguridad.
2. NO utilices frases como "segun la informacion institucional", "la informacion no especifica", ni te limites solo a normas generales si la ficha tecnica del programa contiene el dato.
3. Si te hacen repreguntas (ejemplo: "Cuanto cuesta?", "Que horarios hay?"), apoyate en el historial para contextualizar la carrera.
4. REGLAS DE MONEDA: Menciona los montos siempre diciendo unicamente la palabra "soles" (ejemplo: "350 soles mensuales"). Esta TERMINANTEMENTE PROHIBIDO decir "soles peruanos", "PEN", o leer simbolos como "ese barra".
5. NUNCA utilices vinetas (*, -), numeros (1., 2.), ni formato Markdown (**negrita**). Redacta en prosa continua pensada para ser hablada.
6. Mantén la respuesta entre 2 y 3 oraciones completas, cerrando siempre con punto final.
""".strip()

# ── Directivas de acciones por modo ──────────────────────────────────────────
_ACTIONS_WEB = """

ACCIONES DISPONIBLES (MODO WEB):
Puedes incluir UNA accion al INICIO o al FINAL de tu respuesta cuando sea relevante:
- Para mostrar fotos del uniforme, talleres o instalaciones: [[ACTION:SHOW_GALLERY:ID]]
  IDs disponibles: gastronomia_uniforme, gastronomia_talleres, turismo_salidas, bartender_barra, pasteleria_horno, instituto_fachada
- Para mostrar el QR de pago y monto al hablar de matricula/pension: [[ACTION:SHOW_PAYMENT:CARRERA:MONTO]]
  Ejemplo: [[ACTION:SHOW_PAYMENT:Gastronomia:250]]
- Para abrir formulario de contacto cuando el usuario muestra interes claro en inscribirse: [[ACTION:OPEN_LEAD_FORM:CARRERA]]
  Ejemplo: [[ACTION:OPEN_LEAD_FORM:Gastronomia]]

EJEMPLOS DE ACCIONES (FEW-SHOT):
- Usuario: "muéstrame fotos de los talleres de cocina"
  Respuesta: "[[ACTION:SHOW_GALLERY:gastronomia_talleres]] Claro que sí, aquí tienes una imagen de nuestros talleres de gastronomía equipados para tus clases prácticas."
- Usuario: "cómo es el uniforme de gastronomía?"
  Respuesta: "[[ACTION:SHOW_GALLERY:gastronomia_uniforme]] El uniforme oficial incluye mandil, gorro y guantes para tus prácticas culinarias diarias."
- Usuario: "cómo puedo pagar la matrícula por yape?"
  Respuesta: "[[ACTION:SHOW_PAYMENT:Gastronomia:250]] Puedes realizar el pago mediante Yape escaneando el código QR en pantalla por un monto de doscientos cincuenta soles."

IMPORTANTE: Si mencionas que muestras una imagen, foto o taller, DEBES incluir obligatoriamente la etiqueta [[ACTION:SHOW_GALLERY:...]].
""".strip()

_ACTIONS_KIOSK = """

ACCIONES DISPONIBLES (MODO KIOSCO):
Puedes incluir UNA accion por respuesta al inicio o al final del texto, cuando sea relevante:
- Para mostrar fotos del uniforme, talleres o instalaciones: [[ACTION:SHOW_GALLERY:ID]]
  IDs disponibles: gastronomia_uniforme, gastronomia_talleres, turismo_salidas, bartender_barra, pasteleria_horno, instituto_fachada
NO uses OPEN_LEAD_FORM ni SHOW_PAYMENT en modo kiosco. Si el usuario quiere inscribirse, indicale que pase directamente a Caja o Informes en cualquiera de nuestras sedes.

EJEMPLO KIOSCO (FEW-SHOT):
- Usuario: "quiero ver las fotos de cocina"
  Respuesta: "[[ACTION:SHOW_GALLERY:gastronomia_talleres]] Aquí en pantalla puedes apreciar nuestros talleres profesionales de gastronomía."
""".strip()


def construir_prompt_sistema(mode: str = "web") -> str:
    """Construye el prompt del sistema adaptado al modo de operacion."""
    directives = _ACTIONS_WEB if mode == "web" else _ACTIONS_KIOSK
    return f"{_BASE_PROMPT}\n\n{directives}"


def _construir_mensajes(historial: list, contexto: str, pregunta: str, mode: str = "web") -> list:
    """Ensambla el array de mensajes para la API de Groq."""
    system_prompt = construir_prompt_sistema(mode)
    mensajes = [{"role": "system", "content": system_prompt}]
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
) -> str:
    """
    Modo estandar (no streaming): espera la respuesta completa de Groq.
    Se mantiene para el endpoint /chat de compatibilidad.
    """
    mensajes = _construir_mensajes(historial, contexto, pregunta, mode=mode)
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
):
    """
    Modo streaming (v3+): retorna un AsyncStream de chunks de Groq.
    El caller itera con `async for chunk in stream` para recibir tokens
    a medida que el modelo los genera, sin esperar la respuesta completa.
    """
    mensajes = _construir_mensajes(historial, contexto, pregunta, mode=mode)
    return await _groq_client.chat.completions.create(
        messages=mensajes,
        model=settings.groq_model,
        temperature=settings.groq_temperature,
        max_tokens=settings.groq_max_tokens,
        stream=True,
    )
