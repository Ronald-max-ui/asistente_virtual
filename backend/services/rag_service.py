"""
services/rag_service.py — Búsqueda vectorial RAG con Enrutamiento por Entidad y Pre-filtrado de Metadatos.

Arquitectura:
  1. Detección de entidad/programa: Mapeo de alias a IDs canónicos ("gastronomia", "turismo", etc.)
     analizando la query y el historial de conversación.
  2. Búsqueda Dirigida / Particionada (Guaranteed Retrieval):
     - Si se detecta un programa específico:
       * 3 chunks filtrados exactamente por id de la carrera (where={"id": entidad}).
       * 2 chunks institucionales de soporte (where={"tipo": "institucional"}).
       * Combinación sin duplicados con metadatos jerárquicos.
     - Si es consulta general:
       * Búsqueda global estándar en ChromaDB con k=4.
  3. Reformulación de queries cortas con Groq temperature=0.
  4. Formateo con metadatos jerárquicos: [Programa: X | Sección: Y > Z].
  5. Ejecución asíncrona en ThreadPoolExecutor para no bloquear el event loop.
"""
import asyncio
import re
import unicodedata
from functools import partial

from groq import AsyncGroq
from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
from langchain_community.vectorstores import Chroma

from config import settings

# ── Inicialización en tiempo de arranque ──────────────────────────────────────
print("[RAG] Cargando modelo de embeddings y conectando a ChromaDB...")
_embeddings = FastEmbedEmbeddings(model_name=settings.chroma_embedding_model)
_vector_db = Chroma(
    persist_directory=settings.chroma_db_path,
    embedding_function=_embeddings,
    collection_name=settings.chroma_collection_name,
)
print(f"[RAG] ChromaDB listo en coleccion '{settings.chroma_collection_name}'.")

# Cliente Groq compartido para reformulación de queries
_groq_client = AsyncGroq(api_key=settings.groq_api_key)

# Umbral: si la query tiene <= N palabras, se intenta reformular si hay historial
_QUERY_CORTA_UMBRAL = 5

# ── Mapeo de Alias / Entidades ────────────────────────────────────────────────
# Mapea palabras clave y alias a los identificadores canónicos usados en frontmatter YAML
ALIAS_A_ENTIDAD = {
    # Gastronomía
    "gastronomia": "gastronomia",
    "gastronomica": "gastronomia",
    "gastronomico": "gastronomia",
    "cocina": "gastronomia",
    "cocinero": "gastronomia",
    "chef": "gastronomia",
    "culinario": "gastronomia",
    "culinaria": "gastronomia",

    # Turismo
    "turismo": "turismo",
    "turistica": "turismo",
    "turistico": "turismo",
    "guia": "turismo",
    "guiado": "turismo",
    "viajes": "turismo",
    "japones": "turismo",

    # Administración
    "administracion": "administracion",
    "administrador": "administracion",
    "empresas": "administracion",
    "empresarial": "administracion",

    # Contabilidad
    "contabilidad": "contabilidad",
    "contable": "contabilidad",
    "contador": "contabilidad",
    "tributaria": "contabilidad",

    # Bartender
    "bartender": "bartender",
    "bar": "bartender",
    "barman": "bartender",
    "cocteleria": "bartender",
    "cocteles": "bartender",
    "mixologia": "bartender",
    "flair": "bartender",

    # Panadería y Pastelería
    "panaderia": "panaderia_pasteleria",
    "pasteleria": "panaderia_pasteleria",
    "reposteria": "panaderia_pasteleria",
    "panadero": "panaderia_pasteleria",
    "pastelero": "panaderia_pasteleria",
    "fondant": "panaderia_pasteleria",
    "buttercream": "panaderia_pasteleria",
}


def _normalizar_texto(texto: str) -> str:
    """Elimina tildes, signos y pasa a minúsculas para coincidencia robusta."""
    if not texto:
        return ""
    texto_norm = unicodedata.normalize("NFD", texto)
    texto_sin_tildes = "".join(c for c in texto_norm if unicodedata.category(c) != "Mn")
    texto_limpio = re.sub(r"[^\w\s]", " ", texto_sin_tildes.lower())
    return texto_limpio


