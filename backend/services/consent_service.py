"""Consentimiento conservador basado en el usuario, nunca en la salida del LLM."""
import re
import unicodedata


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto or "").lower()
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", texto)).strip()


def hay_negacion(texto: str) -> bool:
    return bool(re.search(r"\b(no|nunca|jamas|tampoco|todavia|despues|luego)\b|mas tarde|otro momento", normalizar(texto)))


_DIRECTAS = {
    "SHOW_GALLERY": r"\b(?:(?:muestrame|ensenam\w*|mostrarme|quiero ver|deseo ver|puedo ver)\b.*\b(?:fotos?|imagenes?|uniforme|talleres?|barra|hornos?|fachada)|pon la foto|ver las fotos|ver fotos)\b",
    "OPEN_LEAD_FORM": r"\b(quiero (?:dejar|registrar|enviar) mis datos|dej[ao]r? mis datos|abre (?:el|un) formulario|abreme (?:el|un) formulario|muestrame el formulario|quiero (?:inscribirme|matricularme|registrarme)|quiero que me contacten|llamame|que me llame\w*|contactame|quiero hablar con un asesor|agendar (?:una )?visita)\b",
    "SHOW_PAYMENT": r"\b(quiero pagar|deseo pagar|voy a pagar|realizar el pago|hacer el pago|muestrame (?:el )?qr|pasame (?:el )?qr|pasar el qr|envia\w* (?:el )?qr|dame (?:el )?qr|abre (?:el )?pago|quiero (?:yapear|transferir)|(?:dame|muestrame|pasame|envia\w*) (?:los )?datos de pago)\b",
}
_TEMAS = {
    "SHOW_GALLERY": r"\b(fotos?|imagenes?|uniforme|talleres?)\b",
    "OPEN_LEAD_FORM": r"\b(formulario|dejar tus datos|registrar tus datos|contactemos|contacte|contactarte|visita guiada)\b",
    "SHOW_PAYMENT": r"\b(qr|datos de pago|pagar|realizar el pago|pago por yape)\b",
}
_AFIRMACION = re.compile(r"^(si|claro|dale|ok|de acuerdo|acepto|por favor|perfecto|a ver)( (por favor|gracias|adelante))?$")


def accion_disponible(tipo: str, *, mode: str = "web", persona: str = "sales", lead_submitted: bool = False) -> bool:
    """Capacidades únicas para solicitudes del modelo y autorización final."""
    if tipo not in _DIRECTAS or mode not in ("web", "kiosk") or persona not in ("info", "sales"):
        return False
    if tipo != "SHOW_GALLERY" and (mode != "web" or persona != "sales"):
        return False
    if tipo == "OPEN_LEAD_FORM" and lead_submitted:
        return False
    return True


def autorizar_accion(tipo: str, pregunta: str, historial: list | None = None,
                     *, mode: str = "web", persona: str = "sales", lead_submitted: bool = False) -> bool:
    if not accion_disponible(tipo, mode=mode, persona=persona, lead_submitted=lead_submitted):
        return False
    q = normalizar(pregunta)
    if hay_negacion(q):
        return False
    if re.search(_DIRECTAS[tipo], q):
        return True
    if not _AFIRMACION.fullmatch(q):
        return False
    previo = next((t.get("content", "") for t in reversed(historial or []) if t.get("role") == "assistant"), "")
    # Una afirmación corta solo responde a una oferta concreta y no ambigua.
    oferta = normalizar(previo)
    if "?" not in previo or hay_negacion(oferta):
        return False
    if not re.search(r"\b(quieres|deseas|te gustaria|te muestro|te abro|puedo mostrarte|puedo abrirte)\b", oferta):
        return False
    acciones_ofrecidas = [a for a, patron in _TEMAS.items() if re.search(patron, oferta)]
    return acciones_ofrecidas == [tipo]
