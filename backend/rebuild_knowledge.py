"""Explicit administrative command; never rebuilds during server startup."""
import argparse
import json
from pathlib import Path
from knowledge_config import IndexSettings
from services.knowledge_index import (validate_sources, source_hashes, index_status, rebuild,
    build_worker, active_generation, check_generation, create_embedder, model_artifacts, open_collection,
    IndexErrorControlled, KNOWLEDGE)
from services.knowledge_index import verify_persisted

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    operation=parser.add_mutually_exclusive_group(required=True)
    operation.add_argument('--validate-only',action='store_true')
    operation.add_argument('--build',action='store_true')
    operation.add_argument('--check',action='store_true')
    operation.add_argument('--evaluate',action='store_true')
    operation.add_argument('--worker',type=Path,help=argparse.SUPPRESS)
    operation.add_argument('--verify',type=Path,help=argparse.SUPPRESS)
    parser.add_argument('--options',help=argparse.SUPPRESS)
    parser.add_argument('--source-root',type=Path,default=KNOWLEDGE,help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    try:
        options=IndexSettings(**json.loads(args.options)) if (args.worker or args.verify) and args.options else IndexSettings.from_env()
        if args.worker or args.verify:
            candidate=(args.worker or args.verify).resolve()
            if candidate.parent!=(options.root/'generations').resolve() or not candidate.name.startswith('gen-'):
                raise IndexErrorControlled('Invalid candidate path')
            if args.worker:
                build_worker(candidate,options,args.source_root)
                print('Candidate built and evaluated.')
            else:
                verify_persisted(candidate,options)
                print('Persisted candidate reopened and evaluated.')
        elif args.validate_only:
            report=validate_sources()
            print(json.dumps({'status':'valid','files':len(report.files),'warnings':len(report.warnings)},ensure_ascii=False))
        elif args.build:
            manifest=rebuild(options)
            print(json.dumps({'status':'ready','chunk_count':manifest['chunk_count'],
                'collection_name':manifest['collection_name'],'evaluation_passed':manifest['evaluation']['passed']}))
        elif args.evaluate:
            from services.knowledge_evaluation import evaluate
            path=active_generation(options)
            status,manifest=check_generation(path,options)
            if status['status']!='ready': raise IndexErrorControlled('Index not ready for evaluation')
            embedder=create_embedder(options)
            if model_artifacts(embedder)!=manifest['model_artifacts']:
                raise IndexErrorControlled('Model artifacts incompatible')
            result=evaluate(open_collection(path,options),embedder,options)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 0 if result['passed'] else 1
        else:
            result=index_status(options,verify_vectors=True)
            print(json.dumps(result))
            return 0 if result['status']=='ready' else 1
        return 0
    except Exception as exc:
        # Provider/library exceptions may contain paths or payloads. Only local,
        # controlled messages are printed; no stack trace/secrets on the CLI.
        message=str(exc) if isinstance(exc,IndexErrorControlled) else 'Index operation failed; active selector unchanged.'
        print(json.dumps({'status':'invalid','error':message},ensure_ascii=False))
        return 1

if __name__=='__main__': raise SystemExit(main())
