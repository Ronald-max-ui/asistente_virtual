"""Pruebas HTTP con RAG/LLM/TTS simulados: sin red ni ingestión, con almacenamiento temporal."""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, mock_open, patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.pricing_service import sanear_tarifas_texto
from test_support import commercial_service
from services.operational_service import OperationalService
from services.voucher_service import read_validated_image


class ServerFixture:
    """Compatibility only for historical test names; production uses AppServices."""
    def __init__(self, app):
        self.app = app
        for name in ('generar_respuesta_llm','stream_respuesta_llm','generar_audio_bytes','buscar_contexto','consultar_tarifa'):
            self.__dict__[name] = getattr(self, name)
    @property
    def session_manager(self): return self.app.state.services.session
    @session_manager.setter
    def session_manager(self, value): self.app.state.services.use_session(value)
    @property
    def _VOUCHERS_DIR(self): return self.app.state.services.vouchers.directory
    @_VOUCHERS_DIR.setter
    def _VOUCHERS_DIR(self, value): self.app.state.services.vouchers.directory = value
    @property
    def generar_respuesta_llm(self): return self.app.state.services.llm.complete_call
    @generar_respuesta_llm.setter
    def generar_respuesta_llm(self, value):
        self.app.state.services.llm.complete_call = value
        self.__dict__["generar_respuesta_llm"] = value
    @property
    def stream_respuesta_llm(self): return self.app.state.services.llm.stream_call
    @stream_respuesta_llm.setter
    def stream_respuesta_llm(self, value):
        self.app.state.services.llm.stream_call = value
        self.__dict__["stream_respuesta_llm"] = value
    @property
    def generar_audio_bytes(self): return self.app.state.services.speech.audio_call
    @generar_audio_bytes.setter
    def generar_audio_bytes(self, value):
        self.app.state.services.speech.audio_call = value
        self.__dict__["generar_audio_bytes"] = value
    @property
    def buscar_contexto(self): return self.app.state.services.knowledge.search_call
    @buscar_contexto.setter
    def buscar_contexto(self, value):
        self.app.state.services.knowledge.search_call = value
        self.__dict__["buscar_contexto"] = value
    @property
    def consultar_tarifa(self): return self.app.state.services.vouchers.resolve_price
    @consultar_tarifa.setter
    def consultar_tarifa(self, value):
        self.app.state.services.vouchers.resolve_price = value
        self.__dict__["consultar_tarifa"] = value
    async def responder_streaming(self, data, request):
        from api.chat import responder_streaming
        # Direct-call cancellation regressions supply a minimal HTTP request.
        if hasattr(request, 'scope'): request.scope['app'] = self.app
        else: request.app = self.app
        return await responder_streaming(data, request)


def load_server(security_settings=None, *, real_session_auth=False, pricing=None):
    from dataclasses import replace
    from security.config import SecuritySettings, RatePolicy
    if security_settings is None:
        security_settings = replace(SecuritySettings(), policies={key: RatePolicy(10000) for key in SecuritySettings().policies})
    import tempfile
    import atexit
    directory = tempfile.TemporaryDirectory()
    atexit.register(directory.cleanup)
    config = types.ModuleType("config")
    config.settings = types.SimpleNamespace(session_ttl_seconds=90, session_cleanup_interval_seconds=60,
                                           cors_origins=["http://localhost:5173"])
    rag = types.ModuleType("services.rag_service")
    rag.buscar_contexto = AsyncMock(return_value="Contexto de prueba")
    rag.detectar_entidad = lambda query, history: None
    llm = types.ModuleType("services.llm_service")
    llm.filtrar_texto = sanear_tarifas_texto
    llm.construir_prompt_sistema = lambda **kwargs: ""
    llm.generar_respuesta_llm = AsyncMock()
    llm.stream_respuesta_llm = AsyncMock()
    from services.pricing_service import pricing_service
    from app_services import build_services
    selected_pricing = pricing or pricing_service
    spec = importlib.util.spec_from_file_location("phase1_server", ROOT / "server.py")
    server = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"config": config, "services.rag_service": rag, "services.llm_service": llm}), patch("os.makedirs"), patch("security.config.SecuritySettings.from_env", return_value=security_settings), patch.dict("os.environ", {"RUNTIME_DATABASE_PATH":str(Path(directory.name)/"runtime.sqlite3")}):
        from services.providers import GroqProvider, EdgeSpeechProvider, AcademicKnowledgeProvider
        from services.tts_service import generar_audio_bytes
        with patch('app_services.build_services', side_effect=lambda configuration: build_services(configuration, pricing=selected_pricing,
            llm=GroqProvider(llm.generar_respuesta_llm, llm.stream_respuesta_llm), speech=EdgeSpeechProvider(generar_audio_bytes),
            knowledge=AcademicKnowledgeProvider(rag.buscar_contexto))):
            spec.loader.exec_module(server)
    # Real temporary runtime DB for all historical route tests. Authentication is
    # provisioned only in this fixture; production always requires an opaque token.
    from session_manager import SessionManager, token_digest
    from persistence.sqlite_runtime_repository import SQLiteRuntimeRepository
    repository = SQLiteRuntimeRepository(Path(directory.name) / 'runtime.sqlite3')
    class FixtureSessions(SessionManager):
        async def authorize(self, sid, token):
            if real_session_auth:
                return await super().authorize(sid, token)
            try:
                return await self.call('authorize', sid, token_digest('fixture-token'))
            except Exception:
                await self.call('create_session', sid, token_digest('fixture-token'))
                return await self.call('authorize', sid, token_digest('fixture-token'))
    server = ServerFixture(server.app)
    server.session_manager = FixtureSessions(repository=repository)
    server._VOUCHERS_DIR = str(Path(directory.name) / 'vouchers')
    Path(server._VOUCHERS_DIR).mkdir()
    server.app.state.commercial_service = commercial_service
    from services.admin_service import AdminService
    from persistence.sqlite_admin_repository import SQLiteAdminRepository
    server.app.state.admin_service = AdminService(SQLiteAdminRepository(commercial_service.repository))
    import logging
    logging.getLogger('lia.security').setLevel(logging.WARNING)
    return server


