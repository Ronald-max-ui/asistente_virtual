"""Validate Markdown sources without embeddings, providers or vector DB writes.

Exit 1 for critical issues, 0 for a valid corpus (warnings remain visible).
Optional commercial comparison reads SQLite in mode=ro, never initializes it.
"""
import argparse
import json
import re
import sqlite3
import unicodedata
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit
import yaml

BASE = Path(__file__).resolve().parent
ROOT = BASE / 'knowledge'
MONEY = re.compile(r'(?:\bS/\.?\s*\d|[$€]\s*\d|\b(?:PEN|USD|EUR)\s*\d|\b\d[\d.,]*(?:\s+\d[\d.,]*)?\s*(?:soles|PEN|USD|EUR|euros|dólares)\b)', re.I)
CONCEPT = r'(?:inscripci[oó]n|matr[ií]cula|mensualidades?|pensi[oó]n|cuotas?|pago\s+(?:al\s+)?contado|ciclo\s+completo)'
BARE_PRICE = re.compile(CONCEPT + r'\s*(?::|=|cuesta|vale)\s*\d', re.I)
FREE_PRICE = re.compile(CONCEPT+r'[^.\n]{0,45}\b(?:gratis|gratuit[ao]s?|sin\s+costo)\b|\b(?:gratis|gratuit[ao]s?)\b[^.\n]{0,30}'+CONCEPT, re.I)
FINANCIAL = re.compile(r'\b(?:descuentos?|promoci[oó]n|promociones|oferta|campaña)\b', re.I)
PERCENT = re.compile(r'\d+(?:[.,]\d+)?\s*%|\d+(?:[.,]\d+)?\s+por\s+ciento', re.I)
MONTHS = r'enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre'
DATES = re.compile(r'\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{1,2}\s+(?:de\s+)?(?:'+MONTHS+r')(?:\s+(?:de\s+)?\d{4})?\b',re.I)
INLINE_LINK = re.compile(r'!?\[[^\]\n]*\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+["\'][^\n]*?["\'])?\s*\)')
REF_DEFINITION = re.compile(r'^\s*\[([^\]]+)\]:\s*(<[^>]+>|\S+)',re.M)
REF_LINK = re.compile(r'!?\[([^\]\n]+)\]\[([^\]\n]*)\]')
HTML_LINK = re.compile(r'\b(?:src|href)\s*=\s*["\']([^"\']+)["\']',re.I)


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    file: str
    line: int
    message: str


@dataclass
class Report:
    files: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    @property
    def errors(self): return [item for item in self.findings if item.severity=='error']
    @property
    def warnings(self): return [item for item in self.findings if item.severity=='warning']
    def add(self, code, path, line, message, severity='error'):
        self.findings.append(Finding(severity,code,path,line,message))
    def data(self):
        return {'status':'invalid' if self.errors else 'valid','files':self.files,
                'errors':len(self.errors),'warnings':len(self.warnings),
                'findings':[asdict(item) for item in self.findings]}


def heading_slug(value):
    value = unicodedata.normalize('NFKC',value).lower()
    value = re.sub(r'[^\w\s-]','',value)
    return re.sub(r'\s','-',value.strip())


def document_parts(text):
    """Keep source line numbers; YAML is only retrieval metadata, never prices."""
    if not text.startswith('---\n'):
        return {},text,0
    match=re.match(r'^---\n(.*?)\n---(?:\n|$)',text,re.S)
    if not match: raise ValueError('Frontmatter delimiter missing')
    metadata=yaml.safe_load(match.group(1)) or {}
    if not isinstance(metadata,dict): raise ValueError('Metadata must be a mapping')
    return metadata,text[match.end():],text[:match.end()].count('\n')


def prose_lines(body, offset=0):
    fence=None
    for number,line in enumerate(body.splitlines(),offset+1):
        marker=re.match(r'^\s*(`{3,}|~{3,})',line)
        if marker:
            if fence is None: fence=marker.group(1)[0]
            elif marker.group(1)[0]==fence: fence=None
            continue
        if fence is None: yield number,line


def headings(body):
    return [(number,len(match.group(1)),match.group(2).strip().rstrip('#').strip())
        for number,line in prose_lines(body)
        if (match:=re.match(r'^\s{0,3}(#{1,6})\s+(.+)$',line))]


