/** Pauses hidden rendering, resumes with bounded delta and explicit cleanup. */
export function createRenderLoop(frame, { document: doc = document,
  requestFrame = requestAnimationFrame, cancelFrame = cancelAnimationFrame } = {}) {
  let id = null, stopped = false, last = null, elapsed = 0;
  function schedule() { if (!stopped && !doc.hidden && id === null) id = requestFrame(tick); }
  function tick(timestamp) {
    id = null;
    if (stopped || doc.hidden) return;
    const delta = last === null ? 0 : Math.min((timestamp - last) / 1000, 0.05);
    last = timestamp; elapsed += delta;
    frame(delta, elapsed); schedule();
  }
  function visibility() {
    if (id !== null) cancelFrame(id);
    id = null; last = null;
    schedule();
  }
  doc.addEventListener('visibilitychange', visibility);
  schedule();
  return () => { stopped = true; if (id !== null) cancelFrame(id); id = null;
    doc.removeEventListener('visibilitychange', visibility); };
}
