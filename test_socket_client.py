import socketio
import asyncio

sio = socketio.AsyncClient()

@sio.event
async def connect():
    print("✅ Connected to Socket.IO server")

@sio.event
async def new_message(data):
    print(f"📩 Received Socket.IO Event: {data}")

@sio.event
async def disconnect():
    print("❌ Disconnected from server")

async def main():
    try:
        await sio.connect('http://localhost:8001', socketio_path='/socket.io')
        await sio.wait()
    except Exception as e:
        print(f"Connection Error: {e}")

if __name__ == '__main__':
    asyncio.run(main())
