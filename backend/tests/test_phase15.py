"""Fase 1.5: esquemas estrictos, autorización y adaptación legada."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.action_service import ActionContext, procesar_acciones, herramientas_llm
from services.llm_protocol import LegacyActionAdapter, ToolCallCollector


class StructuredActionsTests(unittest.TestCase):
    def context(self, query="Quiero pagar la inscripción de Gastronomía", **kwargs):
        return ActionContext(pregunta=query, historial=[], **kwargs)

    def test_model_amount_and_arbitrary_fields_are_rejected(self):
        for field in ["amount", "monto", "qr_url", "html", "currency"]:
            result = procesar_acciones([{"type": "show_payment", "program": "gastronomia",
                                       "concept": "inscripcion", field: "999"}], self.context())
            self.assertEqual(result.actions, [])

    def test_inscription_uses_catalog_and_pending_has_no_action(self):
        result = procesar_acciones([{"type": "show_payment", "program": "Gastronomía", "concept": "Inscripción"}], self.context())
        self.assertEqual(result.actions[0]["amount"], "80")
        self.assertEqual(result.actions[0]["program"], "gastronomia")
        result = procesar_acciones([{"type": "show_payment", "program": "gastronomia", "concept": "matricula"}],
                                  self.context("Quiero pagar la matrícula de Gastronomía"))
        self.assertEqual(result.actions, [])
        self.assertEqual(result.notices[0]["code"], "tariff_pending")

    def test_unknown_program_concept_variant_and_type_are_rejected(self):
        for changes in [{"program": "medicina"}, {"concept": "donacion"}, {"modality": "telepatia"},
                        {"shift": "domingo"}, {"type": "run_code"}]:
            request = {"type": "show_payment", "program": "gastronomia", "concept": "inscripcion", **changes}
            self.assertEqual(procesar_acciones([request], self.context()).actions, [])

    def test_consent_context_and_capabilities(self):
        request = {"type": "show_payment", "program": "gastronomia", "concept": "inscripcion"}
        self.assertEqual(procesar_acciones([request], self.context("No quiero pagar")).actions, [])
        self.assertEqual(procesar_acciones([request], self.context("Quiero pagar la matrícula de Gastronomía")).actions, [])
        for mode in ["web", "kiosk"]:
            for persona in ["info", "sales"]:
                result = procesar_acciones([request], self.context(mode=mode, persona=persona))
                self.assertEqual(bool(result.actions), mode == "web" and persona == "sales")
                gallery = {"type": "show_gallery", "resource_id": "gastronomia_talleres"}
                self.assertEqual(len(procesar_acciones([gallery], self.context("Muéstrame fotos", mode=mode, persona=persona)).actions), 1)

    def test_tool_schemas_have_no_amount_and_forbid_extra_fields(self):
        tools = herramientas_llm()
        self.assertEqual({t["function"]["name"] for t in tools}, {"show_payment", "show_contact", "show_gallery"})
        for tool in tools:
            schema = tool["function"]["parameters"]
            self.assertFalse(schema["additionalProperties"])
            self.assertNotIn("amount", schema["properties"])

    def test_catalog_is_only_consulted_after_consent(self):
        request = {"type": "show_payment", "program": "gastronomia", "concept": "inscripcion"}
        with patch("services.action_service.pricing_service.resolve") as catalog:
            self.assertEqual(procesar_acciones([request], self.context("No quiero pagar")).actions, [])
            catalog.assert_not_called()

    def test_short_confirmation_is_bound_to_offered_concept_and_program(self):
        history = [{"role": "assistant", "content": "¿Quieres pagar la inscripción de Gastronomía con el QR?"}]
        context = ActionContext("Sí", history)
        request = {"type": "show_payment", "program": "gastronomia", "concept": "inscripcion"}
        self.assertEqual(procesar_acciones([request], context).actions[0]["amount"], "80")
        self.assertEqual(procesar_acciones([{**request, "program": "turismo"}], context).actions, [])
        self.assertEqual(procesar_acciones([{**request, "concept": "matricula"}], context).actions, [])
        self.assertEqual(procesar_acciones([request], ActionContext("Sí", [])).actions, [])

    def test_legacy_discards_amount_and_strips_fragmented_or_malformed_tags(self):
        adapter = LegacyActionAdapter("Quiero pagar la inscripción de Gastronomía", [])
        text = ''.join(adapter.feed(p) for p in ["Hola. [[ACT", "ION:SHOW_PAYMENT:Gastronomia:999.00]] ", "Listo.", " [[ACTION:UNKNOWN:evil]]"])
        text += adapter.finish()
        self.assertNotIn("ACTION", text)
        self.assertNotIn("999", str(adapter.structured_actions))
        result = procesar_acciones(adapter.structured_actions, self.context())
        self.assertEqual(result.actions[0]["amount"], "80")
        truncated = LegacyActionAdapter("Hola", [])
        self.assertEqual(truncated.feed("Texto [[ACTION:SHOW_PAYMENT:"), "Texto ")
        self.assertEqual(truncated.finish(), "")
        self.assertEqual(truncated.structured_actions, [])


if __name__ == "__main__":
    unittest.main()
