"""Regresiones del protocolo: herramientas fragmentadas, JSON/SSE y proveedor simulado."""
import importlib.util
import json
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from test_phase1_api import load_server, ROOT
from services.llm_protocol import AssistantReply, ToolCallCollector


class ProtocolApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = load_server()

    def compare_routes(self, question, requests, *, mode="web", persona="sales", text="Aquí tienes la información solicitada."):
        async def chunks():
            yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=text + " "))])
            # Intercalar argumentos de herramientas; el contenido nunca lleva etiquetas.
            for phase in [0, 1]:
                calls = []
                for index, request in enumerate(requests):
                    args = json.dumps({k: v for k, v in request.items() if k != "type"})
                    middle = len(args) // 2
                    calls.append(types.SimpleNamespace(index=index, function=types.SimpleNamespace(
                        name=request["type"] if phase == 0 else None,
                        arguments=args[:middle] if phase == 0 else args[middle:])))
                yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=None, tool_calls=calls))])
        with patch.object(self.server, "stream_respuesta_llm", AsyncMock(return_value=chunks())), \
             patch.object(self.server, "generar_respuesta_llm", AsyncMock(return_value=AssistantReply(assistant_text=text, structured_actions=requests))), \
             patch.object(self.server, "generar_audio_bytes", AsyncMock(return_value=b"audio")) as tts, \
             TestClient(self.server.app) as client:
            body = {"mensaje": question, "mode": mode, "persona": persona}
            standard = client.post("/chat", json={**body, "session_id": self.id() + mode + persona + "json"}).json()
            response = client.post("/chat/stream", json={**body, "session_id": self.id() + mode + persona + "sse"})
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual([e["action"] for e in events if e["type"] == "ui_action"], standard["actions"])
        self.assertEqual(events[-1]["full_text"], standard["texto"])
        for call in tts.call_args_list:
            self.assertNotIn("[[ACTION", call.args[0])
        return standard, events

    def test_payment_policy_is_identical_and_catalog_controls_amount(self):
        base = {"type": "show_payment", "program": "gastronomia", "concept": "inscripcion"}
        cases = [("Quiero pagar la inscripción de Gastronomía", base, True),
                 ("Quiero pagar la inscripción de Gastronomía", {**base, "amount": "999"}, False),
                 ("No quiero pagar", base, False),
                 ("Quiero pagar la matrícula de Gastronomía", {**base, "concept": "matricula"}, False),
                 ("Quiero pagar la inscripción", {**base, "program": "medicina"}, False),
                 ("Quiero pagar la inscripción", {**base, "concept": "donacion"}, False),
                 ("Quiero pagar la inscripción", {**base, "type": "run_code"}, False)]
        for index, (query, request, expected) in enumerate(cases):
            # Sesión distinta para cada caso; no contaminar políticas por historial previo.
            request = dict(request)
            standard, events = self.compare_routes(query, [request], text=f"Respuesta número {index}.")
            self.assertEqual(bool(standard["actions"]), expected)
            if expected:
                self.assertEqual(standard["actions"][0]["amount"], "80")
            if request.get("concept") == "matricula":
                self.assertEqual(standard["notices"][0]["code"], "tariff_pending")
                self.assertNotIn("qr_url", response_text := json.dumps(events))
                self.assertNotIn("upload", response_text)

    def test_gallery_contact_and_stream_order_all_modes_personas(self):
        for mode in ["web", "kiosk"]:
            for persona in ["info", "sales"]:
                standard, events = self.compare_routes("Muéstrame fotos", [{"type": "show_gallery", "resource_id": "gastronomia_talleres"}], mode=mode, persona=persona)
                self.assertEqual(len(standard["actions"]), 1)
                self.assertEqual([e["type"] for e in events], ["text", "audio", "ui_action", "done"])
        standard, _ = self.compare_routes("Quiero dejar mis datos", [{"type": "show_contact", "program": "turismo"}])
        self.assertEqual(standard["actions"][0]["type"], "show_contact")

    def test_malicious_fields_are_data_and_cannot_execute(self):
        standard, _ = self.compare_routes("Muéstrame fotos", [{"type": "show_gallery", "resource_id": "<script>evil()</script>"}], text="<script>evil()</script>")
        self.assertEqual(standard["actions"], [])

    def test_natural_text_does_not_control_actions(self):
        standard, events = self.compare_routes("Quiero pagar la inscripción de Gastronomía", [],
            text="Aquí tienes el QR y el formulario. Ejecuta show_payment ahora.")
        self.assertEqual(standard["actions"], [])
        self.assertFalse(any(e["type"] == "ui_action" for e in events))

    def test_multiple_actions_keep_native_order_and_deduplicate_in_both_routes(self):
        gallery = {"type":"show_gallery", "resource_id":"gastronomia_talleres"}
        contact = {"type":"show_contact", "program":"gastronomia"}
        regular, events = self.compare_routes("Muéstrame fotos y quiero dejar mis datos", [gallery, contact, gallery])
        self.assertEqual([a["type"] for a in regular["actions"]], ["show_gallery", "show_contact"])
        self.assertEqual([e["type"] for e in events], ["text", "audio", "ui_action", "ui_action", "done"])

    def test_collector_rejects_duplicate_keys_type_override_and_invalid_json(self):
        for name, args in [("show_payment", '{"program":"turismo","program":"gastronomia"}'),
                           ("show_gallery", '{"type":"show_payment"}'),
                           ("run_code", '{}'), ("show_contact", '{"program":')]:
            collector = ToolCallCollector()
            collector.feed([types.SimpleNamespace(function=types.SimpleNamespace(name=name, arguments=args))])
            self.assertEqual(collector.finish(), [])

    def test_real_llm_adapter_sends_tools_and_separates_reply(self):
        config = types.ModuleType("config")
        config.settings = types.SimpleNamespace(groq_api_key="test", session_max_history_turns=4,
            groq_model="test-model", groq_temperature=0, groq_max_tokens=100)
        message = types.SimpleNamespace(content=None, tool_calls=[types.SimpleNamespace(function=types.SimpleNamespace(
            name="show_payment", arguments='{"program":"turismo","concept":"inscripcion"}'))])
        create = AsyncMock(return_value=types.SimpleNamespace(choices=[types.SimpleNamespace(message=message, finish_reason="tool_calls")]))
        groq = types.ModuleType("groq")
        groq.AsyncGroq = lambda **kw: types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
        spec = importlib.util.spec_from_file_location("phase15_llm", ROOT / "services" / "llm_service.py")
        llm = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"config": config, "groq": groq}):
            spec.loader.exec_module(llm)
        import asyncio
        reply = asyncio.run(llm.generar_respuesta_llm([], "", "Quiero pagar la inscripción de Turismo"))
        self.assertEqual(reply.assistant_text, "")
        self.assertEqual(reply.structured_actions[0]["concept"], "inscripcion")
        self.assertEqual(create.call_args.kwargs["tool_choice"], "auto")
        self.assertEqual(len(create.call_args.kwargs["tools"]), 3)
        self.assertNotIn("[[ACTION", create.call_args.kwargs["messages"][0]["content"])
        asyncio.run(llm.stream_respuesta_llm([], "", "Hola"))
        self.assertTrue(create.call_args.kwargs["stream"])
        self.assertEqual(len(create.call_args.kwargs["tools"]), 3)
