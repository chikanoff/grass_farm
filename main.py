import asyncio
import random
import json
import time
from loguru import logger
import aiofiles
import os
import sys
from src.connection import GrassConnection

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
            connector = GrassConnection(proxy, user)
            tasks.append(asyncio.create_task(connector.connect()))

    await asyncio.gather(*tasks)

if __name__ == '__main__':
    asyncio.run(main())