def valid_png():
    import io
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', (4, 4), 'white').save(buffer, format='PNG')
    return buffer.getvalue()


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = load_server()

    def stream(self, question, output, *, mode="web", persona="sales", parts=None):
        captured = {}

        async def chunks():
            for part in parts or [output]:
                yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=part))])

        async def fake_stream(*args, **kwargs):
            captured.update(kwargs)
            return chunks()

        with patch.object(self.server, "stream_respuesta_llm", fake_stream), \
             patch.object(self.server, "generar_audio_bytes", AsyncMock(return_value=b"audio-test")), \
             TestClient(self.server.app) as client:
            response = client.post("/chat/stream", json={"mensaje": question, "mode": mode, "persona": persona,
                                                       "session_id": self.id() + mode + persona})
        self.assertEqual(response.status_code, 200)
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        self.assertEqual(events[-1]["type"], "done")
        return events, captured

    def test_fragmented_action_preserves_text_audio_and_all_combinations(self):
        for mode in ["web", "kiosk"]:
            for persona in ["info", "sales"]:
                events, captured = self.stream("Muéstrame fotos", "", mode=mode, persona=persona,
                    parts=["[[ACT", "ION:SHOW_GALLERY:gastronomia_talleres]]", " Aquí tienes una foto. ", "¿Qué opinas?"])
                self.assertEqual(captured["persona"], persona)
                actions = [e for e in events if e["type"] == "ui_action"]
                self.assertEqual(len(actions), 1)
                self.assertEqual(actions[0]["action"]["resource_id"], "gastronomia_talleres")
                self.assertTrue(any(e["type"] == "audio" for e in events))
                for event in events:
                    if event["type"] in ("text", "done"):
                        self.assertNotIn("[[ACTION", event.get("text", event.get("full_text", "")))

    def test_model_does_not_authorize_itself_or_override_negation(self):
        for query in ["Hola", "No quiero pagar", "¿Cuánto cuesta?"]:
            events, _ = self.stream(query, "[[ACTION:SHOW_PAYMENT:Gastronomia:999]] Aquí tienes el QR.")
            self.assertFalse(any(e["type"] == "ui_action" for e in events))
        events, _ = self.stream("Hola", "[[ACTION:OPEN_LEAD_FORM:Gastronomia]] Te abro el formulario.")
        self.assertFalse(any(e["type"] == "ui_action" for e in events))

    def test_confirmed_inscription_and_pending_tuition(self):
        events, _ = self.stream("Quiero pagar la inscripción de Turismo", "[[ACTION:SHOW_PAYMENT:Turismo:999]]")
        action = next(e["action"] for e in events if e["type"] == "ui_action")
        self.assertEqual(action["amount"], "80")
        self.assertEqual(action["concept"], "inscripcion")
        self.assertTrue(action["qr_url"].startswith("/static/media/"))
        events, _ = self.stream("Quiero pagar la matrícula de Turismo", "[[ACTION:SHOW_PAYMENT:Turismo:999]]")
        self.assertFalse(any(e["type"] == "ui_action" for e in events))
        self.assertTrue(any(e.get("code") == "tariff_pending" for e in events))
        self.assertIn("pendiente", events[-1]["full_text"])

    def test_commercial_actions_stay_disabled_in_kiosk(self):
        events, _ = self.stream("Quiero pagar", "[[ACTION:SHOW_PAYMENT:Gastronomia:250]]", mode="kiosk")
        self.assertFalse(any(e["type"] == "ui_action" for e in events))
        events, _ = self.stream("Quiero dejar mis datos", "[[ACTION:OPEN_LEAD_FORM:Gastronomia]]", mode="kiosk")
        self.assertFalse(any(e["type"] == "ui_action" for e in events))

    def test_untrusted_resource_cannot_be_emitted(self):
        events, _ = self.stream("Muéstrame fotos", "[[ACTION:SHOW_GALLERY:../../secret]] Aquí tienes una imagen.")
        self.assertFalse(any(e["type"] == "ui_action" for e in events))

    def test_voucher_amount_must_match_authorized_catalog(self):
        with TestClient(self.server.app) as client:
            for concepto, monto, expected in [("matricula", "250", 409), ("inscripcion", "999", 422),
                                             ("inscripcion", "NaN", 422), ("otro", "80", 422)]:
                response = client.post("/api/vouchers", data={"concepto": concepto, "monto": monto, "carrera": "Turismo"},
                                       files={"imagen": ("voucher.png", b"test", "image/png")})
                self.assertEqual(response.status_code, expected)
            self.assertEqual(list(Path(self.server._VOUCHERS_DIR).iterdir()), [])
            response = client.post("/api/vouchers", data={"concepto": "inscripcion", "monto": "80.00", "carrera": "Turismo"},
                                   files={"imagen": ("voucher.png", valid_png(), "image/png")})
            self.assertEqual(response.status_code, 200)
            self.assertIsNotNone(self.server.session_manager.repository.get_record('vouchers', response.json()['voucher_id']))

    def test_tts_failure_preserves_text_and_sse_done(self):
        async def chunks():
            yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content="Respuesta institucional. Otra oración."))])
        with patch.object(self.server, "stream_respuesta_llm", AsyncMock(return_value=chunks())), \
             patch.object(self.server, "generar_audio_bytes", AsyncMock(side_effect=RuntimeError("tts-test"))), \
             TestClient(self.server.app) as client:
            response = client.post("/chat/stream", json={"mensaje": "Hola", "session_id": self.id()})
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        self.assertEqual(events[-1]["full_text"], "Respuesta institucional. Otra oración.")
        self.assertTrue(any(e["type"] == "text" for e in events))

    def test_legacy_chat_and_support_routes(self):
        with patch.object(self.server, "generar_respuesta_llm", AsyncMock(return_value="Respuesta institucional.")) as llm, \
             patch.object(self.server, "generar_audio_bytes", AsyncMock(return_value=b"audio")), \
             TestClient(self.server.app) as client:
            for mode in ["web", "kiosk"]:
                for persona in ["info", "sales"]:
                    response = client.post("/chat", json={"mensaje": "Hola", "mode": mode, "persona": persona,
                                                          "session_id": self.id() + mode + persona})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["texto"], "Respuesta institucional.")
                    self.assertTrue(response.json()["audio_b64"])
                    self.assertEqual(llm.call_args.kwargs["persona"], persona)
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.get("/api/media").status_code, 200)
            self.assertEqual(client.get("/static/media/yape_qr.webp").status_code, 200)
            self.assertEqual(client.post("/reset-session", json={"mensaje": "", "session_id": "test"}).status_code, 200)

    def test_real_prompt_and_voice_filter_preserve_official_overrides(self):
        config = types.ModuleType("config")
        config.settings = types.SimpleNamespace(groq_api_key="test", session_max_history_turns=4)
        groq = types.ModuleType("groq")
        groq.AsyncGroq = lambda **kwargs: None
        spec = importlib.util.spec_from_file_location("phase1_llm", ROOT / "services" / "llm_service.py")
        llm = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"config": config, "groq": groq}):
            spec.loader.exec_module(llm)
        for mode in ["web", "kiosk"]:
            for persona in ["info", "sales"]:
                prompt = llm.construir_prompt_sistema(mode=mode, persona=persona)
                self.assertIn("importes, campañas y gratuidad provienen exclusivamente de PricingService", prompt)
                self.assertIn("No ofrezcas sábados para otras carreras", prompt)
                self.assertNotIn("350 soles", prompt)
        self.assertIn("pendiente de confirmación", llm.filtrar_texto("La matrícula cuesta S/ 250."))
        self.assertIn("80 soles", llm.filtrar_texto("La inscripción cuesta 999 PEN."))


if __name__ == "__main__":
    unittest.main()
