"""Panel API regressions: temporary SQL, concurrency, scoped files and dynamic public prices."""
import unittest,json,uuid,types,asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import AsyncMock
import test_phase9a as previous
ORIGIN=previous.ORIGIN
from test_phase1_api import valid_png
from services.commercial_service import payload
from domain.revision import revision
from domain.errors import DomainError
from services.llm_protocol import AssistantReply
class PanelTests(unittest.TestCase):
    setUp=previous.AdminTests.setUp
    create=previous.AdminTests.create
    login=previous.AdminTests.login
    csrf=previous.AdminTests.csrf
    def test_dashboard_permission_minimization(self):
        self.create('voucher_reviewer','revisor_pagos');self.login('voucher_reviewer')
        result=self.client.get('/api/admin/panel/dashboard').json()
        self.assertIn('pending_vouchers',result);self.assertNotIn('recent_leads',result);self.assertNotIn('active_programs',result)
        context=self.client.get('/api/admin/panel/context').json();self.assertNotIn('prices',context);self.assertNotIn('programs',context)
        self.assertEqual(self.client.get('/api/admin/leads').status_code,403)
    def test_record_etag_conflict_atomic(self):
        self.login();record=self.commercial.list('programs')[0];url='/api/admin/programs/'+record['id'];etag=self.client.get(url).headers['etag']
        first=payload(record);first['name']+=' valid'
        response=self.client.put(url,json=first,headers={**self.csrf(),'If-Match':etag});self.assertEqual(response.status_code,200)
        first['name']+=' stale';response=self.client.put(url,json=first,headers={**self.csrf(),'If-Match':etag})
        self.assertEqual(response.status_code,409);self.assertEqual(response.json()['code'],'admin_record_changed')
        self.assertFalse(self.commercial.get('programs',record['id'])['name'].endswith('stale'))
    def test_two_repository_writers_only_one_revision_commits(self):
        old=self.commercial.list('programs')[0];expected=revision(old);barrier=Barrier(2)
        def write(n):
            data=payload(old);data['name']+=' '+str(n);barrier.wait()
            try:self.commercial.save('programs',data,self.user['id'],expected=expected);return True
            except DomainError:return False
        with ThreadPoolExecutor(2) as pool:self.assertEqual(sum(pool.map(write,[1,2])),1)
    def test_settings_and_users_reject_stale_revision(self):
        self.login();h=self.csrf();response=self.client.get('/api/admin/settings');settings=response.json();etag=response.headers['etag'];settings['assistant_name']='Lia test'
        self.assertEqual(self.client.put('/api/admin/settings',json=settings,headers={**h,'If-Match':etag}).status_code,200)
        self.assertEqual(self.client.put('/api/admin/settings',json=settings,headers={**h,'If-Match':etag}).status_code,409)
        url='/api/admin/users/'+self.user['id'];etag=self.client.get(url).headers['etag'];body=dict(display_name='New',role='superadmin',enabled=True)
        self.assertEqual(self.client.put(url,json=body,headers={**h,'If-Match':etag}).status_code,200)
        self.assertEqual(self.client.put(url,json=body,headers={**h,'If-Match':etag}).status_code,409)
    def offer(self,identifier='synthetic_campaign'):
        today=self.server.app.state.services.pricing.today().isoformat()
        campaign=dict(id=identifier,name='Synthetic campaign',starts_on=today,ends_on=today,enabled=True,notes='')
        price=payload(next(p for p in self.commercial.list('prices') if p['program']=='turismo' and p['concept']=='inscripcion'))
        price.update(id=identifier+'_offer',campaign_id=identifier,campaign='Synthetic campaign',status='free',amount='0',starts_on=None,ends_on=None)
        return dict(campaign=campaign,price=price,create=True)
    def test_campaign_offer_atomic_conflict_no_orphan(self):
        self.login();h=self.csrf();body=self.offer()
        response=self.client.post('/api/admin/panel/campaign-offer',json=body,headers=h);self.assertEqual(response.status_code,200)
        self.assertEqual(self.server.app.state.services.pricing.resolve('turismo','inscripcion')['status'],'free')
        other=self.offer('conflicting_campaign');response=self.client.post('/api/admin/panel/campaign-offer',json=other,headers=h)
        self.assertEqual(response.status_code,409);self.assertIsNone(self.commercial.get('campaigns',other['campaign']['id']));self.assertIsNone(self.commercial.get('prices',other['price']['id']))
        audits=self.client.get('/api/admin/audit?resource_type=campaigns').json();self.assertTrue(any(a['resource_id']==body['campaign']['id'] for a in audits))
    def test_backend_campaign_phase_and_base_quote(self):
        self.login();self.client.post('/api/admin/panel/campaign-offer',json=self.offer(),headers=self.csrf())
        context=self.client.get('/api/admin/panel/context').json();self.assertEqual(context['timezone'],'America/Lima');self.assertEqual(context['campaigns'][0]['phase'],'current')
        base=self.client.get('/api/admin/panel/base-price?program=turismo&concept=inscripcion').json();self.assertEqual(base['amount'],'80');self.assertEqual(base['status'],'active')
    def voucher(self,reference=None):
        runtime=self.server.app.state.services.session.repository;identifier=uuid.uuid4().hex;reference=reference or identifier+'.png'
        directory=Path(self.server._VOUCHERS_DIR);(directory/reference).write_bytes(valid_png())
        tariff=dict(program='turismo',modality=None,shift=None,concept='inscripcion',amount='80',currency='PEN',campaign='base')
        return runtime.save_voucher(None,tariff,identifier,None,lambda:(identifier,reference),lambda _:None)['voucher_id']
    def test_voucher_file_private_permission_headers(self):
        identifier=self.voucher();url='/api/admin/panel/vouchers/'+identifier+'/file';self.assertEqual(self.client.get(url).status_code,401)
        self.login();response=self.client.get(url);self.assertEqual(response.status_code,200);self.assertEqual(response.content,valid_png())
        self.assertEqual(response.headers['content-type'],'image/png');self.assertEqual(response.headers['cache-control'],'no-store');self.assertIn('inline',response.headers['content-disposition']);self.assertNotIn(str(self.root),response.text)
        self.assertEqual(self.client.get('/api/admin/panel/vouchers/not_found/file').status_code,404)
        self.assertEqual(self.client.get(url+'?path=../../secret').content,valid_png())
    def test_voucher_unapproved_reference_rejected_and_pagination_status(self):
        identifier=self.voucher('unapproved.png');self.login();self.assertEqual(self.client.get('/api/admin/panel/vouchers/'+identifier+'/file').status_code,404)
        other=self.voucher();self.client.post('/api/admin/vouchers/'+other+'/review',json={'status':'approved'},headers=self.csrf())
        rows=self.client.get('/api/admin/vouchers?status=pending_review&limit=1').json();self.assertEqual(len(rows),1);self.assertEqual(rows[0]['status'],'pending_review');self.assertNotIn('file_reference',rows[0])
    def test_filtered_audit_no_private_data(self):
        self.login();record=payload(self.commercial.list('prices')[0]);self.commercial.save('prices',record,self.user['id'])
        rows=self.client.get('/api/admin/audit?resource_type=prices&resource_id='+record['id']+'&limit=1').json()
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['resource_id'],record['id']);self.assertNotIn('password_hash',json.dumps(rows))
        self.assertEqual(self.client.get('/api/admin/audit?since=invalid').status_code,422)
    def test_public_chat_observes_panel_price_and_campaign_without_rebuild(self):
        self.login();record=next(p for p in self.commercial.list('prices') if p['program']=='turismo' and p['concept']=='inscripcion');body=payload(record);body['amount']='120.50'
        self.assertEqual(self.client.put('/api/admin/prices/'+record['id'],json=body,headers=self.csrf()).status_code,200)
        self.server.generar_respuesta_llm=AsyncMock(return_value=AssistantReply(assistant_text='Información de Turismo.',native_actions_present=True))
        self.server.generar_audio_bytes=AsyncMock(return_value=b'fixture')
        bootstrap=self.client.post('/api/session',json={}).json();headers={'X-Session-Token':bootstrap['session_token']}
        result=self.client.post('/chat',json=dict(mensaje='¿Cuánto cuesta la inscripción de Turismo?',session_id=bootstrap['session_id'],mode='web',persona='sales'),headers=headers)
        self.assertEqual(result.status_code,200);self.assertIn('120.5',result.json()['texto'])
        self.client.post('/api/admin/panel/campaign-offer',json=self.offer(),headers=self.csrf())
        result=self.client.post('/chat',json=dict(mensaje='¿Cuánto cuesta la inscripción de Turismo?',session_id=bootstrap['session_id'],mode='kiosk',persona='info'),headers=headers)
        self.assertEqual(result.status_code,200);self.assertIn('gratuit',result.json()['texto'].lower());self.assertFalse(result.json()['actions'])

    def test_avatar_selection_rejects_stale_configuration(self):
        self.login();context=self.client.get('/api/admin/panel/context').json()
        expected=context['avatar_revision'];settings=self.commercial.settings();settings['assistant_name']='Changed elsewhere';self.commercial.save_settings(settings)
        result=self.client.post('/api/admin/avatars/lia_original/activate',headers={**self.csrf(),'If-Match':expected})
        self.assertEqual(result.status_code,409);self.assertEqual(result.json()['code'],'admin_record_changed')
    def test_campaign_edit_checks_both_revisions(self):
        self.login();body=self.offer();created=self.client.post('/api/admin/panel/campaign-offer',json=body,headers=self.csrf()).json()
        body.update(create=False,campaign_revision=revision(created['campaign']),price_revision=revision(created['price']))
        body['price']['status']='active';body['price']['amount']='60'
        first=self.client.post('/api/admin/panel/campaign-offer',json=body,headers=self.csrf());self.assertEqual(first.status_code,200)
        self.assertEqual(self.client.post('/api/admin/panel/campaign-offer',json=body,headers=self.csrf()).status_code,409)
        self.assertEqual(self.server.app.state.services.pricing.resolve('turismo','inscripcion')['amount'],'60')

    def test_existing_campaign_without_offer_can_receive_atomic_offer(self):
        self.login();body=self.offer();existing=self.commercial.save('campaigns',body['campaign'])
        body.update(create=False,campaign_revision=revision(existing),price_revision=None)
        result=self.client.post('/api/admin/panel/campaign-offer',json=body,headers=self.csrf())
        self.assertEqual(result.status_code,200);self.assertEqual(self.server.app.state.services.pricing.resolve('turismo','inscripcion')['status'],'free')
