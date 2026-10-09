"""Legacy CLI delegates to the safe administrative builder; never deletes an index."""
import os
import glob
import sys
import yaml
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from pathlib import Path
KNOWLEDGE_DIR = str(Path(__file__).resolve().parent / 'knowledge')
HEADERS_TO_SPLIT = [('#', 'h1'), ('##', 'h2'), ('###', 'h3')]
MAX_CHUNK_SIZE = 800
CHUNK_OVERLAP = 80

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



if __name__ == '__main__':
    from rebuild_knowledge import main
    # LEGACY: --dry-run maps to validation; old bare command builds safely.
    raise SystemExit(main(['--validate-only'] if '--dry-run' in sys.argv else (sys.argv[1:] or ['--build'])))
