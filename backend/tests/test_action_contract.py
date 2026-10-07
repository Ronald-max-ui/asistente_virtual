"""Contrato de producción: salida estricta y única migración desde etiquetas."""
import json
import types
import unittest
from unittest.mock import AsyncMock, patch
from pydantic import ValidationError
from fastapi.testclient import TestClient
from test_phase1_api import load_server
from services.action_service import ActionContext, AUTHORIZED_ACTION_SCHEMA, procesar_acciones, herramientas_llm
from services.llm_protocol import AssistantReply, ChatResponse, SSE_SCHEMA


class ActionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = load_server()

    def test_authorized_dtos_reject_extra_fields_and_unsafe_resource_paths(self):
        context = ActionContext("Quiero pagar la inscripción de Gastronomía", [])
        request = {"type":"show_payment", "program":"gastronomia", "concept":"inscripcion"}
        action = procesar_acciones([request], context).actions[0]
        self.assertNotIn("observations", action)
        self.assertNotIn("promotions", action)
        for change in [{"amount":999}, {"amount":"0"}, {"qr_url":"javascript:evil()"}, {"html":"<script>evil()</script>"}]:
            with self.assertRaises(ValidationError): AUTHORIZED_ACTION_SCHEMA.validate_python({**action, **change})
        with self.assertRaises(ValidationError):
            AUTHORIZED_ACTION_SCHEMA.validate_python({"type":"run_code", "code":"evil()"})

    def test_chat_and_sse_envelopes_are_typed(self):
        with self.assertRaises(ValidationError): ChatResponse(texto="Hola", audio_b64="", actions=[{"type":"run_code"}], notices=[])
        with self.assertRaises(ValidationError): SSE_SCHEMA.validate_python({"type":"ui_action", "action":"SHOW_PAYMENT"})
        with self.assertRaises(ValidationError): SSE_SCHEMA.validate_python({"type":"mode_switch", "mode":"<script>evil()</script>"})
        with self.assertRaises(ValidationError): SSE_SCHEMA.validate_python({"type":"text", "text":"Hola", "code":"evil()"})

    def test_available_tools_share_consent_capabilities(self):
        for mode in ["web", "kiosk"]:
            for persona in ["info", "sales"]:
                names = {t["function"]["name"] for t in herramientas_llm(mode=mode, persona=persona)}
                self.assertEqual(names, {"show_gallery", "show_payment", "show_contact"} if mode == "web" and persona == "sales" else {"show_gallery"})
        self.assertNotIn("show_contact", {t["function"]["name"] for t in herramientas_llm(mode="web", persona="sales", lead_submitted=True)})
        self.assertEqual(herramientas_llm(mode="invalid", persona="sales"), [])

    def both_routes(self, *, request=None, native_present=True, args=None, finish_reason=None):
        text = "Una imagen solicitada. [[ACTION:SHOW_GALLERY:gastronomia_talleres]]"
        async def chunks():
            yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=text))])
            if native_present:
                serialized = args if args is not None else json.dumps({k:v for k,v in request.items() if k != "type"})
                calls = [types.SimpleNamespace(index=0, function=types.SimpleNamespace(name=request["type"] if request else "show_gallery", arguments=serialized))]
                yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=None, tool_calls=calls), finish_reason=finish_reason)])
        reply = AssistantReply(assistant_text=text, structured_actions=[request] if request else [], native_actions_present=native_present)
        with patch.object(self.server, "stream_respuesta_llm", AsyncMock(return_value=chunks())), \
             patch.object(self.server, "generar_respuesta_llm", AsyncMock(return_value=reply)), \
             patch.object(self.server, "generar_audio_bytes", AsyncMock(return_value=b"audio")) as tts, TestClient(self.server.app) as client:
            body = {"mensaje":"Muéstrame fotos", "mode":"web", "persona":"sales"}
            regular = client.post("/chat", json={**body, "session_id":self.id()+"json"}).json()
            response = client.post("/chat/stream", json={**body, "session_id":self.id()+"sse"})
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual([e["action"] for e in events if e["type"] == "ui_action"], regular["actions"])
        self.assertNotIn("[[ACTION", regular["texto"])
        self.assertEqual(regular["texto"], events[-1]["full_text"])
        self.assertTrue(all("[[ACTION" not in call.args[0] for call in tts.call_args_list))
        return regular, events

    def test_native_actions_win_over_legacy_with_identical_route_order(self):
        regular, events = self.both_routes(request={"type":"show_gallery", "resource_id":"gastronomia_uniforme"})
        self.assertEqual([a["resource_id"] for a in regular["actions"]], ["gastronomia_uniforme"])
        self.assertEqual([e["type"] for e in events], ["text", "audio", "ui_action", "done"])

    def test_invalid_native_action_never_falls_back_to_valid_legacy(self):
        regular, _ = self.both_routes(request={"type":"show_gallery", "resource_id":"gastronomia_uniforme", "amount":"999"})
        self.assertEqual(regular["actions"], [])
        regular, _ = self.both_routes(args='{"resource_id":')
        self.assertEqual(regular["actions"], [])

    def test_legacy_remains_only_when_no_native_tool_was_requested(self):
        regular, _ = self.both_routes(native_present=False)
        self.assertEqual([a["resource_id"] for a in regular["actions"]], ["gastronomia_talleres"])
