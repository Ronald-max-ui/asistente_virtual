"""Tarifas de ejemplo SOLO en fixtures: jamás autorizar los importes antiguos del RAG."""
import copy
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, mock_open, patch
from fastapi.testclient import TestClient
from test_phase1_api import load_server
from services import pricing_service as module
from services.pricing_service import CatalogError, PricingService
from services.action_service import ActionContext, procesar_acciones
from services.action_service import herramientas_llm
from services.llm_protocol import AssistantReply
import types


ROOT = Path(__file__).resolve().parents[1]


class DynamicPricingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name) / "02_carreras"
        directory.mkdir()
        self.path = directory / "gastronomia.pricing.json"
        self.data = json.loads((ROOT / "knowledge/02_carreras/gastronomia.pricing.json").read_text(encoding="utf-8"))
        self.day = date(2026, 10, 7)
        self.service = PricingService(Path(self.temp.name), today=lambda: self.day)
        self.write()

    def write(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")

    def price(self, concept="inscripcion", modality=None, shift=None):
        return self.service.resolve("gastronomia", concept, modality, shift)

    def test_hot_reload_even_when_size_and_mtime_are_unchanged(self):
        self.assertEqual(self.price()["amount"], "80")
        stat = self.path.stat()
        self.data["prices"][0]["amount"] = "90.00"
        self.write()
        os.utime(self.path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(self.path.stat().st_size, stat.st_size)
        self.assertEqual(self.price()["amount"], "90")

    def test_free_and_pending_have_different_meanings_and_neither_opens_payment(self):
        request = {"type": "show_payment", "program": "gastronomia", "concept": "inscripcion"}
        context = ActionContext("Quiero pagar la inscripción de Gastronomía", [])
        for status, amount, code in [("free", 0, "price_free"), ("pending", None, "tariff_pending")]:
            self.data["prices"][0].update(status=status, amount=amount)
            self.write()
            with patch.object(module, "pricing_service", self.service), patch("services.action_service.pricing_service", self.service):
                quote = self.price()
                self.assertEqual(quote["amount"], "0" if status == "free" else None)
                result = procesar_acciones([request], context)
                self.assertEqual(result.actions, [])
                self.assertEqual(result.notices[0]["code"], code)
                message = self.service.authoritative_answer("¿Cuánto cuesta la inscripción de Gastronomía?")
                self.assertIn("gratuita" if status == "free" else "pendiente", message)

    def test_dates_are_inclusive_and_rechecked_without_file_change(self):
        self.data["prices"][0].update(starts_on="2026-10-08", ends_on="2026-10-09")
        self.write()
        self.assertEqual(self.price()["status"], "pending")
        for day in [8, 9]:
            self.day = date(2026, 10, day)
            self.assertEqual(self.price()["status"], "active")
        self.day = date(2026, 10, 10)
        self.assertEqual(self.price()["status"], "pending")

    def test_program_modality_shift_and_concept_use_exact_catalog_prices(self):
        self.data["modalities"].append("virtual")
        base = self.data["prices"][0]
        self.data["prices"][0] = {**base, "modality": "presencial", "amount": "123.45"}
        self.data["prices"].append({**base, "modality": "virtual", "amount": "67.89"})
        self.write()
        self.assertEqual(self.price(modality="presencial")["amount"], "123.45")
        self.assertEqual(self.price(modality="virtual")["amount"], "67.89")
        self.assertEqual(self.price()["reason"], "variant_required")
        for concept in module.CONCEPTOS:
            self.price(concept, "virtual")
        with self.assertRaises(ValueError): self.price(modality="telepatia")
        with self.assertRaises(ValueError): self.price(shift="domingo")
        with self.assertRaises(ValueError): self.service.resolve("medicina", "inscripcion")

    def test_shift_specific_prices_and_campaign_rollover(self):
        base = self.data["prices"][0]
        self.data["prices"][0] = {**base, "ends_on": "2026-10-07"}
        self.data["prices"].append({**base, "campaign": "campana_siguiente", "starts_on": "2026-10-08", "shift": "sabados", "amount": "45.00"})
        self.write()
        self.assertEqual(self.price(shift="sabados")["amount"], "80")
        self.day = date(2026, 10, 8)
        self.assertEqual(self.price(shift="sabados")["amount"], "45")
        self.assertEqual(self.price(shift="lunes_viernes")["status"], "pending")

    def test_invalid_reload_blocks_old_price_and_recovers_after_fix(self):
        self.assertEqual(self.price()["amount"], "80")
        self.path.write_text('{"invalid":', encoding="utf-8")
        with self.assertRaises(CatalogError): self.price()
        self.assertIn("necesita revisión", self.service.authoritative_answer("Precio inscripción Gastronomía"))
        with patch("services.action_service.pricing_service", self.service):
            self.assertEqual([tool["function"]["name"] for tool in herramientas_llm()], ["show_gallery"])
        self.write()
        self.assertEqual(self.price()["amount"], "80")
        self.path.unlink()
        with self.assertRaises(CatalogError): self.price()

    def test_invalid_states_amounts_ranges_fields_and_overlap_are_rejected(self):
        original = copy.deepcopy(self.data)
        for change in [{"status":"free", "amount":None}, {"status":"pending", "amount":0},
                       {"status":"active", "amount":0}, {"amount":True}, {"amount":"NaN"},
                       {"amount":"1.999"}, {"amount":"-1"}, {"currency":"soles"},
                       {"starts_on":"2026-10-10", "ends_on":"2026-10-01"}, {"html":"<script>evil()</script>"}]:
            self.data = copy.deepcopy(original)
            self.data["prices"][0].update(change)
            self.write()
            with self.assertRaises(CatalogError): self.price()
        self.data = original
        self.data["prices"].append(copy.deepcopy(self.data["prices"][0]))
        self.write()
        with self.assertRaises(CatalogError): self.price()

    def test_promotions_are_metadata_and_never_derive_an_amount(self):
        self.data["prices"][0]["promotions"] = [{"id":"ejemplo", "description":"Descuento de ejemplo", "kind":"percent", "value":"10", "conditions":"Condiciones aprobadas por el administrador"}]
        self.write()
        quote = self.price()
        self.assertEqual(quote["amount"], "80")
        self.assertEqual(quote["promotions"][0]["value"], "10")

    def test_model_promotions_and_non_numeric_free_claims_are_not_authoritative(self):
        with patch.object(module, "pricing_service", self.service):
            for text in ["La inscripción cuesta noventa soles.", "La inscripción es gratuita.",
                         "La inscripción cuesta $999.", "Hay un descuento de 75%."]:
                answer = module.sanear_tarifas_texto(text, "Precio de inscripción Gastronomía")
                self.assertNotIn("999", answer)
                self.assertNotIn("75%", answer)
                self.assertNotIn("noventa", answer)
                self.assertNotIn("es gratuita", answer)
            self.assertEqual(module.respuesta_comercial("¿Cuánto dura Gastronomía?"), "")

    def test_routes_and_vouchers_revalidate_edits_without_restart_or_rag_refresh(self):
        server = load_server(pricing=self.service)
        request = {"type":"show_payment", "program":"gastronomia", "concept":"inscripcion"}
        async def chunks():
            # Viejo contenido vectorial/modelo intenta imponer otro importe.
            yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content="La inscripción cuesta 999 soles."))])
            yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=None, tool_calls=[types.SimpleNamespace(index=0, function=types.SimpleNamespace(name="show_payment", arguments=json.dumps({"program":"gastronomia", "concept":"inscripcion"})))]))])
        with patch.object(module, "pricing_service", self.service), patch("services.action_service.pricing_service", self.service), \
             patch.object(server, "generar_respuesta_llm", AsyncMock(return_value=AssistantReply(assistant_text="La inscripción cuesta 999 soles.", structured_actions=[request]))), \
             patch.object(server, "generar_audio_bytes", AsyncMock(return_value=b"audio")), TestClient(server.app) as client:
            for index, amount in enumerate(["95.00", "0", None]):
                status = "active" if index == 0 else "free" if index == 1 else "pending"
                self.data["prices"][0].update(status=status, amount=amount)
                self.write()
                body = {"mensaje":"Quiero pagar la inscripción de Gastronomía", "persona":"sales", "mode":"web"}
                regular = client.post("/chat", json={**body, "session_id":f"dynamic-json-{index}"}).json()
                with patch.object(server, "stream_respuesta_llm", AsyncMock(return_value=chunks())):
                    response = client.post("/chat/stream", json={**body, "session_id":f"dynamic-sse-{index}"})
                events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
                self.assertEqual(events[-1]["type"], "done")
                self.assertEqual(regular["actions"], [e["action"] for e in events if e["type"] == "ui_action"])
                self.assertEqual(regular["texto"], events[-1]["full_text"])
                self.assertNotIn("999", regular["texto"])
                if status == "active":
                    self.assertEqual(regular["actions"][0]["amount"], "95")
                    self.assertIn("95 soles", regular["texto"])
                else:
                    self.assertEqual(regular["actions"], [])
                with patch("builtins.open", mock_open()) as files:
                    upload = client.post("/api/vouchers", data={"concepto":"inscripcion", "monto":"80", "carrera":"gastronomia"}, files={"imagen":("test.png",b"test","image/png")})
                    self.assertEqual(upload.status_code, 422 if status == "active" else 409)
                    if status == "free":
                        self.assertEqual(upload.json()["code"], "price_free")
                        self.assertIn("gratuita", upload.json()["message"])
                    files.assert_not_called()


if __name__ == "__main__": unittest.main()
