from fastapi import WebSocket
import docker
from docker.models.containers import Container
from typing import Dict, List
import selectors
from threading import Thread
import asyncio
from pydantic import BaseModel
from socket import SocketIO

class Poller(Thread):
    """
    stores all open sockets to docker containers
    as soon as data is available to read (stdout/stderr) from one socket, it calls send_from_console on the associated server"""
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
        """associate a websocket connection with the given container id"""
        server = self.servers[id]
        server.console_listeners.append(ws)

    def send_console_in(self, id: str, data: str):
        """send data to a servers stdin"""
        server = self.servers[id]
        server.send_to_console_in(data + "\n")
    
    def find_running_servers(self):
        """find all servers that have been created with this poc to store their ids in memory"""
        containers = self.client.containers.list(all=True,filters={
            "label": "mc-docker"
        })

        for container in containers:
            id: str = container.id # type: ignore

            self.servers[id] = Server(
                id=id,
                container=container
            )

    def create_server(self) -> str:
        """create a server"""
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

        self.servers[id].start()

        return id

class ServerData(BaseModel):
    id: str
    online: bool
    name: str

class Server:
    def __init__(self, id: str, container: Container) -> None:
        self.id = id
        self.container = container
        self.console_listeners: List[WebSocket] = []

        self.attach_socket: SocketIO = None # type: ignore

        if self.container.status == "running":
            self._connect()

    
    def _connect(self):
        """The magic: attach to the docker container and access stdin/stdout/stderr as a stream
        set the socket to nonblocking to use select
        allow writing to stdin"""
        self.attach_socket = self.container.attach_socket(params={'stdin': 1, 'stdout': 1, 'stderr': 1, 'stream':1})
        self.attach_socket._sock.setblocking(False) # type: ignore
        self.attach_socket._writing = True # type: ignore

        poller.register(self.attach_socket, self)
    
    def get_data(self) -> ServerData:
        self.container.reload()
        return ServerData(
            id=self.id,
            online=self.container.status == "running",
            name=self.container.name # type: ignore
        )
    
    def start(self):
        self.container.start()
        self._connect()
    
    def stop(self):
        self.container.stop(timeout=2)
        poller.selector.unregister(self.attach_socket)
        self.attach_socket = None # type: ignore
    
    def send_to_console_in(self, text: str):
        if not self.attach_socket:
            raise IOError("nope")
        self.attach_socket.write(text.encode())

    async def send_from_console(self, data: bytes):
        """send some data to all websockets associated with this server"""
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