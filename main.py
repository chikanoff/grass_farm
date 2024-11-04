import asyncio
import random
import ssl
import json
import time
import uuid
from loguru import logger
from websockets_proxy import Proxy, proxy_connect
import aiofiles
import os
import sys

PROXY_FILE = 'proxy.txt'
USER_FILE = 'users.txt'
ASSIGNMENTS_FILE = 'account_proxies.json'

async def load_assignments():
    if os.path.exists(ASSIGNMENTS_FILE):
        if os.path.getsize(ASSIGNMENTS_FILE) > 0:
            with open(ASSIGNMENTS_FILE, 'r') as file:
                return json.load(file)
        else:
            return {}
    return {}

async def save_assignments(assignments):
    with open(ASSIGNMENTS_FILE, 'w') as file:
        json.dump(assignments, file, indent=4)

async def assign_proxies_to_accounts(users, all_proxies):
    assignments = await load_assignments()
    
    assigned_proxies = {proxy for proxies in assignments.values() for proxy in proxies}
    unassigned_proxies = [proxy for proxy in all_proxies if proxy not in assigned_proxies]
    unassigned_users = [user for user in users if user not in assignments]

    if not unassigned_proxies or not unassigned_users:
        logger.info("All proxies are assigned or not unassigned users")
        return assignments

    if len(unassigned_proxies) < len(unassigned_users):
        raise ValueError("Not enough proxy for all users")
    
    num_proxies_per_user, remainder = divmod(len(unassigned_proxies), len(unassigned_users))
    
    random.shuffle(unassigned_proxies)

    proxy_index = 0
    
    for user in unassigned_users:
        proxies_for_user = unassigned_proxies[proxy_index:proxy_index + num_proxies_per_user]
        
        if remainder > 0:
            proxies_for_user.append(unassigned_proxies[proxy_index + num_proxies_per_user])
            proxy_index += 1
            remainder -= 1

        assignments[user] = proxies_for_user
        proxy_index += num_proxies_per_user

    await save_assignments(assignments)
    return assignments

async def connect_to_wss(proxy_url, user_id):
    device_id = str(uuid.uuid3(uuid.NAMESPACE_DNS, proxy_url))
    logger.info(f"Device ID: {device_id}")

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    uri = "wss://proxy.wynd.network:4444/"

    proxy = Proxy.from_url(proxy_url)

    while True:
        try:
            await asyncio.sleep(random.uniform(0.1, 1.0))
            custom_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
                "Origin": "chrome-extension://lkbnfiajjmbhnfledhphioinpickokdi"
            }
            async with proxy_connect(uri, proxy=proxy, ssl=ssl_context, extra_headers=custom_headers) as websocket:
                async def send_ping():
                    while True:
                        ping_message = json.dumps(
                            {"id": str(uuid.uuid4()), "version": "1.0.0", "action": "PING", "data": {}}
                        )
                        logger.debug(f"Sending ping: {ping_message}")
                        await websocket.send(ping_message)
                        await asyncio.sleep(60)

                send_ping_task = asyncio.create_task(send_ping())
                
                try:
                    while True:
                        response = await websocket.recv()
                        message = json.loads(response)
                        logger.info(f"Received message: {message}")

                        if message.get("action") == "AUTH":
                            auth_response = {
                                "id": message["id"],
                                "origin_action": "AUTH",
                                "result": {
                                    "browser_id": device_id,
                                    "user_id": user_id,
                                    "user_agent": custom_headers["User-Agent"],
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

                except asyncio.CancelledError:
                    send_ping_task.cancel()
                    break
                except Exception as e:
                    logger.error(f"Connection error on proxy {proxy_url}: {str(e)}")
                finally:
                    send_ping_task.cancel()

        except Exception as e:
            logger.error(f"Connection error on proxy {proxy_url}: {e}")
            if "Device creation limit exceeded" in str(e):
                logger.info(f"Removing faulty proxy: {proxy_url}")
                await log_and_remove_broken_proxy(proxy_url)
                return None

async def remove_proxy_from_list(proxy):
    async with aiofiles.open(PROXY_FILE, "r+") as file:
        lines = await file.readlines()
        await file.seek(0)
        await file.writelines(line for line in lines if line.strip() != proxy)
        await file.truncate()

async def remove_proxy_from_assigments(proxy):
    assignments = await load_assignments()
    
    for user, proxies in assignments.items():
        if proxy in proxies:
            proxies.remove(proxy)
            if not proxies:
                del assignments[user]
    
    await save_assignments(assignments)

async def log_and_remove_broken_proxy(proxy_url):
    await remove_proxy_from_list(proxy_url)
    await remove_proxy_from_assigments(proxy_url)

    async with aiofiles.open("logs.txt", "a") as log_file:
        log_message = f"{time.strftime('%Y-%m-%d %H:%M:%S')} - Proxy broken: {proxy_url}\n"
        await log_file.write(log_message)

async def validate_files():
    if not os.path.exists(USER_FILE) or os.path.getsize(USER_FILE) == 0:
        logger.error(f"File {USER_FILE} does not exist or is empty")
        sys.exit(1)
        
    if not os.path.exists(PROXY_FILE) or os.path.getsize(PROXY_FILE) == 0:
        logger.error(f"File {PROXY_FILE} does not exist or is empty")
        sys.exit(1)

async def main():
    await validate_files()

    with open(USER_FILE, 'r') as file:
        users = file.read().splitlines()
        
    with open(PROXY_FILE, 'r') as file:
        all_proxies = file.read().splitlines()

    assignments = await assign_proxies_to_accounts(users, all_proxies)
    
    tasks = []
    for user, proxies in assignments.items():
        for proxy in proxies:
            tasks.append(asyncio.create_task(connect_to_wss(proxy, user)))

    await asyncio.gather(*tasks)

if __name__ == '__main__':
    asyncio.run(main())
