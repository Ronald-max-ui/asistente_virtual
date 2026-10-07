"""Pruebas HTTP con RAG/LLM/TTS simulados: sin red, ingestión ni escrituras."""
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


def load_server():
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
    spec = importlib.util.spec_from_file_location("phase1_server", ROOT / "server.py")
    server = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"config": config, "services.rag_service": rag, "services.llm_service": llm}), patch("os.makedirs"):
        spec.loader.exec_module(server)
    server.app.state.commercial_service = commercial_service
    return server


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
        with TestClient(self.server.app) as client, patch("builtins.open", mock_open()) as files:
            for concepto, monto, expected in [("matricula", "250", 409), ("inscripcion", "999", 422),
                                             ("inscripcion", "NaN", 422), ("otro", "80", 422)]:
                response = client.post("/api/vouchers", data={"concepto": concepto, "monto": monto, "carrera": "Turismo"},
                                       files={"imagen": ("voucher.png", b"test", "image/png")})
                self.assertEqual(response.status_code, expected)
            files.assert_not_called()
            response = client.post("/api/vouchers", data={"concepto": "inscripcion", "monto": "80.00", "carrera": "Turismo"},
                                   files={"imagen": ("voucher.png", b"test", "image/png")})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(files.call_count, 2)

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
