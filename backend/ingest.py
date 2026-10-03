"""
ingest.py — Indexación de la base de conocimiento estructurada en Markdown.

Fase 3 del proceso de normalización RAG:
  - Lee los archivos .md de backend/knowledge/ (estructura Single Source of Truth).
  - Extrae el frontmatter YAML de cada archivo para enriquecer los metadatos.
  - Divide el contenido por jerarquía de títulos con MarkdownHeaderTextSplitter,
    preservando el contexto semántico de cada sección.
  - LIMPIA la colección ChromaDB existente antes de re-indexar para eliminar
    completamente los vectores del esquema antiguo (archivos .docx).
  - Re-indexa con FastEmbed (ONNX) y persiste en ./chroma_db.

Uso:
    python ingest.py
    python ingest.py --dry-run   # Muestra estadísticas sin indexar
"""

import os
import glob
import sys
import re
import time

import yaml
import chromadb
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document

# ── Configuración ─────────────────────────────────────────────────────────────
KNOWLEDGE_DIR    = "./knowledge"          # Nueva base MD estructurada
DB_DIR           = "./chroma_db"          # Directorio persistente de ChromaDB
COLLECTION_NAME  = "knowledge"            # Nombre de colección (igual que en rag_service.py)
EMBEDDING_MODEL  = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# MarkdownHeaderTextSplitter: divide por jerarquía de títulos
HEADERS_TO_SPLIT = [
    ("#",  "h1"),
    ("##", "h2"),
    ("###","h3"),
]

# RecursiveCharacterTextSplitter: subdivisión de secciones largas
MAX_CHUNK_SIZE    = 800   # Caracteres máximos por chunk
CHUNK_OVERLAP     = 80    # Solapamiento para preservar contexto entre chunks

# ── Utilidades ────────────────────────────────────────────────────────────────

def parsear_frontmatter(contenido: str) -> tuple[dict, str]:
    """
    Extrae el frontmatter YAML delimitado por --- del inicio del archivo.
    Devuelve (metadata_dict, cuerpo_sin_frontmatter).
    Si no hay frontmatter válido, devuelve ({}, contenido_original).
    """
    if not contenido.startswith("---"):
        return {}, contenido

    partes = contenido.split("---", 2)
    if len(partes) < 3:
        return {}, contenido

    try:
        metadata = yaml.safe_load(partes[1]) or {}
    except yaml.YAMLError as e:
        print(f"  [WARN] Error al parsear YAML: {e}")
        metadata = {}

    return metadata, partes[2].strip()


def limpiar_coleccion_chroma(db_dir: str, collection_name: str) -> None:
    """
    Elimina la colección ChromaDB existente para garantizar una re-indexación
    limpia. Esto borra completamente los vectores del esquema anterior (.docx).
    """
    try:
        client = chromadb.PersistentClient(path=db_dir)
        colecciones_existentes = [c.name for c in client.list_collections()]
        if collection_name in colecciones_existentes:
            client.delete_collection(collection_name)
            print(f"[OK] Coleccion '{collection_name}' eliminada. Re-indexando desde cero.")
        else:
            print(f"[INFO] Coleccion '{collection_name}' no existia. Se creara nueva.")
    except Exception as e:
        print(f"[WARN] No se pudo limpiar ChromaDB: {e}. Continuando...")


