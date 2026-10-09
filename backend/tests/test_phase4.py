"""Offline corpus validation and academic retrieval; no vector-index writes."""
import ast
import contextlib
import glob
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
import yaml
from fastapi.testclient import TestClient
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from test_phase1_api import load_server, valid_png
from test_support import repository
from services.pricing_service import PricingService
from services.llm_protocol import AssistantReply
from validate_knowledge import validate_knowledge, read_commercial_programs, main, ROOT, BASE, document_parts


def corpus_chunks():
    """Run only the existing pure Markdown loader, not ingest's imports/main."""
    source=ast.parse((BASE/'ingest.py').read_text(encoding='utf-8-sig'))
    nodes=[node for node in source.body if isinstance(node,ast.FunctionDef)
           and node.name in ('parsear_frontmatter','cargar_archivos_md')]
    namespace=dict(yaml=yaml,os=os,glob=glob,Document=Document,
        MarkdownHeaderTextSplitter=MarkdownHeaderTextSplitter,
        RecursiveCharacterTextSplitter=RecursiveCharacterTextSplitter,
        HEADERS_TO_SPLIT=[('#','h1'),('##','h2'),('###','h3')],MAX_CHUNK_SIZE=800,CHUNK_OVERLAP=80)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'academic_loader','exec'),namespace)
    with contextlib.redirect_stdout(io.StringIO()):
        return namespace['cargar_archivos_md'](str(ROOT))


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'knowledge'
        self.root.mkdir()
        self.file=self.root/'ficha.md'

    def write(self,body='# Programa\n\nInformación académica.',metadata=None):
        meta=metadata or dict(id='test',tipo='institucional',categoria='test',titulo='Programa',tags=['academico'])
        self.file.write_text('---\n'+yaml.safe_dump(meta,allow_unicode=True)+'---\n\n'+body,encoding='utf-8')

    def codes(self): return {issue.code for issue in validate_knowledge(self.root,asset_root=self.root).findings}

    def test_complete_corpus_and_commercial_modes_are_consistent(self):
        programs=read_commercial_programs(repository.path)
        report=validate_knowledge(ROOT,programs=programs)
        self.assertEqual(len(report.files),9)
        self.assertEqual(report.findings,[])
        # Read-only validation also detects admin configuration drift.
        programs[0]['modalities']=['presencial']
        self.assertIn('modality_mismatch',{f.code for f in validate_knowledge(ROOT,programs=programs).errors})

    def test_detects_amounts_promotions_and_advertised_free_tariffs(self):
        for amount in ('S/ 80','S/. 250','80 soles','PEN 80','80 USD','$80','€80','matrícula: 250'):
            self.write('# Programa\n\n'+amount)
            self.assertIn('monetary_amount',self.codes(),amount)
        for offer in ('Promoción: 20% de descuento','Campaña con 10 por ciento de descuento'):
            self.write('# Programa\n\n'+offer)
            self.assertIn('priced_promotion',self.codes())
        self.write('# Programa\n\nLa inscripción es gratuita.')
        self.assertIn('dynamic_free_price',self.codes())
        self.write('# Programa\n\nUn precio pendiente no significa gratuito.')
        self.assertEqual(self.codes(),set())

    def test_dates_invalid_incomplete_unexpected_and_stable_review(self):
        for text,code in [('15 de noviembre','unexpected_date_format'),('15 noviembre','unexpected_date_format'),('05/10/2026','unexpected_date_format'),
                          ('2026-02-30','invalid_date'),('2026-1-05','unexpected_date_format')]:
            self.write('# Programa\n\n'+text)
            self.assertIn(code,self.codes())
        self.write('# Historia\n\nFecha histórica: 2020-01-01.')
        report=validate_knowledge(self.root)
        self.assertEqual(report.errors,[])
        self.assertEqual(report.warnings[0].code,'absolute_date_review')

    def test_empty_files_bodies_bad_encoding_and_duplicate_headers(self):
        self.file.write_bytes(b'')
        self.assertIn('empty_file',self.codes())
        self.file.write_bytes(b'\xff\xfeinvalid')
        self.assertIn('invalid_encoding',self.codes())
        self.write('# Programa')
        self.assertIn('empty_body',self.codes())
        self.write('# Programa\n\n## Requisitos\nDatos.\n\n## Requisitos\nMás datos.')
        self.assertIn('duplicate_heading',self.codes())
        self.write('# Programa\n\n````markdown\n## Ejemplo\n## Ejemplo\n````\nTexto.')
        self.assertNotIn('duplicate_heading',self.codes())

    def test_local_links_assets_references_and_anchors(self):
        self.write('# Programa\n\n[No existe](ausente.md)\n![Imagen](/static/ausente.png)\n[Sección](#inexistente)\n[Referencia][missing]')
        self.assertTrue({'broken_local_link','broken_local_anchor','missing_link_reference'}<=self.codes())
        assets=self.root/'static'
        assets.mkdir()
        (assets/'image.png').write_bytes(valid_png())
        self.write('# Programa\n\n[Este documento](#programa)\n![Imagen](/static/image.png)\n[Referencia][local]\n\n[local]: ficha.md#programa')
        self.assertEqual(self.codes(),set())
        self.write('# Programa\n\n[Fuera](../../secret.md)')
        self.assertIn('outside_root_link',self.codes())
        self.write('# Programa\n\n[Inválido](http://[invalid)')
        self.assertIn('invalid_link',self.codes())

    def test_invalid_metadata_duplicate_ids_and_legacy_configuration(self):
        self.file.write_text('---\n[broken yaml\n---\n# Test\nText',encoding='utf-8')
        self.assertIn('invalid_metadata',self.codes())
        self.write('# Programa\n\n[Tarifa](test.pricing.json)')
        self.assertIn('legacy_price_reference',self.codes())
        self.write(metadata=dict(id='test',tipo='institucional',categoria='test',titulo='Test',tags=[],prices=[]))
        self.assertIn('dynamic_metadata',self.codes())
        self.write()
        (self.root/'duplicate.md').write_bytes(self.file.read_bytes())
        self.assertIn('duplicate_id',self.codes())

    def test_cli_fails_for_critical_issues_and_does_not_create_database(self):
        self.write('# Programa\n\nS/ 999')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--knowledge',str(self.root)]),1)
            missing=self.root/'missing.sqlite3'
            self.assertEqual(main(['--knowledge',str(self.root),'--commercial-db',str(missing)]),1)
        self.assertFalse(missing.exists())
        self.write()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--knowledge',str(self.root),'--json']),0)


