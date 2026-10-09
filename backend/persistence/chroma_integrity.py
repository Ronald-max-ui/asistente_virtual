"""Read-only Chroma SQLite integrity adapter; no index policy or promotion."""
import hashlib
import sqlite3
from contextlib import closing

def sha256(data): return hashlib.sha256(data).hexdigest()

def queue_digest(db):
    rows=db.execute('SELECT id,vector,encoding FROM embeddings_queue ORDER BY seq_id').fetchall()
    return sha256(b''.join(str(identifier).encode()+b'\0'+(vector or b'')+str(encoding).encode()
                          for identifier,vector,encoding in rows))

def inspect_database(path, manifest, options, required_meta, sources):
    dbfile=path/'chroma.sqlite3'
    if not dbfile.is_file(): raise ValueError('Missing database')
    with closing(sqlite3.connect(dbfile.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0]!='ok': raise ValueError('Corrupt database')
        collections=db.execute('SELECT id,name,dimension FROM collections').fetchall()
        if len(collections)!=1 or collections[0][1:]!=(options.collection,options.dimension):
            raise ValueError('Collection incompatible')
        count=db.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0]
        if count!=manifest['chunk_count']: raise ValueError('Chunk count incompatible')
        metadata={}
        for row in db.execute('SELECT id,key,string_value FROM embedding_metadata'):
            metadata.setdefault(row[0],{})[row[1]]=row[2]
        if len(metadata)!=count: raise ValueError('Missing metadata')
        digest=[]
        for meta in metadata.values():
            if not required_meta<=meta.keys() or meta['fuente'] not in sources:
                raise ValueError('Chunk metadata incompatible')
            if meta['tipo'] in ('carrera_tecnica','curso_corto') and meta.get('program_id')!=meta['source_id']:
                raise ValueError('Programme mismatch')
            if sha256(meta['chroma:document'].encode('utf-8'))!=meta['content_sha256']:
                raise ValueError('Chunk content corrupt')
            digest.append(meta['content_sha256'])
        if sha256('\n'.join(sorted(digest)).encode())!=manifest['chunks_sha256']:
            raise ValueError('Chunk digest incompatible')
        if queue_digest(db)!=manifest['queue_sha256']:
            raise ValueError('Persistent embedding log corrupt')


def persisted_queue_digest(path):
    with closing(sqlite3.connect((path/'chroma.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
        return queue_digest(db)
