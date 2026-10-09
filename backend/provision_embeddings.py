"""Explicit model provisioning; writes model cache only, never the knowledge index."""
import json
from dataclasses import replace

def main():
    try:
        from knowledge_config import IndexSettings
        from services.knowledge_index import create_embedder
        options=replace(IndexSettings.from_env(),local_files_only=False)
        model=create_embedder(options)
        vector=next(iter(model.embed(['Información institucional'])))
        if len(vector)!=options.dimension:raise ValueError('Incompatible model dimension')
        print(json.dumps({'status':'ready','dimension':len(vector)}));return 0
    except Exception as exc:
        print(json.dumps({'status':'failed','error_type':type(exc).__name__}));return 1
if __name__=='__main__':raise SystemExit(main())