class KnowledgePolicyTests(unittest.TestCase):
    def test_academic_loader_preserves_id_types_sections_and_learning_content(self):
        chunks=corpus_chunks()
        self.assertTrue(chunks)
        expected={'administracion':['SSOMA','planificar'], 'contabilidad':['software contable','Auditoría'],
            'gastronomia':['tabla de picar','25 estudiantes','insumos'], 'turismo':['japonés','Salidas de campo'],
            'bartender':['Mocktails','delantal','Flair'], 'panaderia_pasteleria':['fondant','buttercream','chantilly']}
        for identifier,keywords in expected.items():
            selected=[chunk for chunk in chunks if chunk.metadata['id']==identifier]
            self.assertTrue(selected,identifier)
            text='\n'.join(chunk.page_content for chunk in selected)
            for keyword in keywords: self.assertIn(keyword.lower(),text.lower())
            self.assertIn('Campo laboral',{chunk.metadata.get('h2') for chunk in selected})
            self.assertTrue(all(not isinstance(value,(list,dict)) for chunk in selected for value in chunk.metadata.values()))
        self.assertFalse(any('inicio_clases' in chunk.metadata for chunk in chunks))

    def test_saturdays_are_scoped_and_not_exclusive(self):
        allowed={'gastronomia','bartender','panaderia_pasteleria'}
        for folder in ('02_carreras','03_cursos_cortos'):
            for path in (ROOT/folder).glob('*.md'):
                _,body,_=document_parts(path.read_text(encoding='utf-8'))
                if path.stem in allowed:
                    self.assertIn('Puede tener clases o actividades los sábados',body)
                    self.assertNotIn('exclusivamente',body.lower())
                else: self.assertNotIn('sábados',body)
        faq=(ROOT/'04_faqs/preguntas_frecuentes.md').read_text(encoding='utf-8')
        self.assertIn('Esta condición no se extiende automáticamente a Administración, Contabilidad ni Turismo',faq)
        self.assertIn('no establece exclusividad',faq)

    def test_faq_uses_current_tariff_and_canonical_contact_and_requirements(self):
        text=(ROOT/'04_faqs/preguntas_frecuentes.md').read_text(encoding='utf-8')
        self.assertIn('consulta la tarifa actual',text)
        self.assertNotIn('.pricing.json',text)
        for duplicated in ('949 355 435','994 773 335','2026','15 días','partida de nacimiento'):
            self.assertNotIn(duplicated,text)
        self.assertIn('pendiente de revisión',text)
        self.assertNotIn('grabadas y disponibles en la plataforma Q10',text)

    def test_pricing_reads_database_without_opening_markdown(self):
        pricing=PricingService(repository=repository)
        original=Path.read_bytes
        def deny_markdown(path):
            if path.suffix=='.md': self.fail('Pricing must not read Markdown')
            return original(path)
        with patch.object(Path,'read_bytes',deny_markdown):
            self.assertEqual(pricing.resolve('gastronomia','inscripcion')['amount'],'80')
            self.assertEqual(pricing.resolve('gastronomia','matricula')['amount'],None)
            self.assertIn('80 soles',pricing.authoritative_answer('Precio de inscripción de Gastronomía'))

    def test_contaminated_rag_does_not_set_json_sse_or_voucher_amount(self):
        server=load_server()
        stale='La inscripción cuesta S/ 999. La matrícula cuesta 250 soles.'
        native=[{'type':'show_payment','program':'gastronomia','concept':'inscripcion'}]
        async def chunks():
            yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=stale))])
            yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content='',tool_calls=[
                types.SimpleNamespace(index=0,function=types.SimpleNamespace(name='show_payment',arguments=json.dumps({k:v for k,v in native[0].items() if k!='type'}))) ]))])
        with patch.object(server,'buscar_contexto',AsyncMock(return_value=stale)), \
             patch.object(server,'generar_respuesta_llm',AsyncMock(return_value=AssistantReply(assistant_text=stale,structured_actions=native))), \
             patch.object(server,'stream_respuesta_llm',AsyncMock(return_value=chunks())), \
             patch.object(server,'generar_audio_bytes',AsyncMock(return_value=b'a')), TestClient(server.app) as client:
            question='Quiero pagar la inscripción de Gastronomía'
            standard=client.post('/chat',json={'mensaje':question,'session_id':'price-json'}).json()
            stream=client.post('/chat/stream',json={'mensaje':question,'session_id':'price-sse'})
            self.assertEqual(stream.status_code,200)
            events=[json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith('data: ')]
            action=next(event['action'] for event in events if event['type']=='ui_action')
            self.assertEqual(standard['actions'][0]['amount'],'80')
            self.assertEqual(action['amount'],'80')
            self.assertNotIn('999',standard['texto'])
            self.assertNotIn('250',events[-1]['full_text'])
            fields={'carrera':'gastronomia','concepto':'inscripcion','monto':'999'}
            denied=client.post('/api/vouchers',data=fields,files={'imagen':('receipt.png',valid_png(),'image/png')})
            self.assertEqual(denied.status_code,422)
            accepted=client.post('/api/vouchers',data={**fields,'monto':'80'},files={'imagen':('receipt.png',valid_png(),'image/png')})
            self.assertEqual(accepted.status_code,200)
            record=server.session_manager.repository.get_record('vouchers',accepted.json()['voucher_id'])
            self.assertEqual(record['amount'],'80')


class AcademicRetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_rag_routing_reads_academic_chunks_without_real_embeddings(self):
        chunks=corpus_chunks()
        calls=[]
        class ReadOnlyFakeStore:
            def similarity_search(self,query,k,filter=None):
                calls.append(filter)
                return [chunk for chunk in chunks if not filter or all(chunk.metadata.get(key)==value for key,value in filter.items())][:k]
        store=ReadOnlyFakeStore()
        config=types.ModuleType('config')
        config.settings=types.SimpleNamespace(groq_api_key='test',groq_model='test',chroma_embedding_model='test',
            chroma_db_path='not-opened',chroma_collection_name='knowledge',chroma_k=4)
        groq=types.ModuleType('groq'); groq.AsyncGroq=lambda **kwargs:None
        embedding=types.ModuleType('langchain_community.embeddings.fastembed')
        embedding.FastEmbedEmbeddings=lambda **kwargs:None
        vectors=types.ModuleType('langchain_community.vectorstores'); vectors.Chroma=lambda **kwargs:store
        spec=importlib.util.spec_from_file_location('phase4_rag',BASE/'services/rag_service.py')
        rag=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'config':config,'groq':groq,'langchain_community.embeddings.fastembed':embedding,
                                    'langchain_community.vectorstores':vectors}),contextlib.redirect_stdout(io.StringIO()):
            spec.loader.exec_module(rag)
            # Fase 5 replaces the vector-store adapter; keep this offline Fase 4
            # fixture at the index contract, without opening a real database.
            def offline_search(query, entity):
                return [(doc, 0.1) for doc in store.similarity_search(query,4,{'id':entity})]
            rag._knowledge_index.search=offline_search
            for query,identifier in [('Gastronomía','gastronomia'),('Administración','administracion'),('Contabilidad','contabilidad'),
                ('Turismo','turismo'),('Bartender','bartender'),('Panadería','panaderia_pasteleria')]:
                context=await rag.buscar_contexto(query)
                self.assertIn({'id':identifier},calls)
                self.assertIn('Descripción',context)
                self.assertNotIn('2026-10-05',context)
                self.assertNotIn('.pricing.json',context)


if __name__=='__main__': unittest.main()