def detectar_entidad(query: str, historial: list | None = None) -> str | None:
    """
    Detecta si la consulta (o el historial reciente) hace referencia a una carrera o curso.
    Prioriza primero la query actual, y si es ambigua o no tiene mención explícita,
    revisa los últimos mensajes del usuario y del asistente.
    """
    palabras_query = _normalizar_texto(query).split()
    for palabra in palabras_query:
        if palabra in ALIAS_A_ENTIDAD:
            return ALIAS_A_ENTIDAD[palabra]

    # Si la query actual no contiene el alias, revisar historial reciente (últimos 4 mensajes)
    if historial:
        ultimos = historial[-4:]
        for turno in reversed(ultimos):
            palabras_turno = _normalizar_texto(turno.get("content", "")).split()
            for palabra in palabras_turno:
                if palabra in ALIAS_A_ENTIDAD:
                    return ALIAS_A_ENTIDAD[palabra]

    return None


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


async def reformular_query(pregunta: str, historial: list) -> str:
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

    try:
        resp = await _groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=settings.groq_model,
            temperature=0,
            max_tokens=60,
            stream=False,
        )
        reformulada = resp.choices[0].message.content.strip()
        for prefijo in ("Búsqueda:", "Query:", "Búsqueda reformulada:", "-"):
            if reformulada.lower().startswith(prefijo.lower()):
                reformulada = reformulada[len(prefijo):].strip()
        if reformulada:
            print(f"[RAG] Query reformulada: '{pregunta}' -> '{reformulada}'")
            return reformulada
    except Exception as e:
        print(f"[RAG] Reformulacion fallida (usando query original): {e}")

    return pregunta


# ── Búsqueda vectorial principal con Guaranteed Retrieval ─────────────────────

def _ejecutar_busqueda_sincrona(query: str, entidad: str | None) -> list:
    """
    Ejecuta la búsqueda en ChromaDB de forma particionada según si hay entidad activa.
    """
    docs_resultado = []
    vistos_textos = set()

    def agregar_docs(lista):
        for d in lista:
            # Evitar chunks duplicados en la concatenación
            contenido_hash = d.page_content.strip()
            if contenido_hash not in vistos_textos:
                vistos_textos.add(contenido_hash)
                docs_resultado.append(d)

    if entidad:
        # 1. Búsqueda dirigida y garantizada para la carrera específica (hasta 6 chunks)
        try:
            docs_carrera = _vector_db.similarity_search(
                query,
                k=6,
                filter={"id": entidad},
            )
            agregar_docs(docs_carrera)
        except Exception as err:
            print(f"[RAG] Error en búsqueda filtrada de entidad {entidad}: {err}")

        # 2. Búsqueda en FAQs relevantes para la entidad
        try:
            docs_faqs = _vector_db.similarity_search(
                query,
                k=2,
                filter={"tipo": "faq"},
            )
            agregar_docs(docs_faqs)
        except Exception as err:
            print(f"[RAG] Error en búsqueda de FAQs: {err}")

        # 3. Búsqueda de apoyo institucional/general (2 chunks)
        try:
            docs_inst = _vector_db.similarity_search(
                query,
                k=2,
                filter={"tipo": "institucional"},
            )
            agregar_docs(docs_inst)
        except Exception as err:
            print(f"[RAG] Error en búsqueda de apoyo institucional: {err}")

        # Si por alguna razón la búsqueda particionada devolvió muy poco, complementar con global
        if len(docs_resultado) < 2:
            docs_extra = _vector_db.similarity_search(query, k=settings.chroma_k)
            agregar_docs(docs_extra)

    else:
        # Búsqueda global estándar si no hay entidad detectada (4 chunks)
        docs_globales = _vector_db.similarity_search(query, k=settings.chroma_k)
        agregar_docs(docs_globales)

    return docs_resultado


async def buscar_contexto(query: str, historial: list | None = None) -> str:
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
    if historial:
        query_efectiva = await reformular_query(query, historial)
        # Si la query reformulada aporta una entidad que antes no se vio
        if not entidad_detectada:
            entidad_detectada = detectar_entidad(query_efectiva)
            if entidad_detectada:
                print(f"[RAG] Entidad detectada tras reformulación: '{entidad_detectada}'")

    # 3. Búsqueda vectorial particionada en ThreadPoolExecutor para no bloquear el event loop
    loop = asyncio.get_event_loop()
    docs = await loop.run_in_executor(
        None,
        partial(_ejecutar_busqueda_sincrona, query_efectiva, entidad_detectada),
    )

    if not docs:
        return "No se encontró información relevante."

    # 4. Formatear cada chunk con metadatos jerárquicos
    fragmentos = [_formatear_chunk(doc) for doc in docs]
    return "\n\n---\n\n".join(fragmentos)
