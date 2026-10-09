"""Operational commercial E2E and real concurrent SQLite transactions."""
import unittest,json,uuid,sqlite3,csv,io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import datetime,timedelta,timezone
import test_phase9a as previous
from test_phase1_api import valid_png
from services.commercial_service import payload
from persistence.lead_operations_repository import LeadOperationsRepository,boundaries
from domain.errors import DomainError
from backup_runtime import backup_runtime
class OperationsTests(unittest.TestCase):
 setUp=previous.AdminTests.setUp
 create=previous.AdminTests.create
 login=previous.AdminTests.login
 csrf=previous.AdminTests.csrf
 def lead(self,name='Synthetic prospect',phone='999111222'):
  runtime=self.server.app.state.services.session.repository;sid=uuid.uuid4().hex;runtime.create_session(sid,'fixture_digest');lead=runtime.save_lead(sid,dict(name=name,whatsapp=phone,program='turismo',modality=None,origin='web',notes='original captured'),'capture');return lead['lead_id'],sid
 def profile(self,id):return self.client.get('/api/admin/operations/leads/'+id).json()
 def mutate(self,id,path,body,key=None,etag=None,method='POST'):
  h={**self.csrf(),'Idempotency-Key':key or uuid.uuid4().hex,'If-Match':etag or self.profile(id)['etag']}
  return self.client.request(method,'/api/admin/operations/leads/'+id+path,json=body,headers=h)
 def search(self,**filters):return self.client.post('/api/admin/operations/leads/search',json=filters,headers=self.csrf())
 def test_capture_tracking_tasks_voucher_review_convert_end_to_end(self):
  self.login();bootstrap=self.client.post('/api/session',json={}).json();sid=bootstrap['session_id'];capture=self.client.post('/api/leads',data={'nombre':'Synthetic prospect','whatsapp':'999111222','carrera':'Turismo','session_id':sid,'notas':'original captured'},headers={'X-Session-Token':bootstrap['session_token'],'Idempotency-Key':uuid.uuid4().hex});self.assertEqual(capture.status_code,200);id=capture.json()['lead_id'];original=self.profile(id);self.assertEqual(original['status'],'new');self.assertEqual(original['stage'],'lead_captured');self.assertNotIn('history',original)
  body=dict(status='contacted',assigned_to_user_id=self.user['id']);self.assertEqual(self.mutate(id,'',body,method='PUT').status_code,200)
  key=uuid.uuid4().hex;etag=self.profile(id)['etag'];note={'type':'note','text':'Synthetic note'}
  self.assertEqual(self.mutate(id,'/activities',note,key,etag).status_code,200);self.assertEqual(self.mutate(id,'/activities',note,key,etag).status_code,200)
  due=datetime.now(timezone.utc)+timedelta(hours=1);task={'due_at':due.isoformat(),'assigned_to':self.user['id'],'type':'follow_up','note':'Synthetic follow up'}
  key=uuid.uuid4().hex;etag=self.profile(id)['etag'];self.assertEqual(self.mutate(id,'/tasks',task,key,etag).status_code,200);self.assertEqual(self.mutate(id,'/tasks',task,key,etag).status_code,200)
  profile=self.profile(id);self.assertEqual(len(profile['tasks']),1);self.assertEqual(profile['next_follow_up_at'],due.timestamp());self.assertEqual(sum(a['type']=='note' for a in profile['activities']),1)
  taskid=profile['tasks'][0]['id'];self.assertEqual(self.mutate(id,'/tasks/'+taskid,{'status':'completed'}).status_code,200)
  runtime=self.server.app.state.services.session.repository;voucher=uuid.uuid4().hex;reference=voucher+'.png';directory=self.server.app.state.services.vouchers.directory;(__import__('pathlib').Path(directory)/reference).write_bytes(valid_png());tariff=self.server.app.state.services.pricing.resolve('turismo','inscripcion')
  runtime.save_voucher(sid,tariff,'synthetic_fingerprint','voucher',lambda:(voucher,reference),lambda _:None,id)
  price=next(p for p in self.commercial.list('prices') if p['program']=='turismo' and p['concept']=='inscripcion');price=payload(price);price['amount']='120';self.commercial.save('prices',price)
  self.assertEqual(self.profile(id)['vouchers'][0]['amount'],'80');self.assertEqual(self.client.post('/api/admin/vouchers/'+voucher+'/review',json={'status':'approved','review_note':'Synthetic'},headers=self.csrf()).status_code,200)
  self.assertEqual(self.profile(id)['status'],'contacted');self.assertEqual(self.mutate(id,'',{'status':'converted','assigned_to_user_id':self.user['id']},method='PUT').status_code,200)
  profile=self.profile(id);types={a['type'] for a in profile['activities']};self.assertTrue({'lead_created','assigned','status_changed','note','task_created','task_completed','voucher_received','voucher_approved','converted'}<=types)
  self.assertEqual(runtime.get_record('leads',id)['notes'],'original captured');self.assertEqual(self.mutate(id,'',{'status':'lost'},method='PUT').status_code,409)
  audits=self.client.get('/api/admin/audit').json();actions={a['action'] for a in audits};self.assertTrue({'leads.note','leads.task_created','leads.task_completed'}<=actions)
  tasks=[a for a in audits if a['resource_type']=='lead_tasks'];self.assertEqual(len(tasks),2);self.assertTrue(all('note' not in a['after'] for a in tasks));self.assertNotIn('Synthetic follow up',json.dumps(audits))
 def test_concurrent_admin_writers_only_one_commits(self):
  id,sid=self.lead();repo=LeadOperationsRepository(self.server.app.state.services.session.repository);old=repo.profile(id)['etag'];barrier=Barrier(2)
  def write(actor):
   barrier.wait()
   try:repo.mutate(id,'tracking',{'status':'contacted','assigned_to_user_id':None},actor,'concurrency',old,uuid.uuid4().hex);return True
   except DomainError as exc:self.assertEqual(exc.code,'lead_changed');return False
  with ThreadPoolExecutor(2) as pool:self.assertEqual(sum(pool.map(write,['admin_a','admin_b'])),1)
 def test_permissions_assignment_validation_no_price_privileges(self):
  admissions=self.create('admissions','admisiones');reader=self.create('reader','solo_lectura');id,_=self.lead();self.login('admissions')
  self.assertEqual(self.mutate(id,'',{'status':'interested','assigned_to_user_id':admissions['id']},method='PUT').status_code,200)
  self.assertEqual(self.mutate(id,'',{'status':'interested','assigned_to_user_id':reader['id']},method='PUT').status_code,422)
  self.assertEqual(self.client.get('/api/admin/users').status_code,403);self.assertEqual(self.client.put('/api/admin/settings',json={},headers=self.csrf()).status_code,403)
  self.assertEqual(self.client.post('/api/admin/operations/leads/export',json={},headers=self.csrf()).status_code,403)
  self.login('reader');self.assertEqual(self.profile(id)['status'],'interested');self.assertEqual(self.mutate(id,'/activities',{'text':'No'},method='POST').status_code,403)
 def test_search_duplicates_filters_and_privacy(self):
  self.login();id,_=self.lead('Synthetic A','+51 999111222');other,_=self.lead('Synthetic B','999111222');self.lead('Unrelated','999555777')
  self.assertEqual(len(self.search(search='999111222').json()),2);self.assertTrue(self.profile(id)['possible_duplicate']);self.assertTrue(self.profile(other)['possible_duplicate'])
  self.mutate(id,'',{'status':'contacted','assigned_to_user_id':self.user['id']},method='PUT');self.assertEqual(len(self.search(quick='mine').json()),1)
  self.assertEqual(len(self.search(status='new',limit=1).json()),1)
  self.assertEqual(self.mutate(id,'/activities',{'text':'<script>x</script>'}).status_code,422)
  logs=self.client.get('/api/admin/audit?resource_type=leads').text;self.assertNotIn('Synthetic A',logs);self.assertNotIn('999111222',logs)
 def test_idempotency_conflict_stale_etag_and_required_keys(self):
  self.login();id,_=self.lead();old=self.profile(id)['etag'];key=uuid.uuid4().hex
  self.assertEqual(self.mutate(id,'/activities',{'text':'First'},key,old).status_code,200)
  self.assertEqual(self.mutate(id,'/activities',{'text':'Second'},key,old).status_code,409)
  self.assertEqual(self.mutate(id,'',{'status':'contacted'},etag=old,method='PUT').status_code,409)
  self.assertEqual(self.client.post('/api/admin/operations/leads/'+id+'/activities',json={'text':'No key'},headers=self.csrf()).status_code,422)
 def test_loss_note_and_aware_dates(self):
  self.login();id,_=self.lead();self.assertEqual(self.mutate(id,'',{'status':'lost','loss_reason':'other'},method='PUT').status_code,422)
  self.assertEqual(self.mutate(id,'',{'status':'lost','loss_reason':'other','loss_note':'Synthetic reason'},method='PUT').status_code,200)
  self.assertEqual(self.mutate(id,'',{'status':'contacted'},method='PUT').status_code,200)
  self.assertEqual(self.mutate(id,'/tasks',{'due_at':'2026-10-10T10:00:00'}).status_code,422)
 def test_exact_dashboard_calendar_and_cohort_counts(self):
  self.login();runtime=self.server.app.state.services.session.repository;now=datetime(2026,10,9,17,tzinfo=timezone.utc).timestamp();runtime.clock=lambda:now;repo=LeadOperationsRepository(runtime);today,tomorrow,_=boundaries(now)
  a,_=self.lead();b,_=self.lead();c,_=self.lead()
  with runtime.transaction() as db:db.execute('UPDATE leads SET created_at=? WHERE lead_id=?',(today-40*86400,c))
  for id,due in [(a,today+3600),(b,tomorrow+3600)]:repo.mutate(id,'task_create',dict(due_at=due,assigned_to=None,type='follow_up',note=''),self.user['id'],'fixture',repo.profile(id)['etag'],uuid.uuid4().hex)
  repo.mutate(c,'tracking',{'status':'converted','assigned_to_user_id':None},self.user['id'],'fixture',repo.profile(c)['etag'],uuid.uuid4().hex)
  metrics=self.client.get('/api/admin/operations/analytics?period=7d').json();self.assertEqual(metrics['new_today'],2);self.assertEqual(metrics['new_7_days'],2);self.assertEqual(metrics['created_in_period'],2);self.assertEqual(metrics['conversions_in_period'],1);self.assertEqual(metrics['follow_ups_today'],1);self.assertEqual(metrics['overdue'],1)
  self.assertEqual(len(self.search(quick='tomorrow').json()),1)
 def test_csv_injection_filtered_no_notes_audited(self):
  self.login()
  for value in ['=SUM(1,2)','+cmd','@test','-1']:self.lead(value,uuid.uuid4().hex[:9])
  self.lead('Excluded','999888777');response=self.client.post('/api/admin/operations/leads/export',json={'status':'new'},headers=self.csrf());self.assertEqual(response.status_code,200)
  rows=list(csv.reader(io.StringIO(response.text.lstrip('\ufeff'))));self.assertTrue(all(r[1].startswith("'") for r in rows[1:] if r[1]!='Excluded'));self.assertNotIn('original captured',response.text)
  audit=self.client.get('/api/admin/audit?action=leads.export').json();self.assertEqual(len(audit),1);self.assertEqual(audit[0]['after'],None)
 def test_backup_and_migration_indexes_are_additive(self):
  self.login();id,_=self.lead();self.mutate(id,'/activities',{'text':'Backup note'});runtime=self.server.app.state.services.session.repository
  from persistence.sqlite_runtime_repository import SQLiteRuntimeRepository
  reopened=SQLiteRuntimeRepository(runtime.path);self.assertEqual(LeadOperationsRepository(reopened).profile(id)['activities'][0]['text'],'Backup note')
  target=backup_runtime(runtime,self.server.app.state.services.vouchers.directory,self.root/'runtime-backup')
  from verify_runtime_backup import verify
  self.assertTrue(verify(target)['passed'])
  from contextlib import closing
  with closing(sqlite3.connect(target/'runtime.sqlite3')) as db:
   self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],3);self.assertEqual(db.execute('SELECT count(*) FROM lead_activity').fetchone()[0],2)
   self.assertIn('tracking_status',str(db.execute('EXPLAIN QUERY PLAN SELECT lead_id FROM lead_tracking WHERE status=?',('new',)).fetchall()));self.assertIn('tasks_due',str(db.execute("EXPLAIN QUERY PLAN SELECT lead_id FROM lead_tasks WHERE status='pending' AND due_at<?",(100,)).fetchall()))

 def test_two_http_admins_stale_write_is_rejected(self):
  from fastapi.testclient import TestClient
  self.login();self.create('second_admin','admisiones');id,_=self.lead();old=self.profile(id)['etag']
  with TestClient(self.server.app) as other:
   self.login('second_admin',client=other);h={**self.csrf(other),'Idempotency-Key':uuid.uuid4().hex,'If-Match':old}
   self.assertEqual(other.put('/api/admin/operations/leads/'+id,json={'status':'interested'},headers=h).status_code,200)
  response=self.mutate(id,'',{'status':'contacted'},etag=old,method='PUT');self.assertEqual(response.status_code,409);self.assertEqual(response.json()['code'],'lead_changed');self.assertEqual(self.profile(id)['status'],'interested')

 def test_version_two_migration_preserves_capture_and_seeds_new(self):
  id,_=self.lead();runtime=self.server.app.state.services.session.repository
  with runtime.transaction() as db:
   db.execute('DROP TABLE lead_tasks');db.execute('DROP TABLE lead_activity');db.execute('DROP TABLE lead_tracking');db.execute('PRAGMA user_version=2')
  from persistence.sqlite_runtime_repository import SQLiteRuntimeRepository
  repo=SQLiteRuntimeRepository(runtime.path);profile=LeadOperationsRepository(repo).profile(id)
  self.assertEqual(profile['status'],'new');self.assertEqual(profile['name'],'Synthetic prospect');self.assertIsNone(profile['converted_at']);self.assertEqual(repo.get_record('leads',id)['notes'],'original captured')
  repo=SQLiteRuntimeRepository(runtime.path);self.assertEqual(len(LeadOperationsRepository(repo).profile(id)['activities']),1)
