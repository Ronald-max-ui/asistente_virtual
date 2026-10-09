"""Regresiones de persistencia comercial, API administrativa y fuente monetaria única."""
import json
import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from test_phase1_api import load_server
from migrate_commercial import migrate, seed_configuration, BASE
from persistence.sqlite_repository import SQLiteRepository
from services.commercial_service import CommercialService, payload
from services.avatar_service import AvatarService
from services.pricing_service import PricingService, CatalogError
from services.llm_protocol import AssistantReply
import services.pricing_service as pricing_module
import services.action_service as action_module

class CommercialTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repository = SQLiteRepository(Path(self.directory.name) / 'commercial.sqlite3')
        self.report = migrate(self.repository)
        seed_configuration(self.repository)
        self.service = CommercialService(self.repository)
        self.pricing = PricingService(repository=self.repository, today=lambda: date(2026, 10, 7))

    def price(self, identifier='offer', program='gastronomia', amount='0', status='free',
              modality=None, shift=None, concept='inscripcion', campaign_id='october'):
        return dict(id=identifier, program=program, concept=concept, modality=modality, shift=shift,
                    amount=amount, currency='PEN', status=status, campaign_id=campaign_id)

    def campaign(self, identifier='october', start='2026-10-01', end='2026-10-31', enabled=True):
        self.service.save('campaigns', dict(id=identifier, name=identifier, starts_on=start, ends_on=end, enabled=enabled))

    def test_migration_correct_and_idempotent_without_overwriting_admin(self):
        self.assertEqual((self.report['programs'], self.report['prices'], self.report['campaigns']), (6, 42, 0))
        self.assertEqual(self.report['rejected'], [])
        programs = self.service.list('programs')
        self.assertEqual(len(programs), 6)
        self.assertEqual(sum(p['kind'] == 'curso_corto' for p in programs), 2)
        self.assertTrue(all(p['academic_path'].endswith('.md') for p in programs))
        price = self.service.get('prices', 'gastronomia_000_inscripcion')
        self.service.save('prices', {**payload(price), 'amount': '91.50'})
        report = migrate(self.repository)
        self.assertEqual((report['programs'], len(report['skipped']), len(self.service.list('prices'))), (0, 6, 42))
        self.assertEqual(self.pricing.resolve('gastronomia', 'inscripcion')['amount'], '91.5')
        updated = self.service.get('prices', price['id'])
        self.assertEqual(updated['created_at'], price['created_at'])
        self.assertEqual(updated['created_by'], 'migration')
        self.assertEqual(updated['updated_by'], 'admin-token')

    def test_migration_rejects_invalid_program_atomically(self):
        root = Path(self.directory.name) / 'knowledge'
        target = root / '02_carreras' / 'gastronomia.pricing.json'
        target.parent.mkdir(parents=True)
        data = json.loads((BASE / 'knowledge/02_carreras/gastronomia.pricing.json').read_text(encoding='utf-8'))
        data['prices'][0].update(status='pending', amount='0')
        target.write_text(json.dumps(data), encoding='utf-8')
        repository = SQLiteRepository(Path(self.directory.name) / 'rejected.sqlite3')
        report = migrate(repository, root)
        self.assertEqual(len(report['rejected']), 1)
        self.assertIn('pending requiere', report['rejected'][0]['reason'])
        self.assertEqual(CommercialService(repository).list('programs'), [])

    def test_source_json_changes_are_not_runtime_and_no_rag_dependency(self):
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('JSON runtime prohibido')):
            self.assertEqual(self.pricing.resolve('turismo', 'inscripcion')['amount'], '80')
            self.assertIn('80 soles', self.pricing.authoritative_answer('Precio de inscripción de Turismo'))
        empty = PricingService(repository=SQLiteRepository(Path(self.directory.name) / 'empty.sqlite3'))
        with self.assertRaises(CatalogError):
            empty.resolve('turismo', 'inscripcion')

    def test_each_program_keeps_own_price_and_course_variants(self):
        price = self.service.get('prices', 'bartender_000_inscripcion')
        self.service.save('prices', {**payload(price), 'amount': '54'})
        self.assertEqual(self.pricing.resolve('bartender', 'inscripcion')['amount'], '54')
        self.assertEqual(self.pricing.resolve('gastronomia', 'inscripcion')['amount'], '80')
        with self.assertRaises(ValueError):
            self.pricing.resolve('bartender', 'inscripcion', 'virtual')

    def test_modality_and_shift_prices_are_independent_and_missing_variant_is_safe(self):
        self.service.save('programs', dict(id='especial', name='Especial', kind='curso_corto',
            modalities=['presencial', 'virtual'], shifts=['manana', 'noche']))
        for index, (mode, shift, amount) in enumerate([
            ('presencial', 'manana', '40'), ('presencial', 'noche', '50'),
            ('virtual', 'manana', '60'), ('virtual', 'noche', '70')]):
            self.service.save('prices', self.price('variant_' + str(index), 'especial', amount, 'active',
                                                 mode, shift, campaign_id=None))
            self.assertEqual(self.pricing.resolve('especial', 'inscripcion', mode, shift)['amount'], amount)
        ambiguous = self.pricing.resolve('especial', 'inscripcion')
        self.assertEqual((ambiguous['status'], ambiguous['reason'], ambiguous['amount']), ('pending', 'variant_required', None))

    def test_free_pending_and_inactive_are_distinct(self):
        price = self.service.get('prices', 'gastronomia_000_inscripcion')
        self.service.save('prices', {**payload(price), 'status': 'free', 'amount': '0'})
        self.assertEqual(self.pricing.resolve('gastronomia', 'inscripcion')['amount'], '0')
        self.service.save('prices', {**payload(price), 'status': 'pending', 'amount': None})
        self.assertIsNone(self.pricing.resolve('gastronomia', 'inscripcion')['amount'])
        self.service.save('prices', {**payload(price), 'status': 'inactive'})
        quote = self.pricing.resolve('gastronomia', 'inscripcion')
        self.assertEqual((quote['status'], quote['reason']), ('pending', 'no_current_price'))
        with self.assertRaises(ValueError):
            self.service.save('prices', {**payload(price), 'status': 'free', 'amount': None})

    def test_campaign_current_expired_future_and_inclusive_boundaries(self):
        self.campaign()
        self.service.save('prices', self.price())
        for day, status, amount in [(date(2026, 9, 30), 'active', '80'), (date(2026, 10, 1), 'free', '0'),
                                   (date(2026, 10, 31), 'free', '0'), (date(2026, 11, 1), 'active', '80')]:
            self.pricing.today = lambda day=day: day
            quote = self.pricing.resolve('gastronomia', 'inscripcion')
            self.assertEqual((quote['status'], quote['amount']), (status, amount))
        self.assertEqual(self.pricing.resolve('administracion', 'inscripcion')['amount'], '80')

    def test_disabled_campaign_and_program(self):
        self.campaign(enabled=False)
        self.service.save('prices', self.price())
        self.assertEqual(self.pricing.resolve('gastronomia', 'inscripcion')['amount'], '80')
        program = self.service.get('programs', 'gastronomia')
        self.service.save('programs', {**payload(program), 'enabled': False})
        with self.assertRaises(ValueError):
            self.pricing.resolve('gastronomia', 'inscripcion')

    def test_campaign_scopes_and_incomplete_variant_do_not_leak_discount(self):
        self.campaign()
        self.service.save('prices', self.price('scoped', 'administracion', modality='virtual', shift='noche'))
        self.assertEqual(self.pricing.resolve('administracion', 'inscripcion', 'virtual', 'noche')['status'], 'free')
        self.assertEqual(self.pricing.resolve('administracion', 'inscripcion', 'presencial', 'noche')['amount'], '80')
        self.assertEqual(self.pricing.resolve('administracion', 'inscripcion', 'virtual', 'manana')['amount'], '80')
        self.assertEqual(self.pricing.resolve('administracion', 'inscripcion')['reason'], 'variant_required')

    def test_concurrent_overlapping_writes_cannot_both_commit(self):
        self.campaign()
        self.campaign('second')
        def save(identifier, campaign_id):
            try:
                self.service.save('prices', self.price(identifier, campaign_id=campaign_id))
                return 'saved'
            except ValueError as exc:
                self.assertIn('superpuestas', str(exc))
                return 'rejected'
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(save, 'first_offer', 'october'), executor.submit(save, 'second_offer', 'second')]
            self.assertCountEqual([f.result() for f in futures], ['saved', 'rejected'])
        self.assertEqual(len([p for p in self.service.list('prices') if p['campaign_id']]), 1)

    def test_overlap_is_rejected_on_price_campaign_edit_and_reactivation(self):
        self.campaign()
        self.service.save('prices', self.price())
        self.campaign('second', '2026-10-15', '2026-11-05')
        with self.assertRaisesRegex(ValueError, 'superpuestas'):
            self.service.save('prices', self.price('second_offer', campaign_id='second'))
        self.assertIsNone(self.service.get('prices', 'second_offer'))
        self.campaign('second', '2026-11-01', '2026-11-05')
        self.service.save('prices', self.price('second_offer', campaign_id='second'))
        with self.assertRaisesRegex(ValueError, 'superpuestas'):
            self.campaign('second', '2026-10-31', '2026-11-05')
        self.assertEqual(self.service.get('campaigns', 'second')['starts_on'], '2026-11-01')
        self.campaign('third', '2026-10-01', '2026-10-31', enabled=False)
        self.service.save('prices', self.price('third_offer', campaign_id='third'))
        with self.assertRaisesRegex(ValueError, 'superpuestas'):
            self.campaign('third')

    def test_base_overlap_invalid_variant_alias_and_orphan_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'superpuestas'):
            self.service.save('prices', self.price('duplicate', amount='20', status='active', campaign_id=None))
        with self.assertRaises(ValueError):
            self.service.save('prices', self.price('orphan', program='unknown', campaign_id=None))
        program = self.service.get('programs', 'administracion')
        self.service.save('prices', self.price('specific', 'administracion', '25', 'active', 'virtual',
                                             concept='matricula', campaign_id=None, shift='noche') | {'status': 'inactive'})
        with self.assertRaises(ValueError):
            self.service.save('programs', {**payload(program), 'modalities': ['presencial']})
        self.assertEqual(self.service.get('programs', 'administracion')['modalities'], program['modalities'])
        with self.assertRaises(ValueError):
            self.service.save('programs', {**payload(program), 'aliases': ['gastronomia']})

    def test_promotions_are_persisted_metadata_without_derived_amount(self):
        price = self.service.get('prices', 'gastronomia_000_inscripcion')
        self.service.save('prices', {**payload(price), 'promotions': [dict(id='promo', description='Beneficio',
            kind='percent', value='25', conditions='Sujeto a evaluación')]})
        quote = self.pricing.resolve('gastronomia', 'inscripcion')
        self.assertEqual(quote['amount'], '80')
        self.assertEqual(quote['promotions'][0]['value'], '25')

    def test_public_config_and_single_active_avatar_after_both_selection_paths(self):
        self.service.save('avatars', dict(id='second', name='Segundo', url='/static/avatars/second.vrm'))
        self.service.activate_avatar('second')
        self.assertEqual(sum(a['active'] for a in self.service.list('avatars')), 1)
        self.assertEqual(self.service.settings()['active_avatar_id'], 'second')
        self.service.save_settings({**self.service.settings(), 'assistant_name': 'Lía',
            'active_avatar_id': 'lia_original', 'voice': {'voice_id': 'es-PE-CamilaNeural'}, 'extensions': {'note': 'private'}})
        config = AvatarService(self.repository).public_config()
        self.assertEqual(config['avatar']['id'], 'lia_original')
        self.assertNotIn('secret', json.dumps(config))
        self.assertNotIn('private', json.dumps(config))
        self.assertNotIn('created_at', config['avatar'])
        self.assertEqual(sum(a['active'] for a in self.service.list('avatars')), 1)
        with self.assertRaises(ValueError):
            self.service.save_settings({**self.service.settings(), 'active_avatar_id': 'missing'})
        with self.assertRaises(ValueError):
            self.service.save_settings({**self.service.settings(), 'active_avatar_id': None})
        original = self.service.get('avatars', 'lia_original')
        with self.assertRaises(ValueError):
            self.service.save('avatars', {**payload(original), 'active': False, 'enabled': False})
        self.assertEqual(AvatarService(self.repository).public_config()['avatar']['id'], 'lia_original')
        with self.assertRaises(ValueError):
            self.service.save('avatars', dict(id='evil', name='Bad', url='javascript:alert(1)', active=True))

    def test_admin_separation_auth_validation_and_config_endpoint(self):
        server = load_server()
        server.app.state.commercial_service = self.service
        server.app.state.admin_api_token = ''
        with TestClient(server.app) as client:
            self.assertEqual(client.get('/api/admin/programs').status_code, 503)
            self.assertEqual(client.get('/api/config').json()['avatar']['id'], 'lia_original')
            server.app.state.admin_api_token = 'test-token'
            self.assertEqual(client.get('/api/admin/programs').status_code, 401)
            self.assertEqual(client.get('/api/admin/programs', headers={'Authorization': 'Bearer bad'}).status_code, 401)
            headers = {'Authorization': 'Bearer test-token'}
            self.assertEqual(len(client.get('/api/admin/programs', headers=headers).json()), 6)
            self.assertEqual(client.post('/api/admin/programs', headers=headers, json={'id': 'x', 'extra': 1}).status_code, 422)
            avatar = dict(id='second', name='Segundo', url='/static/avatars/second.vrm')
            self.assertEqual(client.post('/api/admin/avatars', headers=headers, json=avatar).status_code, 201)
            self.assertEqual(client.post('/api/admin/avatars/second/activate', headers=headers).status_code, 200)
            self.assertEqual(client.get('/api/config').json()['avatar']['id'], 'second')
            self.assertEqual(client.post('/api/admin/avatars', headers=headers, json=avatar).status_code, 409)
            price = payload(self.service.get('prices', 'gastronomia_000_inscripcion'))
            self.assertEqual(client.put('/api/admin/prices/' + price['id'], headers=headers, json={**price, 'amount': '86'}).status_code, 200)
            self.assertEqual(self.pricing.resolve('gastronomia', 'inscripcion')['amount'], '86')
            self.assertEqual(client.post('/api/admin/prices', headers=headers,
                json=self.price('dupe', amount='85', status='active', campaign_id=None)).status_code, 409)
            self.assertEqual(client.get('/api/admin/settings', headers=headers).status_code, 200)
            self.assertEqual(client.get('/api/admin/campaigns', headers=headers).status_code, 200)

    def test_db_updates_apply_to_chat_and_stream_with_identical_policy(self):
        server = load_server(pricing=self.pricing)
        server.app.state.commercial_service = self.service
        request = dict(type='show_payment', program='gastronomia', concept='inscripcion')
        reply = AssistantReply(assistant_text='La inscripción cuesta S/ 999.', structured_actions=[request], native_actions_present=True)
        async def fake_stream(*args, **kwargs):
            async def chunks():
                yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(
                    content='La inscripción cuesta S/ 999.', tool_calls=[types.SimpleNamespace(index=0,
                    function=types.SimpleNamespace(name='show_payment', arguments=json.dumps({'program': 'gastronomia', 'concept': 'inscripcion'})))]))])
            return chunks()
        price = payload(self.service.get('prices', 'gastronomia_000_inscripcion'))
        with patch.object(pricing_module, 'pricing_service', self.pricing), patch.object(action_module, 'pricing_service', self.pricing), \
             patch.object(server, 'generar_respuesta_llm', AsyncMock(return_value=reply)), \
             patch.object(server, 'stream_respuesta_llm', fake_stream), \
             patch.object(server, 'generar_audio_bytes', AsyncMock(return_value=b'audio')), TestClient(server.app) as client:
            for amount in ['80', '95.50']:
                self.service.save('prices', {**price, 'amount': amount})
                for endpoint in ['/chat', '/chat/stream']:
                    response = client.post(endpoint, json={'mensaje': 'Quiero pagar la inscripción de Gastronomía',
                        'mode': 'web', 'persona': 'sales', 'session_id': endpoint + amount})
                    self.assertEqual(response.status_code, 200)
                    if endpoint == '/chat':
                        actions = response.json()['actions']
                        self.assertNotIn('999', response.json()['texto'])
                    else:
                        events = [json.loads(l[6:]) for l in response.text.splitlines() if l.startswith('data: ')]
                        actions = [e['action'] for e in events if e['type'] == 'ui_action']
                        types_ = [e['type'] for e in events]
                        self.assertLess(types_.index('text'), types_.index('audio'))
                        self.assertLess(types_.index('audio'), types_.index('ui_action'))
                        self.assertEqual(types_[-1], 'done')
                    self.assertEqual(actions[0]['amount'], amount.rstrip('0').rstrip('.') if '.' in amount else amount)
            for status, amount in [('free', '0'), ('pending', None)]:
                self.service.save('prices', {**price, 'status': status, 'amount': amount})
                for endpoint in ['/chat', '/chat/stream']:
                    response = client.post(endpoint, json={'mensaje': 'Quiero pagar la inscripción de Gastronomía',
                        'mode': 'web', 'persona': 'sales', 'session_id': endpoint + status})
                    actions = response.json()['actions'] if endpoint == '/chat' else [
                        json.loads(l[6:]) for l in response.text.splitlines() if l.startswith('data: ') and json.loads(l[6:])['type'] == 'ui_action']
                    self.assertEqual(actions, [])
                response = client.post('/api/vouchers', data={'carrera': 'gastronomia',
                    'concepto': 'inscripcion', 'monto': '0' if status == 'free' else '80'},
                    files={'imagen': ('test.png', b'test', 'image/png')})
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()['code'], 'price_free' if status == 'free' else 'tariff_pending')

if __name__ == '__main__':
    unittest.main()
