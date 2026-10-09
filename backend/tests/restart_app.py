"""Isolated restart fixture. Never deploy as the public application."""
import asyncio,os,tempfile,types
from pathlib import Path
from config import settings
from server import create_app
from app_services import build_services
from services.providers import GroqProvider,EdgeSpeechProvider,AcademicKnowledgeProvider
from services.llm_protocol import AssistantReply
from services.pricing_service import PricingService
from persistence.sqlite_repository import SQLiteRepository
from session_manager import SessionManager
root=Path(os.environ['LIA_RESTART_WORKSPACE']).resolve()
if not root.is_relative_to(Path(tempfile.gettempdir()).resolve()) or not root.name.startswith('lia-restart-'):
    raise ValueError('Requires isolated temporary workspace')
async def complete(*args,**kwargs):return AssistantReply(assistant_text='Información institucional.')
async def speech(text):return b'synthetic-audio'
async def knowledge(*args):return 'Información institucional estable'
async def stream(*args,**kwargs):
    async def chunks():
        yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content='Respuesta parcial. ',tool_calls=None))])
        await asyncio.sleep(60)
    return chunks()
services=build_services(settings,session=SessionManager(),pricing=PricingService(repository=SQLiteRepository(root/'commercial.sqlite3')),
    llm=GroqProvider(complete,stream),speech=EdgeSpeechProvider(speech),knowledge=AcademicKnowledgeProvider(knowledge),voucher_directory=root/'vouchers')
app=create_app(services=services,configuration=settings)
