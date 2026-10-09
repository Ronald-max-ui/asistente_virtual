"""Real HTTP/RBAC/SQLite administration, exclusively temporary databases."""
import io,json,os,sqlite3,sys,tempfile,threading,unittest
from pathlib import Path
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from domain.admin import CreateUser
from security.admin_config import AdminSettings
from security.admin_policy import ROLES,ALL
from security.config import SecuritySettings,RatePolicy
from persistence.sqlite_repository import SQLiteRepository
from persistence.sqlite_admin_repository import SQLiteAdminRepository
from persistence.repository import RepositoryConflict
from services.admin_service import AdminService,AdminError
from services.commercial_service import CommercialService,payload
from services.pricing_service import PricingService
from migrate_commercial import migrate,seed_configuration
from test_phase1_api import load_server
PASSWORD='Synthetic!SafePassphrase2026'
ORIGIN='http://localhost:5173'
class AdminTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.repo=SQLiteRepository(self.root/'commercial.sqlite3')
        migrate(self.repo);seed_configuration(self.repo)
        self.commercial=CommercialService(self.repo)
        self.admin=AdminService(SQLiteAdminRepository(self.repo),AdminSettings(memory_cost=19456,time_cost=2,legacy_enabled=False))
        self.user=self.create('root_admin','superadmin',first=True)
        self.server=load_server(pricing=PricingService(repository=self.repo),real_session_auth=True)
        self.server.app.state.commercial_service=self.commercial
        self.server.app.state.admin_service=self.admin
        self.client=TestClient(self.server.app);self.addCleanup(self.client.close)
    def create(self,name,role='solo_lectura',first=False):
        return self.admin.create(CreateUser(username=name,display_name='Persona sintética',password=PASSWORD,role=role),'test-bootstrap','test',first)
    def login(self,name='root_admin',password=PASSWORD,client=None):
        return (client or self.client).post('/api/admin/auth/login',json={'username':name,'password':password},headers={'Origin':ORIGIN})
    def csrf(self,client=None):
        return {'Origin':ORIGIN,'X-CSRF-Token':(client or self.client).get('/api/admin/auth/csrf').json()['csrf_token']}
    def test_superadmin_bootstrap_hash_and_idempotent_initialization(self):
        user=self.admin.repository.find_user('root_admin')
        self.assertTrue(user['password_hash'].startswith('$argon2id$'))
        self.assertNotEqual(user['password_hash'],PASSWORD)
        self.assertNotIn('password_hash',self.user)
        with self.assertRaises(RepositoryConflict):self.create('another_root','superadmin',first=True)
        self.assertEqual(ROLES['superadmin'],ALL)
    def test_interactive_bootstrap_cli_does_not_print_password(self):
        from create_admin import main
        database=self.root/'bootstrap.sqlite3'
        with patch('sys.argv',['create_admin.py','--database',str(database)]),patch('sys.stdin.isatty',return_value=True),patch('builtins.input',side_effect=['cli_root','CLI fixture']),patch('getpass.getpass',side_effect=[PASSWORD,PASSWORD]),patch('sys.stdout',new_callable=io.StringIO) as output:
            main()
            self.assertNotIn(PASSWORD,output.getvalue())
        user=SQLiteAdminRepository(SQLiteRepository(database)).find_user('cli_root')
        self.assertEqual(user['role_id'],'superadmin');self.assertTrue(user['password_hash'].startswith('$argon2id$'))

    def test_login_me_cookie_and_secret_minimization(self):
        response=self.login();self.assertEqual(response.status_code,204)
        cookie=response.headers['set-cookie'];self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=strict',cookie);self.assertIn('Path=/api/admin',cookie)
        me=self.client.get('/api/admin/auth/me');self.assertEqual(me.status_code,200)
        self.assertEqual(set(me.json()),{'id','display_name','role','permissions'})
        self.assertNotIn('csrf',me.text);self.assertNotIn('password',me.text)
        rows=self.admin.repository.list_users();self.assertNotIn('password_hash',json.dumps(rows))
        with self.repo.transaction() as unit:
            row=dict(unit.db.execute('SELECT * FROM admin_sessions').fetchone())
        token=self.client.cookies.get(self.admin.settings.cookie_name)
        self.assertNotIn(token,json.dumps(row));self.assertEqual(len(row['token_hash']),64)
        self.assertNotIn('token_hash',json.dumps(self.admin.repository.sessions(self.user['id'])))
    def test_incorrect_disabled_and_unknown_login_are_indistinguishable(self):
        limited=self.create('disabled_user');self.admin.repository.change_user(limited['id'],dict(display_name='D',role='solo_lectura',enabled=False),self.user['id'],'test')
        responses=[self.login(name,password) for name,password in [('root_admin','WrongSynthetic'),('missing_user',PASSWORD),('disabled_user',PASSWORD)]]
        for r in responses:self.assertEqual(r.status_code,401);self.assertEqual(r.json()['message'],'Credenciales incorrectas')
    def test_account_rate_limit_normalization(self):
        for _ in range(5):self.assertEqual(self.login('ROOT_ADMIN','Wrong').status_code,401)
        self.assertEqual(self.login('root_admin').status_code,429)
        self.assertEqual(self.login('other_unknown').status_code,401)
    def test_ip_login_rate_limit(self):
        self.server.app.state.security_settings=replace(SecuritySettings(),policies={**SecuritySettings().policies,'admin_login':RatePolicy(2)})
        for n in range(2):self.assertEqual(self.login('unknown_'+str(n)).status_code,401)
        self.assertEqual(self.login('unknown_3').status_code,429)
        self.assertEqual(self.client.get('/health/live').status_code,200)
    def test_csrf_and_origin_enforced_and_bearer_cannot_bypass_cookie(self):
        self.login();record=payload(self.commercial.list('programs')[0]);url='/api/admin/programs/'+record['id']
        self.assertEqual(self.client.put(url,json=record,headers={'Origin':ORIGIN}).status_code,403)
        headers=self.csrf();headers['Origin']='https://malicious.invalid'
        self.assertEqual(self.client.put(url,json=record,headers=headers).status_code,403)
        headers=self.csrf();headers.pop('Origin');self.assertEqual(self.client.put(url,json=record,headers=headers).status_code,403)
        self.assertEqual(self.client.put(url,json=record,headers=self.csrf()).status_code,200)
        self.server.app.state.admin_api_token='legacy-fixture-token'
        self.assertEqual(self.client.put(url,json=record,headers={'Authorization':'Bearer legacy-fixture-token'}).status_code,403)
    def test_logout_invalidates_server_session_and_cookie(self):
        self.login();token=self.client.cookies.get(self.admin.settings.cookie_name)
        response=self.client.post('/api/admin/auth/logout',headers=self.csrf());self.assertEqual(response.status_code,204)
        with self.assertRaises(AdminError):self.admin.session(token)
        self.assertEqual(self.client.get('/api/admin/auth/me').status_code,401)
    def test_session_inactivity_and_absolute_expiration(self):
        self.admin.clock=lambda:1000
        token=self.admin.login('root_admin',PASSWORD,'test')
        self.admin.clock=lambda:1000+self.admin.settings.inactivity
        with self.assertRaises(AdminError):self.admin.session(token)
        self.admin.clock=lambda:2000;token=self.admin.login('root_admin',PASSWORD,'test')
        for age in range(1000,self.admin.settings.lifetime,1000):
            self.admin.clock=lambda age=age:2000+age;self.admin.session(token)
        self.admin.clock=lambda:2000+self.admin.settings.lifetime
        with self.assertRaises(AdminError):self.admin.session(token)
    def test_disabled_user_and_password_change_revoke_sessions(self):
        user=self.create('mutable_user');self.login('mutable_user');token=self.client.cookies.get(self.admin.settings.cookie_name)
        self.admin.repository.change_user(user['id'],dict(display_name='Disabled',role='solo_lectura',enabled=False),self.user['id'],'test')
        with self.assertRaises(AdminError):self.admin.session(token)
        self.client.cookies.clear();self.login();token=self.client.cookies.get(self.admin.settings.cookie_name)
        self.admin.change_password(self.user['id'],'Another!SyntheticPassphrase2026',self.user['id'],'test')
        with self.assertRaises(AdminError):self.admin.session(token)
    def test_role_change_reflected_and_readonly_403(self):
        user=self.create('commercial_admin','administrador');self.login('commercial_admin')
        record=payload(self.commercial.list('programs')[0]);url='/api/admin/programs/'+record['id']
        self.assertEqual(self.client.put(url,json=record,headers=self.csrf()).status_code,200)
        self.admin.repository.change_user(user['id'],dict(display_name='Reader',role='solo_lectura',enabled=True),self.user['id'],'test')
        self.assertEqual(self.client.get('/api/admin/programs').status_code,200)
        self.assertEqual(self.client.put(url,json=record,headers=self.csrf()).status_code,403)
        self.assertEqual(self.client.get('/api/admin/users').status_code,403)
    def test_role_permissions_for_admissions_and_payment_review(self):
        self.create('admissions_user','admisiones');self.login('admissions_user')
        self.assertEqual(self.client.get('/api/admin/leads').status_code,200)
        self.assertEqual(self.client.get('/api/admin/vouchers').status_code,403)
        self.client.cookies.clear();self.create('review_user','revisor_pagos');self.login('review_user')
        self.assertEqual(self.client.get('/api/admin/vouchers').status_code,200)
        self.assertEqual(self.client.get('/api/admin/leads').status_code,403)
    def test_last_superadmin_guard(self):
        with self.assertRaises(RepositoryConflict):self.admin.repository.change_user(self.user['id'],dict(display_name='No',role='solo_lectura',enabled=False),self.user['id'],'test')
    def test_sessions_can_be_revoked_individually_and_all(self):
        token1=self.admin.login('root_admin',PASSWORD,'test');token2=self.admin.login('root_admin',PASSWORD,'test')
        sessions=self.admin.repository.sessions(self.user['id']);self.admin.repository.revoke_one(self.user['id'],sessions[-1]['id'],self.user['id'],'test')
        with self.assertRaises(AdminError):self.admin.session(token1)
        self.admin.session(token2);self.admin.repository.revoke_user(self.user['id'],self.user['id'],'test')
        with self.assertRaises(AdminError):self.admin.session(token2)
    def test_price_campaign_avatar_and_settings_audit_and_history(self):
        self.login();h=self.csrf()
        price=payload(next(p for p in self.commercial.list('prices') if p['status']=='active'))
        original=price['amount'];price['amount']='120'
        self.assertEqual(self.client.put('/api/admin/prices/'+price['id'],json=price,headers=h).status_code,200)
        campaign=dict(id='audit_october',name='October test',starts_on='2026-10-01',ends_on='2026-10-31',enabled=True)
        self.assertEqual(self.client.post('/api/admin/campaigns',json=campaign,headers=h).status_code,201)
        self.assertEqual(self.client.post('/api/admin/avatars/lia_original/activate',headers=h).status_code,200)
        settings=self.commercial.settings();settings['assistant_name']='Lía test'
        self.assertEqual(self.client.put('/api/admin/settings',json=settings,headers=h).status_code,200)
        audit=self.client.get('/api/admin/audit').json();actions={r['action'] for r in audit}
        self.assertTrue({'prices.save','campaigns.save','avatars.activate','settings.save'}<=actions)
        change=next(r for r in audit if r['action']=='prices.save')
        self.assertEqual(change['before']['amount'],original);self.assertEqual(change['after']['amount'],'120');self.assertEqual(change['actor_user_id'],self.user['id'])
        self.assertNotIn(PASSWORD,json.dumps(audit));self.assertNotIn('password_hash',json.dumps(audit))
        with self.assertRaises(RepositoryConflict):
            with self.repo.transaction(write=True) as u:u.db.execute("DELETE FROM admin_audit_log")
    def test_failed_commercial_change_rolls_back_audit(self):
        before=len(self.admin.repository.audit(1000));campaign=dict(id='bad',name='Bad',starts_on='2026-11-30',ends_on='2026-10-01')
        with self.assertRaises(ValueError):self.commercial.save('campaigns',campaign,self.user['id'])
        self.assertEqual(len(self.admin.repository.audit(1000)),before)
    def voucher(self):
        runtime=self.server.app.state.services.session.repository
        tariff=dict(program='turismo',modality=None,shift=None,concept='inscripcion',amount='80',currency='PEN',campaign='base')
        return runtime.save_voucher(None,tariff,'testhash',None,lambda:('voucher_test','fixture.png'),lambda _:None)['voucher_id']
    def test_voucher_review_audit_and_final_transition(self):
        identifier=self.voucher();self.login();h=self.csrf()
        url='/api/admin/vouchers/'+identifier+'/review'
        response=self.client.post(url,json=dict(status='approved',review_note='Revisado manualmente'),headers=h)
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['reviewed_by'],self.user['id'])
        self.assertEqual(self.client.post(url,json=dict(status='rejected'),headers=h).status_code,409)
        changes=self.client.get('/api/admin/audit').json();review=next(r for r in changes if r['action']=='vouchers.review')
        self.assertEqual(review['before']['status'],'pending_review');self.assertEqual(review['after']['status'],'approved')
        self.assertNotIn('file_reference',json.dumps(changes));self.assertNotIn('Revisado manualmente',json.dumps(changes))
    def test_voucher_rejected_and_malicious_note_validation(self):
        identifier=self.voucher();self.login();h=self.csrf();url='/api/admin/vouchers/'+identifier+'/review'
        for note in ['<script>alert(1)</script>','x'*1001]:self.assertEqual(self.client.post(url,json=dict(status='rejected',review_note=note),headers=h).status_code,422)
        self.assertEqual(self.client.post(url,json=dict(status='rejected'),headers=h).status_code,200)
    def test_concurrent_review_only_one_commits_with_audit(self):
        identifier=self.voucher();repo=self.server.app.state.services.session.repository;barrier=threading.Barrier(2)
        def review(status):
            barrier.wait()
            try:return repo.review_voucher(identifier,status,'',self.user['id'],'concurrent')['status']
            except Exception:return None
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(review,['approved','rejected']))
        self.assertEqual(sum(r is not None for r in results),1);self.assertEqual(len(repo.admin_audit()),1)
    def test_production_secure_cookie_and_http_refusal(self):
        self.admin.settings=replace(self.admin.settings,secure=True,cookie_name='__Secure-lia_admin_session')
        self.server.app.state.security_settings=replace(SecuritySettings(),allowed_origins=('https://lia.example.org',))
        with TestClient(self.server.app,base_url='https://lia.example.org') as client:
            result=client.post('/api/admin/auth/login',json=dict(username='root_admin',password=PASSWORD),headers={'Origin':'https://lia.example.org'})
            self.assertEqual(result.status_code,204);self.assertIn('Secure',result.headers['set-cookie']);self.assertIn('HttpOnly',result.headers['set-cookie'])
            self.assertEqual(client.get('/api/admin/auth/me').status_code,200)
        self.assertEqual(self.client.post('/api/admin/auth/login',json=dict(username='root_admin',password=PASSWORD),headers={'Origin':'https://lia.example.org'}).status_code,403)
    def test_weak_password_and_insecure_production_config_rejected(self):
        with self.assertRaises(AdminError):self.admin.password_hash('aaaaaaaaaaaa')
        with patch.dict(os.environ,APP_ENV='production',ADMIN_COOKIE_SECURE='false'),self.assertRaises(ValueError):AdminSettings.from_env()
        with self.assertRaises(ValueError):AdminSettings(inactivity=60,lifetime=999999)
    def test_legacy_explicit_flag_no_panel_token_and_auditable_actor(self):
        self.server.app.state.admin_api_token='fixture-legacy-not-real'
        headers={'Authorization':'Bearer fixture-legacy-not-real'}
        self.assertEqual(self.client.get('/api/admin/programs',headers=headers).status_code,401)
        self.admin.settings=replace(self.admin.settings,legacy_enabled=True)
        self.assertEqual(self.client.get('/api/admin/programs',headers=headers).status_code,200)
        record=payload(self.commercial.list('programs')[0]);self.client.put('/api/admin/programs/'+record['id'],json=record,headers=headers)
        self.assertEqual(self.admin.repository.audit()[0]['actor_user_id'],'legacy-token')
        self.assertEqual(self.client.get('/api/admin/auth/me',headers=headers).status_code,401)
    def test_backup_cli_does_not_upgrade_or_write_source(self):
        from backup_commercial import backup_commercial
        from backup_runtime import ReadOnlyRuntimeSnapshot
        source=self.root/'old.sqlite3'
        with closing(sqlite3.connect(source)) as db:
            db.execute('CREATE TABLE marker(value TEXT)');db.execute("INSERT INTO marker VALUES('old')");db.execute('PRAGMA user_version=1');db.commit()
        before=source.read_bytes()
        backup_commercial(source,self.root/'old-commercial-backup.sqlite3')
        ReadOnlyRuntimeSnapshot(source).backup(self.root/'old-runtime-backup.sqlite3')
        self.assertEqual(source.read_bytes(),before)

    def test_backup_includes_users_roles_sessions_audit_and_runtime_reviews(self):
        self.login();self.voucher();runtime=self.server.app.state.services.session.repository
        runtime.review_voucher('voucher_test','rejected','',self.user['id'],'test')
        backup=self.repo.backup(self.root/'commercial-backup.sqlite3')
        from verify_admin_backup import verify
        self.assertEqual(verify(backup)['status'],'valid')
        with closing(sqlite3.connect(backup)) as db:
            for table in ('admin_users','admin_roles','admin_sessions','admin_audit_log'):self.assertGreater(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
            self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0],'ok')
        backup=runtime.backup(self.root/'runtime-backup.sqlite3')
        with closing(sqlite3.connect(backup)) as db:self.assertEqual(db.execute('SELECT count(*) FROM voucher_reviews').fetchone()[0],1);self.assertEqual(db.execute('SELECT count(*) FROM admin_audit_log').fetchone()[0],1)
    def test_logs_are_sanitized_and_bad_requests_do_not_echo_passwords(self):
        import logging
        from security.logging import logger
        capture=io.StringIO();handler=logging.StreamHandler(capture);logger.addHandler(handler);logger.setLevel(logging.INFO)
        try:
            self.login(password='WrongSensitiveSyntheticPassword');self.login()
            self.assertNotIn('WrongSensitiveSyntheticPassword',capture.getvalue());self.assertNotIn(PASSWORD,capture.getvalue());self.assertNotIn('root_admin',capture.getvalue());self.assertNotIn('$argon2id$',capture.getvalue())
        finally:logger.removeHandler(handler);logger.setLevel(logging.WARNING)
        response=self.client.post('/api/admin/auth/login',json=dict(username='bad',password=PASSWORD,arbitrary='secret'),headers={'Origin':ORIGIN})
        self.assertEqual(response.status_code,422);self.assertNotIn(PASSWORD,response.text)
    def test_admin_page_is_separate_accessible_no_inline_code(self):
        page=self.client.get('/admin/');self.assertEqual(page.status_code,200)
        self.assertEqual(page.headers['cache-control'],'no-store')
        self.assertIn('autocomplete="current-password"',page.text);self.assertIn('role="status"',page.text)
        self.assertIn("script-src 'self'",page.headers['content-security-policy']);self.assertNotIn('unsafe-eval',page.headers['content-security-policy'])
    def test_e2e_admin_and_limited_role_with_temporary_database(self):
        self.assertEqual(self.login().status_code,204);self.assertEqual(self.client.get('/api/admin/auth/me').status_code,200)
        records=self.client.get('/api/admin/programs').json();record=payload(records[0]);record['name']+=' audit test'
        self.assertEqual(self.client.put('/api/admin/programs/'+record['id'],json=record,headers=self.csrf()).status_code,200)
        self.assertTrue(any(a['resource_id']==record['id'] for a in self.client.get('/api/admin/audit').json()))
        self.assertEqual(self.client.post('/api/admin/auth/logout',headers=self.csrf()).status_code,204)
        self.assertEqual(self.client.get('/api/admin/programs').status_code,401)
        self.create('readonly_user');self.assertEqual(self.login('readonly_user').status_code,204)
        self.assertEqual(self.client.put('/api/admin/programs/'+record['id'],json=record,headers=self.csrf()).status_code,403)
if __name__=='__main__':unittest.main()