def _validate_document(path, relative, text, report):
    if not text.strip():
        report.add('empty_file',relative,1,'El archivo está vacío.')
        return {},'',0
    if '\x00' in text:
        report.add('invalid_encoding',relative,1,'El contenido incluye caracteres nulos.')
    try: metadata,body,offset=document_parts(text)
    except (ValueError,yaml.YAMLError):
        report.add('invalid_metadata',relative,1,'Los metadatos o sus delimitadores son inválidos.')
        metadata,body,offset={},text,0
    required={'id','tipo','categoria','titulo','tags'}
    if not required<=metadata.keys() or any(not isinstance(metadata.get(key),str) or not metadata[key].strip()
                                         for key in required-{'tags'}):
        report.add('missing_metadata',relative,1,'Faltan metadatos mínimos para recuperación académica.')
    if 'tags' in metadata and (not isinstance(metadata['tags'],list) or any(not isinstance(tag,str) for tag in metadata['tags'])):
        report.add('invalid_metadata',relative,1,'Tags debe ser una lista de texto.')
    for key in set(metadata)-required:
        report.add('extra_metadata',relative,1,'Mantener sólo metadatos de recuperación; hechos académicos van en el cuerpo.',severity='warning')
    if set(metadata)&{'prices','pricing','amount','currency','campaign','campaigns','promotions','settings','inicio_clases'}:
        report.add('dynamic_metadata',relative,1,'No almacenar precios, configuración o fechas de convocatoria en metadatos.')
    if not body.strip() or not any(line.strip() and not re.match(r'^\s*#',line) for _,line in prose_lines(body)):
        report.add('empty_body',relative,offset+1,'Falta contenido además de encabezados/metadatos.')
    entries=headings(body)
    if sum(level==1 for _,level,_ in entries)!=1:
        report.add('invalid_title',relative,offset+1,'Debe existir un único título H1.')
    seen=set()
    for line,level,title in entries:
        slug=heading_slug(title)
        if slug in seen: report.add('duplicate_heading',relative,line+offset,'Encabezado repetido en el documento.')
        seen.add(slug)
    for number,line in enumerate(text.splitlines(),1):
        if MONEY.search(line) or BARE_PRICE.search(line):
            report.add('monetary_amount',relative,number,'Un importe debe provenir del sistema comercial, no de Markdown.')
        if FINANCIAL.search(line) and (PERCENT.search(line) or MONEY.search(line)):
            report.add('priced_promotion',relative,number,'No publicar promociones monetarias ni porcentajes de campaña.')
        # Neutral explanations of pending/free states are allowed; unconditional
        # advertised gratuity is dynamic pricing even if no number is written.
        if FREE_PRICE.search(re.sub(r'[*_]','',line)) and not re.search(r'\b(?:si|cuando|pendiente|no\s+significa|consulta)\b',line,re.I):
            report.add('dynamic_free_price',relative,number,'La gratuidad efectiva debe consultarse en el sistema comercial.')
        if '.pricing.json' in line:
            report.add('legacy_price_reference',relative,number,'Los JSON sólo son migración; no son la fuente comercial vigente.')
        if re.search(r'^\s*`{3,}(?:json|yaml|yml|javascript|python)\b',line,re.I):
            report.add('embedded_configuration',relative,number,'No incluir configuración o código administrativo en conocimiento académico.')
        for match in DATES.finditer(line):
            value=match.group()
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
                report.add('unexpected_date_format',relative,number,'Fecha incompleta o formato inesperado; revisar antes de publicar.')
                continue
            try: date.fromisoformat(value)
            except ValueError:
                report.add('invalid_date',relative,number,'La fecha no existe en el calendario.')
                continue
            report.add('absolute_date_review',relative,number,'Clasificar la fecha como estable o temporal antes de indexar.',severity='warning')
    return metadata,body,offset


def _check_link(source, relative, link, line, root, assets, documents, report):
    try:
        parsed=urlsplit(link.strip('<>'))
    except ValueError:
        report.add('invalid_link',relative,line,'El enlace tiene un formato inválido.')
        return
    if parsed.scheme in ('http','https','mailto','tel'): return
    if parsed.scheme or parsed.netloc:
        report.add('invalid_link',relative,line,'Esquema de enlace no permitido.')
        return
    filename=unquote(parsed.path)
    if filename.startswith('/'):
        if not filename.startswith('/static/'):
            report.add('unknown_local_asset',relative,line,'No se reconoce la raíz del recurso local.')
            return
        allowed=assets
        target=(assets/filename.lstrip('/')).resolve()
    else:
        allowed=root
        target=(source.parent/filename).resolve() if filename else source
    if not target.is_relative_to(allowed):
        report.add('outside_root_link',relative,line,'El enlace sale de la raíz permitida.')
        return
    if not target.is_file():
        report.add('broken_local_link',relative,line,'El archivo o asset local no existe.')
        return
    if parsed.fragment and target.suffix.lower()=='.md':
        document=documents.get(target)
        if document and unquote(parsed.fragment) not in {heading_slug(title) for _,_,title in headings(document[1])}:
            report.add('broken_local_anchor',relative,line,'La sección enlazada no existe.')


