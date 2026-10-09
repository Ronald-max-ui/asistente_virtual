"""Scan Git candidates and compiled frontend; findings never include secret values."""
import json,os,re,subprocess
from pathlib import Path
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parents[1]
def scan():
    load_dotenv(ROOT/'backend/.env')
    known=[os.getenv(key,'') for key in ('GROQ_API_KEY','ADMIN_API_TOKEN') if len(os.getenv(key,''))>=12]
    patterns={'provider_key':re.compile(r'(?:gsk_[A-Za-z0-9]{20,}|sk-proj-[A-Za-z0-9_-]{30,}|gh[pousr]_[A-Za-z0-9]{36,}|AKIA[0-9A-Z]{16})'),
        'private_key':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')}
    candidates=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
    paths={ROOT/name for name in candidates if name}
    paths.update((ROOT/'avatar-kiosk/dist').rglob('*'))
    findings=[];checked=0
    for path in sorted(paths):
        if not path.is_file() or path.suffix.lower() not in ('.py','.js','.mjs','.html','.json','.md','.txt','.toml','.yaml','.yml','.example'):continue
        try:content=path.read_text(encoding='utf-8-sig')
        except (UnicodeError,OSError):continue
        checked+=1
        for number,line in enumerate(content.splitlines(),1):
            kinds=[name for name,regex in patterns.items() if regex.search(line)]
            if any(value in line for value in known):kinds.append('configured_credential')
            for kind in kinds:findings.append({'file':str(path.relative_to(ROOT)).replace('\\','/'),'line':number,'kind':kind})
    return {'passed':not findings,'files_checked':checked,'findings':findings}
if __name__=='__main__':
    result=scan();print(json.dumps(result));raise SystemExit(0 if result['passed'] else 1)
