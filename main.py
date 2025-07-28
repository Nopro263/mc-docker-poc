from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from typing import Iterable
import starlette.websockets

from manager import Manager

app = FastAPI()
manager = Manager()
manager.find_running_servers()


@app.websocket("/api/server/{id:str}/console")
async def console_endpoint(websocket: WebSocket, id: str):
    await websocket.accept()

    manager.create_websocket(id, websocket)

    while True:
        try:
            data = await websocket.receive_text()
            manager.send_console_in(id, data)
        except starlette.websockets.WebSocketDisconnect:
            return

@app.get("/api/servers")
def get_severs() -> Iterable[str]:
    return manager.servers.keys()

@app.post("/api/servers")
def create_server() -> str:
    return manager.create_server()

@app.get("/")
def index():
    return RedirectResponse("/index.html")

app.mount("/", StaticFiles(directory="static"), name="static")