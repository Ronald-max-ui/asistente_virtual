import os
import asyncio
import edge_tts

VOZ = "es-PE-CamilaNeural"
OUTPUT_DIR = os.path.abspath("../avatar-kiosk/public")

FRASES = {
    "atraccion_1.mp3": "¡Hola! ¿Buscas información sobre nuestras carreras? Acércate, estoy aquí para ayudarte.",
    "atraccion_2.mp3": "¡Hola! ¿Aún no decides qué estudiar? Toca el micrófono y resolvemos todas tus dudas.",
    "atraccion_3.mp3": "¡Hey! Ven, acércate a la pantalla y descubre nuestras opciones profesionales."
}

async def exportar():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for archivo, texto in FRASES.items():
        ruta = os.path.join(OUTPUT_DIR, archivo)
        print(f"Generando {archivo}...")
        comunicador = edge_tts.Communicate(texto, VOZ, rate="-8%")
        await comunicador.save(ruta)
    print("¡Audios guardados con éxito en public/!")

if __name__ == "__main__":
    asyncio.run(exportar())