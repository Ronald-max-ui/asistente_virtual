"""Synthetic browser fixture; no real databases or administrative users."""
import os
from services.admin_service import AdminService
from persistence.sqlite_admin_repository import SQLiteAdminRepository
from domain.admin import CreateUser
from security.admin_config import AdminSettings
from e2e_app import app,repository
service=AdminService(SQLiteAdminRepository(repository),AdminSettings(legacy_enabled=False))
app.state.admin_service=service
password=os.environ.get('E2E_ADMIN_PASSWORD','')
if not password: raise RuntimeError('Synthetic password not provisioned')
for username,role in [('synthetic_admin','superadmin'),('synthetic_reader','solo_lectura')]:
    service.create(CreateUser(username=username,display_name='Synthetic browser fixture',password=password,role=role),'e2e-bootstrap','e2e',first=username=='synthetic_admin')

# One synthetically associated lead/voucher for the administrative review UI.
import uuid
from pathlib import Path
from test_phase1_api import valid_png
runtime=app.state.services.session.repository
sid='admin_browser_fixture'
runtime.create_session(sid,'synthetic_digest')
lead=runtime.save_lead(sid,dict(name='Synthetic prospect',whatsapp='999111222',program='turismo',modality=None,origin='web',notes=''),'fixture_lead')
identifier=uuid.uuid4().hex
reference=identifier+'.png'
Path(app.state.services.vouchers.directory,reference).write_bytes(valid_png())
tariff=app.state.services.pricing.resolve('turismo','inscripcion')
runtime.save_voucher(sid,tariff,'synthetic_file_fingerprint','fixture_voucher',lambda:(identifier,reference),lambda _:None,lead['lead_id'])
