"""Deterministic acceptance cases against real embeddings and the candidate DB."""
from services.knowledge_retrieval import retrieve, detectar_entidad
from validate_knowledge import MONEY

CASES = (
    dict(query='¿Qué se aprende en Administración?',source='administracion',category='02_carreras',
         kind='carrera_tecnica',program='administracion',contains=['planificar']),
    dict(query='¿Gastronomía es virtual?',source='gastronomia',category='02_carreras',kind='carrera_tecnica',
         program='gastronomia',contains=['presencial','No se ofrece en modalidad virtual']),
    dict(query='¿Qué idiomas enseña Turismo?',source='turismo',category='02_carreras',kind='carrera_tecnica',
         program='turismo',contains=['japonés','inglés']),
    dict(query='¿Necesito experiencia para Bartender?',source='bartender',category='03_cursos_cortos',
         kind='curso_corto',program='bartender',contains=['No se necesita experiencia']),
    dict(query='¿Qué aprenderé en Panadería?',source='panaderia_pasteleria',category='03_cursos_cortos',
         kind='curso_corto',program='panaderia_pasteleria',contains=['fondant']),
    dict(query='¿Dónde queda el instituto?',source='institucional_general',category='01_institucional',
         kind='institucional',program=None,contains=['Bellavista','Garcilaso']),
    dict(query='¿Qué documentos necesito para matricularme?',source='admision_y_pagos',category='01_institucional',
         kind='institucional',program=None,contains=['DNI','certificado de estudios']),
    dict(query='¿Qué documentos necesito para Gastronomía?',source='admision_y_pagos',category='01_institucional',
         kind='institucional',program=None,allowed_sources=['gastronomia','admision_y_pagos'],contains=['DNI']),
    dict(query='¿Administración enseña japonés?',source='administracion',category='02_carreras',
         kind='carrera_tecnica',program='administracion',absent=['japonés']),
    dict(query='¿Contabilidad tiene clases los sábados como Bartender?',source='contabilidad',category='02_carreras',
         kind='carrera_tecnica',program='contabilidad',allow_empty=True,absent=['Puede tener clases o actividades los sábados']),
    dict(query='¿Bartender puede tener actividades los sábados?',source='bartender',category='03_cursos_cortos',
         kind='curso_corto',program='bartender',contains=['Puede tener clases o actividades los sábados'],absent=['exclusivamente']),
    dict(query='¿Cuál es el precio de matrícula?',source='admision_y_pagos',category='01_institucional',
         kind='institucional',program=None,contains=['sistema comercial']),
)

def evaluate(collection, embedder, options):
    results=[]
    for case in CASES:
        selected=retrieve(collection,embedder,case['query'],options,detectar_entidad(case['query']))
        docs=[doc for doc,_ in selected]
        text='\n'.join(doc.page_content for doc in docs).lower()
        matching=any(doc.metadata.get('source_id')==case['source'] and
            doc.metadata.get('categoria')==case['category'] and doc.metadata.get('tipo')==case['kind'] and
            doc.metadata.get('program_id')==case['program'] for doc in docs)
        isolated=all(doc.metadata.get('source_id') in case.get('allowed_sources',[case['source']]) for doc in docs)
        passed=((matching or (not docs and case.get('allow_empty',False))) and isolated and
            all(value.lower() in text for value in case.get('contains',[])) and
            all(value.lower() not in text for value in case.get('absent',[])) and not MONEY.search(text))
        results.append(dict(query=case['query'],expected_source=case['source'],expected_category=case['category'],
            expected_program=case['program'],sources=sorted({doc.metadata['source_id'] for doc in docs}),
            distances=[round(distance,4) for _,distance in selected],passed=bool(passed),
            checks=dict(expected_metadata=matching,source_isolation=isolated,
                missing_terms=[value for value in case.get('contains',[]) if value.lower() not in text],
                forbidden_terms=[value for value in case.get('absent',[]) if value.lower() in text],
                monetary_amount=bool(MONEY.search(text)))))
    return {'passed':all(item['passed'] for item in results),'cases':results}
