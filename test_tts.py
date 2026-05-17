import asyncio
import edge_tts

async def main():
    communicate = edge_tts.Communicate('Hola', 'es-MX-DaliaNeural')
    try:
        async for chunk in communicate.stream():
            print('Got chunk')
            break
    except Exception as e:
        print('Error:', e)

asyncio.run(main())
