from fastapi import WebSocket
import docker
from docker.models.containers import Container
from typing import Dict, List
import selectors
from threading import Thread
import asyncio

class Poller(Thread):
    def run(self) -> None:
        self.selector = selectors.DefaultSelector()
        self.data: Dict[int, Server] = {}
        asyncio.run(self.async_run())

    async def async_run(self) -> None:
        while True:
            for key,mask in self.selector.select(timeout=5):
                await self.data[key.fd].send_from_console(key.fileobj.read()) # type: ignore
    
    def register(self, socket, data):
        self.data[socket.fileno()] = data
        self.selector.register(socket, selectors.EVENT_READ)

poller = Poller()
poller.daemon = True
poller.start()

class Manager:
    def __init__(self) -> None:
        self.servers: Dict[str, Server] = {}
        self.client = docker.DockerClient(base_url='unix://var/run/docker.sock')
    
    def create_websocket(self, id: str, ws: WebSocket):
        server = self.servers[id]
        server.console_listeners.append(ws)

    def send_console_in(self, id: str, data: str):
        server = self.servers[id]
        server.send_to_console_in(data + "\n")
    
    def find_running_servers(self):
        containers = self.client.containers.list(filters={
            "label": "mc-docker"
        })

        for container in containers:
            id: str = container.id # type: ignore

            self.servers[id] = Server(
                id=id,
                container=container
            )

    def create_server(self) -> str:
        container = self.client.containers.create(
            image="alpine",
            entrypoint="sh",
            detach=True,
            stdin_open=True,
            labels=["mc-docker"]
        )

        id: str = container.id # type: ignore

        self.servers[id] = Server(
            id=id,
            container=container
        )

        container.start()

        return id

class Server:
    def __init__(self, id: str, container: Container) -> None:
        self.id = id
        self.container = container
        self.console_listeners: List[WebSocket] = []

        self.attach_socket = self.container.attach_socket(params={'stdin': 1, 'stdout': 1, 'stderr': 1, 'stream':1})
        self.attach_socket._sock.setblocking(False)
        self.attach_socket._writing = True

        poller.register(self.attach_socket, self)
    
    def send_to_console_in(self, text: str):
        self.attach_socket.write(text.encode())

    async def send_from_console(self, data: bytes):
        to_remove: List[WebSocket] = []
        for ws in self.console_listeners:
            try:
                await ws.send_json({
                    "console_out": data[8:].decode()
                })
            except Exception as e:
                print(e)
                to_remove.append(ws)
        
        for ws in to_remove:
            try:
                await ws.close(reason="error")
            except Exception:
                pass
            finally:
                self.console_listeners.remove(ws)

