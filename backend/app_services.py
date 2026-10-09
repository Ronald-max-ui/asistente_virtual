"""Explicit application composition. Business services never import this module."""
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from functools import partial
from importlib import import_module
import asyncio
from services.conversation_service import ConversationService
from services.operational_service import OperationalService
from services.voucher_submission import VoucherSubmissionService
from services.providers import GroqProvider, EdgeSpeechProvider, AcademicKnowledgeProvider, LLMProvider, SpeechProvider, KnowledgeProvider
from services.pricing_service import PricingService, PricingPolicy
from services.action_service import ActionService
from services.commercial_service import CommercialService
from services.avatar_service import AvatarService
from services.health_service import readiness
from session_manager import SessionManager

@dataclass
class AppServices:
    session: SessionManager
    pricing: PricingService
    actions: ActionService
    operational: OperationalService
    conversation: ConversationService
    commercial: CommercialService
    avatar: AvatarService
    vouchers: VoucherSubmissionService
    health: Any
    llm: LLMProvider
    speech: SpeechProvider
    knowledge: KnowledgeProvider
    provider_client: Any = None
    admin: Any = None
    voice: Any = None
    branding: Any = None

    async def warmup(self, timeout):
        warmup=getattr(self.knowledge,'warmup',None)
        if self.conversation.performance.knowledge_prewarm and warmup:
            await asyncio.wait_for(warmup(),timeout)

    async def close(self):
        if self.provider_client is not None:
            await asyncio.wait_for(self.provider_client.close(), 2)

    def use_session(self, session):
        """Explicit replacement for tests/embedders, before requests start."""
        self.session = session
        self.conversation.sessions = self.operational.sessions = self.vouchers.sessions = session

def build_services(settings, *, session=None, pricing=None, llm=None, speech=None, knowledge=None, voucher_directory=None):
    from commercial_runtime import get_repository
    pricing = pricing or PricingService(repository=get_repository())
    from services.voice_service import VoiceService
    voice=VoiceService(pricing.repository or get_repository())
    voice.initialize(getattr(settings,'tts_voice','es-PE-CamilaNeural'),getattr(settings,'tts_rate','+10%'))
    from services.branding_service import BrandingService
    from persistence.branding_repository import BrandingRepository
    branding=BrandingService(BrandingRepository(pricing.repository or get_repository()),(pricing.repository or get_repository()).path.parent/'branding')
    client = None
    if llm is None:
        llm_service = import_module('services.llm_service')
        client = llm_service.create_client(settings)
        llm = GroqProvider(partial(llm_service.generar_respuesta_llm, client=client, pricing=pricing, configuration=settings),
            partial(llm_service.stream_respuesta_llm, client=client, pricing=pricing, configuration=settings))
    if speech is None:
        from services.tts_service import generar_audio_bytes
        from services.providers import ConfiguredEdgeSpeechProvider
        speech = ConfiguredEdgeSpeechProvider(partial(generar_audio_bytes, configuration=settings),voice)
    if knowledge is None:
        rag_service = import_module('services.rag_service')
        from services.knowledge_index import KnowledgeIndex
        index = KnowledgeIndex(getattr(settings, 'knowledge_index', None))
        knowledge = AcademicKnowledgeProvider(partial(rag_service.buscar_contexto, client=client, index=index, configuration=settings),
            partial(asyncio.to_thread,index.search,'Información general del instituto'))
    session = session or SessionManager(ttl=settings.session_ttl_seconds,
        cleanup_interval=settings.session_cleanup_interval_seconds)
    commercial = CommercialService(pricing.repository or get_repository())
    from persistence.sqlite_admin_repository import SQLiteAdminRepository
    from services.admin_service import AdminService
    from security.admin_config import AdminSettings
    admin = AdminService(SQLiteAdminRepository(commercial.repository), getattr(settings,'admin',None) or AdminSettings.from_env())
    actions = ActionService(pricing)
    operational = OperationalService(session, pricing)
    conversation = ConversationService(session, llm, speech, knowledge, actions, PricingPolicy(pricing),
        getattr(settings, 'session_max_history_turns', 4),getattr(settings,'performance',None))
    directory = Path(voucher_directory or Path(__file__).resolve().parent/'storage/vouchers')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    vouchers = VoucherSubmissionService(session, operational, pricing.resolve, directory)
    return AppServices(session, pricing, actions, operational, conversation, commercial,
        AvatarService(commercial.repository), vouchers, readiness, llm, speech, knowledge, admin=admin, provider_client=client, voice=voice, branding=branding)
