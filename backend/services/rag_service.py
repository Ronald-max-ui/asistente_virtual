"""Academic RAG using the single validated active Chroma generation.
Query routing/retrieval is shared with offline acceptance evaluation.
"""
import asyncio
import time
from services.performance import duration

from services.knowledge_index import KnowledgeIndex, IndexErrorControlled
from services.knowledge_retrieval import detectar_entidad, _normalizar_texto

from config import settings
from security.logging import safe_event

# Lazy index: no empty collection creation, network/model download or fallback.
_knowledge_index = KnowledgeIndex()

# Standalone compatibility is lazy; application composition supplies the client.
_groq_client = None

def query_client(client=None):
    global _groq_client
    if client is not None: return client
    if _groq_client is None:
        from services.llm_service import create_client
        _groq_client = create_client()
    return _groq_client

# Umbral: si la query tiene <= N palabras, se intenta reformular si hay historial
_QUERY_CORTA_UMBRAL = 5

# ── Mapeo de Alias / Entidades ────────────────────────────────────────────────
# Mapea palabras clave y alias a los identificadores canónicos usados en frontmatter YAML
# ── Asociación de Entidades a Recursos Visuales del Catálogo ─────────────────
# Permite asociar la carrera o curso activo con los recursos multimedia del catálogo
RECURSOS_POR_ENTIDAD: dict[str, list[str]] = {
    "gastronomia": ["gastronomia_talleres", "gastronomia_uniforme"],
    "turismo": ["turismo_salidas"],
    "bartender": ["bartender_barra"],
    "panaderia_pasteleria": ["pasteleria_horno"],
}


def obtener_recursos_entidad(entidad: str | None) -> list[str]:
    """Retorna los IDs de recursos visuales asociados a una entidad si existen."""
    if not entidad:
        return []
    return RECURSOS_POR_ENTIDAD.get(entidad, [])


# ── Formateo de contexto con metadatos jerárquicos ────────────────────────────

def _formatear_chunk(doc) -> str:
    """
    Formatea un chunk de ChromaDB anteponiendo sus metadatos jerárquicos.
    Ejemplo:
      [Programa: Gastronomía | Sección: Beneficios e Implementos Incluidos]
      Con el pago de la matrícula, el estudiante recibe: uniforme, insumos...
    """
    meta = doc.metadata
    titulo = meta.get("titulo", meta.get("fuente", "Información institucional"))
    h2 = meta.get("h2", "")
    h3 = meta.get("h3", "")

    if h2 and h3:
        seccion = f"{h2} > {h3}"
    elif h2:
        seccion = h2
    elif h3:
        seccion = h3
    else:
        seccion = ""

    if seccion:
        encabezado = f"[Programa: {titulo} | Sección: {seccion}]"
    else:
        encabezado = f"[Programa: {titulo}]"

    return f"{encabezado}\n{doc.page_content}"


# ── Reformulación de query ────────────────────────────────────────────────────

_PROMPT_REFORMULACION = """\
Eres un asistente que reformula preguntas cortas o ambiguas de un usuario \
para que sean útiles en una búsqueda semántica sobre programas de estudio.

Dado el historial de la conversación y la pregunta actual, escribe UNA SOLA \
línea con la búsqueda reformulada. No expliques nada. Solo escribe la búsqueda.

Si la pregunta ya es clara y completa por sí sola, devuélvela tal cual.

HISTORIAL (últimos turnos):
{historial_txt}

PREGUNTA ACTUAL: {pregunta}

BÚSQUEDA REFORMULADA:"""


def needs_reformulation(question):
    # Explicit programme + topic is already unambiguous. Follow-ups such as
    # "¿Y cuánto cuesta?" still need history and retain the approved rewrite.
    from services.knowledge_retrieval import _normalizar_texto
    topics={'virtual','presencial','aprende','aprender','aprendere','experiencia','requisitos','idiomas','duracion','horarios','sabados','precio','precios','inscripcion','matricula'}
    clear=detectar_entidad(question) and bool(set(_normalizar_texto(question).split()) & topics)
    return len(question.split())<=_QUERY_CORTA_UMBRAL and not clear

async def reformular_query(pregunta: str, historial: list, *, client=None, configuration=None) -> str:
    """
    Reescribe la query del usuario usando el contexto del historial si es corta o monosilábica.
    """
    palabras = pregunta.strip().split()
    es_corta = len(palabras) <= _QUERY_CORTA_UMBRAL

    if not historial or not es_corta:
        return pregunta

    max_turnos = 4
    ultimos = historial[-max_turnos:]
    historial_txt = "\n".join(
        f"{'Usuario' if t['role'] == 'user' else 'Asistente'}: {t['content']}"
        for t in ultimos
    )

    prompt = _PROMPT_REFORMULACION.format(
        historial_txt=historial_txt,
        pregunta=pregunta,
    )

    started=time.perf_counter()
    try:
        resp = await query_client(client).chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=(configuration or settings).groq_model,
            temperature=0,
            max_tokens=60,
            stream=False,
        )
        reformulada = resp.choices[0].message.content.strip()
        for prefijo in ("Búsqueda:", "Query:", "Búsqueda reformulada:", "-"):
            if reformulada.lower().startswith(prefijo.lower()):
                reformulada = reformulada[len(prefijo):].strip()
        if reformulada:
            safe_event('rag_query_reformulated')
            return reformulada
    except Exception as e:
        safe_event('rag_operation_failed', error=e)

    finally:duration('rag_reformulation_ms',started)
    return pregunta


# ── Búsqueda vectorial principal con Guaranteed Retrieval ─────────────────────

def _ejecutar_busqueda_sincrona(query: str, entidad: str | None, index=None) -> list:
    try:
        return [doc for doc, distance in (index or _knowledge_index).search(query, entidad)]
    except Exception as exc:
        safe_event('rag_operation_failed', error=exc)
        raise IndexErrorControlled('Knowledge index unavailable') from exc


async def buscar_contexto(query: str, historial: list | None = None, *, client=None, index=None, configuration=None) -> str:
    """
    Ejecuta similarity_search con enrutamiento de entidad en ChromaDB y devuelve el
    contexto formateado con etiquetas jerárquicas de metadatos.
    """
    # 1. Detectar entidad/programa (en query o historial)
    entidad_detectada = detectar_entidad(query, historial)
    if entidad_detectada:
        print(f"[RAG] Entidad activa detectada: '{entidad_detectada}'")

    # 2. Reformular query si el historial lo justifica
    query_efectiva = query
    if historial and needs_reformulation(query):
        query_efectiva = await reformular_query(query, historial, client=client, configuration=configuration)
        # Si la query reformulada aporta una entidad que antes no se vio
        if not entidad_detectada:
            entidad_detectada = detectar_entidad(query_efectiva)
            if entidad_detectada:
                print(f"[RAG] Entidad detectada tras reformulación: '{entidad_detectada}'")

    # 3. Búsqueda vectorial particionada en ThreadPoolExecutor para no bloquear el event loop
    docs = await asyncio.to_thread(_ejecutar_busqueda_sincrona, query_efectiva, entidad_detectada, index)

    if not docs:
        return "No se encontró información relevante."

    # 4. Formatear cada chunk con metadatos jerárquicos
    fragmentos = [_formatear_chunk(doc) for doc in docs]
    return "\n\n---\n\n".join(fragmentos)
