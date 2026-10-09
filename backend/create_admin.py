"""Explicit, interactive first-superadmin bootstrap. No password CLI argument."""
import argparse,getpass,sys
from pathlib import Path
from commercial_runtime import database_path
from persistence.sqlite_repository import SQLiteRepository
from persistence.sqlite_admin_repository import SQLiteAdminRepository
from services.admin_service import AdminService
from domain.admin import CreateUser

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=database_path())
    parser.add_argument('--revoke-all-sessions',action='store_true',help='Administrative recovery after restoring a backup')
    args=parser.parse_args()
    if not args.revoke_all_sessions and not sys.stdin.isatty(): parser.error('Usa un terminal interactivo para introducir la contraseña sin eco')
    service=AdminService(SQLiteAdminRepository(SQLiteRepository(args.database)))
    if args.revoke_all_sessions:
        offset=0
        while True:
            users=service.repository.list_users(100,offset)
            if not users: break
            for user in users: service.repository.revoke_user(user['id'],'recovery-cli','recovery')
            offset+=100
        print('Sesiones administrativas revocadas.')
        return
    username=input('Usuario/email: ').strip()
    display_name=input('Nombre visible: ').strip()
    password=getpass.getpass('Contraseña (mínimo 12 caracteres): ')
    confirmation=getpass.getpass('Repite la contraseña: ')
    if password!=confirmation: parser.error('Las contraseñas no coinciden')
    try: service.create(CreateUser(username=username,display_name=display_name,password=password,role='superadmin'),'bootstrap-cli','bootstrap',first=True)
    except Exception: parser.error('Inicialización rechazada: revisar política de contraseña, usuario o inicialización previa')
    print('Primer superadmin creado. Ninguna contraseña fue impresa.')
if __name__=='__main__': main()