def compare_commercial(programs, documents, root, report):
    for program in programs:
        if not program.get('enabled',True): continue
        academic=program.get('academic_path')
        if not academic:
            report.add('academic_path_missing','<commercial>',0,'Un programa activo no tiene ficha académica asociada.',severity='warning')
            continue
        target=(root/academic).resolve()
        if not target.is_relative_to(root) or target not in documents:
            report.add('program_file_missing',academic,1,'La ficha del programa comercial activo no existe.')
            continue
        meta,body,_=documents[target]
        if meta.get('id')!=program['id']:
            report.add('program_identity_mismatch',academic,1,'La identidad de la ficha no coincide con la configuración comercial.')
        if meta.get('tipo')!=program.get('kind',meta.get('tipo')):
            report.add('program_kind_mismatch',academic,1,'El tipo de programa no coincide con la configuración comercial.')
        section=re.search(r'^## Modalidades\s*\n(.*?)(?=^## |\Z)',body,re.M|re.S)
        modes=set(re.findall(r'^-\s+\*\*([^*:]+)(?::\*\*|\*\*:)',section.group(1),re.M)) if section else set()
        modes={unicodedata.normalize('NFKC',mode).lower() for mode in modes}
        if modes!=set(program['modalities']):
            report.add('modality_mismatch',academic,1,'Las modalidades declaradas no coinciden con la configuración comercial.')


def validate_knowledge(root=ROOT, *, asset_root=BASE, programs=None):
    root,assets=Path(root).resolve(),Path(asset_root).resolve()
    report,documents,ids=Report(),{},{}
    if not root.is_dir():
        report.add('missing_root','<knowledge>',0,'No existe el directorio de conocimiento.')
        return report
    paths=sorted(path for path in root.rglob('*') if path.suffix.lower()=='.md')
    if not paths: report.add('empty_corpus','<knowledge>',0,'No hay archivos Markdown.')
    for path in paths:
        relative=path.relative_to(root).as_posix()
        report.files.append(relative)
        if not path.resolve().is_relative_to(root):
            report.add('outside_root_file',relative,1,'El archivo enlaza fuera de knowledge.')
            continue
        try:
            if path.stat().st_size>2*1024*1024: raise ValueError('oversized')
            text=path.read_bytes().decode('utf-8-sig').replace('\r\n','\n')
        except UnicodeDecodeError:
            report.add('invalid_encoding',relative,1,'El archivo no tiene codificación UTF-8 válida.')
            continue
        except (OSError,ValueError):
            report.add('unreadable_file',relative,1,'No se puede leer el archivo o excede el tamaño de revisión.')
            continue
        metadata,body,offset=_validate_document(path,relative,text,report)
        documents[path.resolve()]=(metadata,body,offset)
        identifier=metadata.get('id')
        if isinstance(identifier,str):
            if identifier in ids: report.add('duplicate_id',relative,1,'Identidad de recuperación repetida en otro archivo.')
            ids[identifier]=relative
    for source,(metadata,body,offset) in documents.items():
        relative=source.relative_to(root).as_posix()
        definitions={key.lower():link for key,link in REF_DEFINITION.findall(body)}
        for line,text in prose_lines(body,offset):
            for link in INLINE_LINK.findall(text)+HTML_LINK.findall(text):
                _check_link(source,relative,link,line,root,assets,documents,report)
            for match in REF_DEFINITION.finditer(text):
                _check_link(source,relative,match.group(2),line,root,assets,documents,report)
            for label,key in REF_LINK.findall(text):
                key=(key or label).lower()
                if key not in definitions:
                    report.add('missing_link_reference',relative,line,'Referencia de enlace sin definición.')
                else: _check_link(source,relative,definitions[key],line,root,assets,documents,report)
    if programs is not None: compare_commercial(programs,documents,root,report)
    return report


def read_commercial_programs(path):
    path=Path(path).resolve()
    if not path.is_file(): raise ValueError('Commercial database unavailable')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        result=[]
        for identifier,enabled,academic,data in db.execute('SELECT id,enabled,academic_path,data_json FROM programs ORDER BY id'):
            result.append(dict(id=identifier,enabled=bool(enabled),academic_path=academic,kind=json.loads(data)['kind'],
                modalities=[row[0] for row in db.execute('SELECT code FROM modalities WHERE program_id=? ORDER BY code',(identifier,))],
                shifts=[row[0] for row in db.execute('SELECT code FROM shifts WHERE program_id=? ORDER BY code',(identifier,))]))
        return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--knowledge',type=Path,default=ROOT)
    parser.add_argument('--assets',type=Path,default=BASE,help='Raíz backend que contiene static/')
    parser.add_argument('--commercial-db',type=Path,help='Comparación opcional de modalidades en SQLite, sólo lectura')
    parser.add_argument('--json',action='store_true')
    args=parser.parse_args(argv)
    programs=None
    try:
        if args.commercial_db: programs=read_commercial_programs(args.commercial_db)
        report=validate_knowledge(args.knowledge,asset_root=args.assets,programs=programs)
    except (OSError,ValueError,sqlite3.Error,KeyError):
        report=Report()
        report.add('commercial_read_failed','<commercial>',0,'No se pudo validar la configuración comercial en modo sólo lectura.')
    if args.json: print(json.dumps(report.data(),ensure_ascii=False,indent=2))
    else:
        for finding in report.findings:
            print(f'{finding.severity.upper()} {finding.file}:{finding.line} [{finding.code}] {finding.message}')
        print(f'Conocimiento: {len(report.files)} archivos; {len(report.errors)} errores; {len(report.warnings)} advertencias.')
    return 1 if report.errors else 0


if __name__=='__main__': raise SystemExit(main())
