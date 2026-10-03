import sys
import asyncio
import edge_tts

if len(sys.argv) < 3:
    sys.exit(1)

texto = sys.argv[1]
archivo_salida = sys.argv[2]

# Voz sugerida: "es-PE-CamilaNeural" (acento peruano) o "es-MX-DaliaNeural" (latino neutro)
VOZ_SELECCIONADA = "es-PE-CamilaNeural"

async def generar():
    # rate="+10%" le da un ritmo comercial ágil y dinámico
    comunicador = edge_tts.Communicate(texto, VOZ_SELECCIONADA, rate="-8%")
    await comunicador.save(archivo_salida)

if __name__ == "__main__":
    asyncio.run(generar())