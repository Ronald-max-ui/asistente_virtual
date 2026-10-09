"""Shared routing/retrieval, with one query embedding and explicit metadata filters."""
import re
import unicodedata
from langchain_core.documents import Document

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
    # Explicit programme names take precedence over inferred topics (e.g. japonés).
    for palabra in palabras_query:
        if palabra in ('administracion','contabilidad','gastronomia','turismo','bartender','panaderia','pasteleria'):
            return ALIAS_A_ENTIDAD[palabra]
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


def institutional_source(query):
    words = set(_normalizar_texto(query).split())
    if words & {'documentos','documentacion','requisitos','matricularme','admision','pago','precio','precios','tarifa','matricula','inscripcion'}:
        return 'admision_y_pagos'
    if words & {'donde','direccion','queda','ubicacion','sede','sedes','contacto','telefono','instituto','institucion','q10','meet','beneficios','carnet','convalidacion','ofimatica'}:
        return 'institucional_general'
    return None


def retrieve(collection, embedder, query, options, entity=None):
    """Returns scored Documents; never embeds a query again for a related search."""
    words=set(_normalizar_texto(query).split())
    # Vocabulary expansion asks about a topic; it never supplies an answer.
    topics=[]
    if words & {'virtual','presencial','distancia','modalidad','modalidades'}:
        topics.append('Modalidades de estudio: presencial, virtual, a distancia')
    if words & {'aprende','aprendere','aprender','aprenden'}:
        topics.append('Qué aprenderás: contenidos y técnicas de formación')
    if words & {'donde','direccion','queda','ubicacion','sede','sedes'}:
        topics.append('Sedes y puntos de atención: ubicación, dirección de clases y oficina de informes')
    if words & {'precio','precios','tarifa','tarifas','costo','cuesta','cuanto'}:
        topics.append('Tarifas, promociones y campañas vigentes: sistema comercial')
    import time
    from services.performance import duration
    started=time.perf_counter()
    vector = next(iter(embedder.query_embed(query+'\n'+'\n'.join(topics)))).tolist()
    duration('embedding_ms',started)
    if len(vector) != options.dimension:
        raise ValueError('Query embedding dimension incompatible')
    source = institutional_source(query)
    # Programme-specific questions stay in their programme; generic institutional
    # queries do not inherit unrelated conversation entities.
    explicit = detectar_entidad(query)
    if source and not explicit:
        where = {'source_id':source}
    elif entity or explicit:
        where = {'program_id':entity or explicit}
    else:
        where = {'tipo':{'$in':['institucional','faq']}}
    # Preserve institutional support for a programme-specific administrative
    # question, without pulling facts from another programme. Both searches
    # receive the exact same precomputed vector.
    support_budget=min(2,options.max_context_chunks-1) if source and explicit else 0
    queries=[(where,min(options.top_k,options.max_context_chunks-support_budget))]
    if support_budget:
        queries.append(({'source_id':source},min(support_budget,options.top_k)))
    selected=[]
    seen=set()
    for query_filter,limit in queries:
        result=collection.query(query_embeddings=[vector],n_results=limit,where=query_filter,
                                include=['documents','metadatas','distances'])
        for text, meta, distance in zip(result['documents'][0],result['metadatas'][0],result['distances'][0]):
            if distance > options.max_distance or text in seen:
                continue
            seen.add(text)
            selected.append((Document(page_content=text,metadata=meta),float(distance)))
            if len(selected)>=options.max_context_chunks:
                return selected
    return selected