def cargar_archivos_md(knowledge_dir: str) -> list[Document]:
    """
    Recorre recursivamente knowledge_dir, parsea el frontmatter YAML de cada
    .md y aplica MarkdownHeaderTextSplitter + RecursiveCharacterTextSplitter.

    Cada chunk resultante hereda los metadatos del frontmatter más los
    encabezados de la sección (h1/h2/h3) para filtrado preciso en ChromaDB.
    """
    patron = os.path.join(knowledge_dir, "**", "*.md")
    archivos = sorted(glob.glob(patron, recursive=True))

    if not archivos:
        print(f"[ERROR] No se encontraron archivos .md en '{knowledge_dir}'.")
        return []

    splitter_md = MarkdownHeaderTextSplitter(
        headers_to_split_on=HEADERS_TO_SPLIT,
        strip_headers=False,  # Conservar el encabezado dentro del texto del chunk
    )

    splitter_rec = RecursiveCharacterTextSplitter(
        chunk_size=MAX_CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )

    todos_los_chunks: list[Document] = []

    for ruta in archivos:
        nombre_corto = os.path.relpath(ruta, knowledge_dir)
        with open(ruta, "r", encoding="utf-8") as f:
            contenido_completo = f.read()

        # 1. Extraer frontmatter YAML
        fm_meta, cuerpo = parsear_frontmatter(contenido_completo)

        if not cuerpo.strip():
            print(f"  [SKIP] {nombre_corto} — sin contenido tras el frontmatter.")
            continue

        # 2. Dividir por jerarquía de títulos Markdown
        chunks_md = splitter_md.split_text(cuerpo)

        # 3. Sub-dividir secciones largas con RecursiveCharacterTextSplitter
        chunks_finales: list[Document] = []
        for chunk in chunks_md:
            sub = splitter_rec.split_documents([chunk])
            chunks_finales.extend(sub)

        # 4. Enriquecer cada chunk con metadatos del frontmatter + ruta
        for chunk in chunks_finales:
            chunk.metadata.update({
                **fm_meta,                              # id, tipo, categoria, titulo, tags...
                "fuente": nombre_corto.replace("\\", "/"),  # Ruta relativa normalizada
            })
            # Convertir tags a string si es lista (ChromaDB no acepta listas en metadata)
            if isinstance(chunk.metadata.get("tags"), list):
                chunk.metadata["tags"] = ", ".join(chunk.metadata["tags"])

        todos_los_chunks.extend(chunks_finales)
        print(f"  [OK] {nombre_corto} — {len(chunks_finales)} chunks")

    return todos_los_chunks


# ── Indexación principal ──────────────────────────────────────────────────────

def indexar_conocimiento(dry_run: bool = False) -> None:
    print("=" * 60)
    print("  INDEXACION DE BASE DE CONOCIMIENTO — Tuinen Star")
    print("=" * 60)

    # 1. Cargar y fragmentar archivos Markdown
    print(f"\n[1/4] Cargando archivos .md desde '{KNOWLEDGE_DIR}'...")
    chunks = cargar_archivos_md(KNOWLEDGE_DIR)

    if not chunks:
        print("[ERROR] No hay chunks para indexar. Revisa la carpeta knowledge/.")
        return

    print(f"\n  Total de chunks generados: {len(chunks)}")

    if dry_run:
        print("\n[DRY-RUN] Simulacion completada. No se modifico ChromaDB.")
        for i, c in enumerate(chunks[:5]):
            print(f"\n  Chunk {i+1}: {c.metadata.get('fuente')} | {c.metadata.get('h2','')}")
            print(f"  Texto: {c.page_content[:120]}...")
        return

    # 2. Limpiar coleccion anterior (elimina vectores de los .docx viejos)
    print(f"\n[2/4] Limpiando coleccion ChromaDB anterior...")
    limpiar_coleccion_chroma(DB_DIR, COLLECTION_NAME)

    # 3. Generar embeddings con FastEmbed (ONNX — sin GPU requerida)
    print(f"\n[3/4] Cargando modelo de embeddings FastEmbed...")
    print(f"  Modelo: {EMBEDDING_MODEL}")
    embeddings = FastEmbedEmbeddings(model_name=EMBEDDING_MODEL)

    # 4. Indexar en ChromaDB
    print(f"\n[4/4] Indexando {len(chunks)} chunks en ChromaDB...")
    t0 = time.time()

    Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=DB_DIR,
        collection_name=COLLECTION_NAME,
    )

    elapsed = time.time() - t0
    print(f"\n[COMPLETADO] {len(chunks)} chunks indexados en {elapsed:.1f}s")
    print(f"  Base vectorial en: {os.path.abspath(DB_DIR)}")
    print(f"  Coleccion: '{COLLECTION_NAME}'")
    print("=" * 60)


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    indexar_conocimiento(dry_run=dry_run)