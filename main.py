from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from typing import Iterable
import starlette.websockets

from manager import Manager, ServerData

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
        except IOError:
            await websocket.send_json({
                    "console_out": "SERVER NOT STARTED"
                })

@app.get("/api/servers")
def get_severs() -> Iterable[ServerData]:
    return [x.get_data() for x in manager.servers.values()]

@app.get("/api/server/{id:str}")
def get_sever(id:str) -> ServerData:
    return manager.servers[id].get_data()

@app.post("/api/server/{id:str}/start")
def start_sever(id:str) -> None:
    return manager.servers[id].start()

@app.post("/api/server/{id:str}/stop")
def stop_sever(id:str) -> None:
    return manager.servers[id].stop()

@app.post("/api/servers")
def create_server() -> ServerData:
    return manager.servers[manager.create_server()].get_data()

@app.get("/")
def index():
    return RedirectResponse("/index.html")

app.mount("/", StaticFiles(directory="static"), name="static")