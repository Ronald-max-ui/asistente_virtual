"""Index configuration independent of cwd, Groq and server initialization."""
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / '.env', override=False)
MODEL = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
COLLECTION = 'lia_knowledge'

def backend_path(value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else BASE / path).resolve()

@dataclass(frozen=True)
class IndexSettings:
    root: Path
    model: str = MODEL
    dimension: int = 384
    collection: str = COLLECTION
    top_k: int = 6
    max_context_chunks: int = 6
    max_distance: float = 0.65
    threads: int = 2
    cache_dir: str | None = str(BASE / 'storage/embedding_models')
    local_files_only: bool = True

    def __post_init__(self):
        object.__setattr__(self, 'root', backend_path(str(self.root)))
        if self.root.is_relative_to(BASE / 'static'):
            raise ValueError('El índice debe permanecer fuera de archivos públicos.')
        if self.cache_dir is not None:
            object.__setattr__(self,'cache_dir',str(backend_path(self.cache_dir)))
        if self.model != MODEL or self.dimension != 384 or self.collection != COLLECTION:
            raise ValueError('Modelo/dimensión/colección incompatible: requiere migración explícita.')
        if not 1 <= self.top_k <= 20 or not 1 <= self.max_context_chunks <= 12:
            raise ValueError('Límites de recuperación inválidos.')
        if not 0 < self.max_distance <= 1 or not 1 <= self.threads <= 16:
            raise ValueError('Umbral/threads inválidos.')

    @classmethod
    def from_env(cls):
        cache = os.getenv('CHROMA_MODEL_CACHE','storage/embedding_models')
        return cls(root=backend_path(os.getenv('CHROMA_DB_PATH','storage/knowledge_index')),
            model=os.getenv('CHROMA_EMBEDDING_MODEL',MODEL),
            dimension=int(os.getenv('CHROMA_EMBEDDING_DIMENSION','384')),
            collection=os.getenv('CHROMA_COLLECTION_NAME',COLLECTION),
            top_k=int(os.getenv('CHROMA_TOP_K','6')),
            max_context_chunks=int(os.getenv('CHROMA_MAX_CONTEXT_CHUNKS','6')),
            max_distance=float(os.getenv('CHROMA_MAX_DISTANCE','0.65')),
            threads=int(os.getenv('CHROMA_EMBEDDING_THREADS','2')),
            cache_dir=str(backend_path(cache)) if cache else None,
            local_files_only=os.getenv('CHROMA_LOCAL_FILES_ONLY','true').lower()=='true')
