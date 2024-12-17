import asyncio
import json
import time
import random
import uuid
import ssl
from base64 import b64encode, b64decode
from aiohttp import ClientSession, WSMsgType
from websockets_proxy import Proxy, proxy_connect
from loguru import logger

class GrassConnection:
    def __init__(self, proxy_url, user_id):
        self.proxy_url = proxy_url
        self.user_id = user_id
        self.device_id = str(uuid.uuid3(uuid.NAMESPACE_DNS, proxy_url))
        self.connection_port = ["4444", "4650"]
        self.uri = f"wss://proxy2.wynd.network:{random.choice(self.connection_port)}/"
        self.custom_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Origin": "chrome-extension://lkbnfiajjmbhnfledhphioinpickokdi"
        }
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE

    async def connect(self):
        proxy = Proxy.from_url(self.proxy_url)

        while True:
            try:
                await asyncio.sleep(random.uniform(0.1, 1.0))

                async with proxy_connect(
                    self.uri,
                    proxy=proxy,
                    ssl=self.ssl_context,
                    extra_headers=self.custom_headers,
                    server_hostname="proxy2.wynd.network"
                ) as websocket:
                    await self.handle_connection(websocket)

            except Exception as e:
                logger.error(f"Connection error on proxy {self.proxy_url}: {e}")
                if "Device creation limit exceeded" in str(e):
                    await self.log_and_remove_broken_proxy()
                    return None

    async def handle_connection(self, websocket):
        async def send_ping():
            while True:
                ping_message = json.dumps({
                    "id": str(uuid.uuid4()),
                    "version": "1.0.0",
                    "action": "PING",
                    "data": {}
                })
                logger.info(f"Sending ping: {ping_message}")
                await websocket.send(ping_message)
                await asyncio.sleep(60)

        send_ping_task = asyncio.create_task(send_ping())

        try:
            while True:
                response = await websocket.recv()
                message = json.loads(response)
                logger.debug(f"Received message: {message}")
                await self.handle_message(websocket, message)

        except asyncio.CancelledError:
            send_ping_task.cancel()
        except Exception as e:
            logger.error(f"Error during connection: {e}")
        finally:
            send_ping_task.cancel()

    async def handle_message(self, websocket, message):
        if message.get("action") == "AUTH":
            auth_response = {
                "id": message["id"],
                "origin_action": "AUTH",
                "result": {
                    "browser_id": self.device_id,
                    "user_id": self.user_id,
                    "user_agent": self.custom_headers["User-Agent"],
                    "timestamp": int(time.time()),
                    "device_type": "extension",
                    "version": "4.26.2",
                    "extension_id": "lkbnfiajjmbhnfledhphioinpickokdi"
                }
            }
            logger.debug(f"Sending auth response: {auth_response}")
            await websocket.send(json.dumps(auth_response))

        elif message.get("action") == "PONG":
            pong_response = {"id": message["id"], "origin_action": "PONG"}
            logger.debug(f"Sending pong response: {pong_response}")
            await websocket.send(json.dumps(pong_response))

    async def log_and_remove_broken_proxy(self):
        logger.debug(f"Removing faulty proxy: {self.proxy_url}")
