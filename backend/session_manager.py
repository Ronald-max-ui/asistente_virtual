"""
session_manager.py — Gestión de sesiones multi-turno con TTL y limpieza automática.

Mejoras respecto al prototipo:
  - asyncio.Lock para proteger el diccionario de sesiones de accesos concurrentes.
  - Tarea de limpieza periódica en background (no depende de que llegue una petición).
  - Método contar_sesiones() para el endpoint /health.
"""
import asyncio
import time
from typing import Dict, List


class SessionManager:
    def __init__(self, ttl: int = 90, cleanup_interval: int = 60) -> None:
        self._sessions: Dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._ttl = ttl
        self._cleanup_interval = cleanup_interval

    async def obtener_o_crear(self, session_id: str) -> List[dict]:
        """
        Devuelve el historial de la sesión. Si la sesión expiró o no existe,
        la reinicia limpia. La actualización de last_active se hace aquí.
        """
        async with self._lock:
            ahora = time.time()
            if session_id in self._sessions:
                sesion = self._sessions[session_id]
                # Sesión expirada: reiniciar sesión completa
                if ahora - sesion["last_active"] > self._ttl:
                    self._sessions[session_id] = {
                        "history": [],
                        "shown_media": [],
                        "funnel_stage": "discovery",
                        "lead_submitted": False,
                        "last_active": ahora,
                    }
                else:
                    sesion.setdefault("shown_media", [])
                    sesion.setdefault("funnel_stage", "discovery")
                    sesion.setdefault("lead_submitted", False)
            else:
                self._sessions[session_id] = {
                    "history": [],
                    "shown_media": [],
                    "funnel_stage": "discovery",
                    "lead_submitted": False,
                    "last_active": ahora,
                }

            self._sessions[session_id]["last_active"] = ahora
            return self._sessions[session_id]["history"]

    async def obtener_sesion(self, session_id: str) -> dict:
        """Retorna el diccionario completo de la sesión ({history, shown_media, funnel_stage, lead_submitted, last_active})."""
        async with self._lock:
            ahora = time.time()
            if session_id in self._sessions:
                sesion = self._sessions[session_id]
                if ahora - sesion["last_active"] > self._ttl:
                    self._sessions[session_id] = {
                        "history": [],
                        "shown_media": [],
                        "funnel_stage": "discovery",
                        "lead_submitted": False,
                        "last_active": ahora,
                    }
                else:
                    sesion.setdefault("shown_media", [])
                    sesion.setdefault("funnel_stage", "discovery")
                    sesion.setdefault("lead_submitted", False)
            else:
                self._sessions[session_id] = {
                    "history": [],
                    "shown_media": [],
                    "funnel_stage": "discovery",
                    "lead_submitted": False,
                    "last_active": ahora,
                }
            self._sessions[session_id]["last_active"] = ahora
            return self._sessions[session_id]

    async def actualizar_etapa_embudo(self, session_id: str, stage: str) -> None:
        """Actualiza la etapa del embudo ('discovery', 'value', 'lead_captured', 'closing')."""
        async with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id]["funnel_stage"] = stage

    async def registrar_lead_completado(self, session_id: str) -> None:
        """Marca lead_submitted=True y funnel_stage='closing' tras registrar formulario."""
        async with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id]["lead_submitted"] = True
                self._sessions[session_id]["funnel_stage"] = "closing"

    async def registrar_medio_mostrado(self, session_id: str, resource_id: str) -> None:
        """Registra un recurso visual mostrado en la sesión para evitar repeticiones."""
        async with self._lock:
            if session_id in self._sessions:
                shown = self._sessions[session_id].setdefault("shown_media", [])
                if resource_id not in shown:
                    shown.append(resource_id)

    async def resetear(self, session_id: str) -> None:
        """Elimina explícitamente una sesión (ej. tras reset manual del kiosco)."""
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def contar_sesiones(self) -> int:
        """Retorna el número de sesiones activas (para /health)."""
        async with self._lock:
            return len(self._sessions)

    async def limpiar_expiradas(self) -> int:
        """Elimina las sesiones cuyo TTL ha vencido. Retorna la cantidad eliminada."""
        async with self._lock:
            ahora = time.time()
            expiradas = [
                sid
                for sid, s in self._sessions.items()
                if ahora - s["last_active"] > self._ttl
            ]
            for sid in expiradas:
                del self._sessions[sid]
            return len(expiradas)

    async def iniciar_limpieza_periodica(self) -> None:
        """
        Corrutina de larga duración que limpia sesiones expiradas cada
        `cleanup_interval` segundos. Debe correrse como asyncio.Task en el lifespan.
        """
        while True:
            await asyncio.sleep(self._cleanup_interval)
            eliminadas = await self.limpiar_expiradas()
            if eliminadas > 0:
                print(f"[Session GC] {eliminadas} sesión(es) expirada(s) eliminada(s).")
