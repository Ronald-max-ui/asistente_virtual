"""Regresiones de Fase 1; no requieren red ni base vectorial."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_support  # Inicializa una base comercial temporal para estas regresiones.

from services.consent_service import autorizar_accion
from services.pricing_service import resolver_pago, sanear_tarifas_texto
from services.action_service import validar_accion


class ConsentTests(unittest.TestCase):
    def test_explicit_requests(self):
        for action, query in [("SHOW_GALLERY", "Muéstrame fotos"),
                              ("OPEN_LEAD_FORM", "Quiero dejar mis datos"),
                              ("SHOW_PAYMENT", "Quiero pagar mi inscripción")]:
            self.assertTrue(autorizar_accion(action, query, []))

    def test_negations_and_information_are_not_consent(self):
        for query in ["No quiero pagar", "No me pases el QR", "¿Cuánto cuesta?",
                      "¿Tengo que pagar?", "¿Puedo pagar con Yape?", "No quiero inscribirme",
                      "Todavía no", "No, gracias", "¿Qué es un QR?"]:
            self.assertFalse(autorizar_accion("SHOW_PAYMENT", query, []), query)
        for action, query in [("SHOW_GALLERY", "No quiero ver fotos"),
                              ("OPEN_LEAD_FORM", "No quiero dejar mis datos"),
                              ("OPEN_LEAD_FORM", "¿Cómo protegen mis datos?")]:
            self.assertFalse(autorizar_accion(action, query, []))

    def test_confirmation_requires_matching_single_offer(self):
        history = [{"role": "assistant", "content": "¿Quieres que te muestre fotos de los talleres?"}]
        self.assertTrue(autorizar_accion("SHOW_GALLERY", "Sí, por favor", history))
        self.assertFalse(autorizar_accion("SHOW_PAYMENT", "Sí", history))
        self.assertFalse(autorizar_accion("SHOW_GALLERY", "Sí, pero no ahora", history))
        self.assertFalse(autorizar_accion("OPEN_LEAD_FORM", "Sí", [{"role": "assistant", "content": "¿Qué horario prefieres?"}]))
        self.assertFalse(autorizar_accion("SHOW_GALLERY", "Muéstrame el QR", []))
        self.assertFalse(autorizar_accion("SHOW_GALLERY", "Muéstrame el formulario", []))
        ambiguous = [{"role": "assistant", "content": "¿Quieres que te muestre fotos o que te abra el formulario?"}]
        self.assertFalse(autorizar_accion("SHOW_GALLERY", "Sí", ambiguous))

    def test_modes_personas_and_lead_state(self):
        for mode in ["web", "kiosk"]:
            for persona in ["info", "sales"]:
                self.assertTrue(autorizar_accion("SHOW_GALLERY", "Muéstrame fotos", [], mode=mode, persona=persona))
                expected = mode == "web" and persona == "sales"
                self.assertEqual(expected, autorizar_accion("SHOW_PAYMENT", "Quiero pagar", [], mode=mode, persona=persona))
                self.assertEqual(expected, autorizar_accion("OPEN_LEAD_FORM", "Quiero dejar mis datos", [], mode=mode, persona=persona))
        self.assertFalse(autorizar_accion("OPEN_LEAD_FORM", "Quiero dejar mis datos", [], lead_submitted=True))
        self.assertFalse(autorizar_accion("UNKNOWN", "Sí", []))


class PricingTests(unittest.TestCase):
    def test_unconfirmed_prices_cannot_reach_voice(self):
        self.assertEqual("La inscripción cuesta 80 soles.", sanear_tarifas_texto("La inscripción cuesta 999 soles."))
        self.assertIn("80 soles", sanear_tarifas_texto("La inscripción es gratuita."))
        self.assertEqual("La inscripción cuesta 80 soles.", sanear_tarifas_texto("La inscripción no es gratuita."))
        for text in ["La matrícula cuesta 250 soles.", "La mensualidad es S/ 399.", "La mensualidad es S/. 399.", "La cuota es 300 PEN."]:
            self.assertIn("pendiente de confirmación", sanear_tarifas_texto(text))
        self.assertIn("pendiente", sanear_tarifas_texto("La inscripción cuesta 80 soles. La matrícula cuesta 80 soles."))

    def test_confirmed_inscription(self):
        payment = resolver_pago("Quiero pagar la inscripción de Turismo", [], ["Turismo", "999"])
        self.assertEqual("80", payment["monto"])
        self.assertEqual("inscripcion", payment["concepto"])
        self.assertTrue(payment["tarifa_confirmada"])

    def test_no_inferred_tuition_or_default_program(self):
        for program in ["Gastronomía", "Turismo", "Administración", "Contabilidad", "Bartender", "Panadería"]:
            payment = resolver_pago("Quiero pagar mi matrícula de " + program, [], [program, "100"])
            self.assertIsNone(payment["monto"])
            self.assertFalse(payment["tarifa_confirmada"])
        self.assertEqual("", resolver_pago("Quiero pagar", [], ["general", "250"])["carrera"])

    def test_model_cannot_inject_program_or_amount(self):
        payment = resolver_pago("Quiero pagar", [], ['<img src=x onerror=alert(1)>', '999'])
        self.assertEqual("", payment["carrera"])
        self.assertIsNone(payment["monto"])


class ActionTests(unittest.TestCase):
    def test_unknown_and_payment_gallery_are_blocked(self):
        for resource in ["unknown", "yape_qr", '<img src=x onerror=alert(1)>']:
            self.assertIsNone(validar_accion("SHOW_GALLERY", [resource], "Muéstrame fotos", [], mode="web", persona="sales"))

    def test_pending_price_and_explicit_consent(self):
        self.assertEqual(None, validar_accion("SHOW_PAYMENT", ["Gastronomia", "999"], "Quiero pagar Gastronomía", [], mode="web", persona="sales"))
        self.assertIsNone(validar_accion("OPEN_LEAD_FORM", ["Gastronomia"], "Hola", [], mode="web", persona="sales"))


if __name__ == "__main__":
    unittest.main()
