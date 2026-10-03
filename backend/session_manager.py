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
                # Sesión expirada: reiniciar historial
                if ahora - sesion["last_active"] > self._ttl:
                    self._sessions[session_id] = {"history": [], "last_active": ahora}
            else:
                self._sessions[session_id] = {"history": [], "last_active": ahora}

            self._sessions[session_id]["last_active"] = ahora
            return self._sessions[session_id]["history"]

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
