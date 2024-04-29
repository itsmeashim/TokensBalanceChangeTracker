import asyncio
import logging
import os
from traceback import format_exception

import aiohttp
import pymongo
from dotenv import load_dotenv
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
request_semaphore = asyncio.Semaphore(10)

load_dotenv(override=True)

webhook_url = os.getenv("WEBHOOK_URL")
results_webhook_url = os.getenv("RESULTS_WEBHOOK_URL")
MORALIS_API = os.getenv("MORALIS_API")
MONGO_SESSION = os.getenv("MONGO_SESSION")
SOL_API = os.getenv("SOL_API")
print(SOL_API)

# MongoDB setup
mongo_client = pymongo.MongoClient(MONGO_SESSION)
db = mongo_client["tokenchange_alerts"]
wallets_collection = db["wallets"]
alerted_coins = db["alerted_coins"]

# Asynchronous Discord webhook function
async def send_message_to_discord(message, webhook_url=webhook_url):
    try:
        async with aiohttp.ClientSession() as session:
            data = {
                "embeds": [{
                    "description": message,
                    "color": 0x3498DB  # Blue color for informational message
                }]
            }
            async with session.post(webhook_url, json=data) as response:
                if response.status != 204:
                    logger.error(f"Request to Discord webhook failed with status code {response.status}")
    except Exception as e:
        logger.error(f"Error in sending message to Discord: {e}")
        await send_exception_to_discord(e)

# Asynchronous exception handling function
async def send_exception_to_discord(exception):
    try:
        if not isinstance(exception, Exception):
            logger.error("Parameter must be an Exception.")
            return
        exception_message = "".join(format_exception(type(exception), exception, exception.__traceback__))
        data = {
            "embeds": [{
                "title": "Exception Occurred",
                "description": f"```{exception_message}```",
                "color": 0xFF0000  # Red color for error
            }]
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=data) as response:
                if response.status != 204:
                    logger.error(f"Request to Discord webhook failed with status code {response.status}")
    except Exception as e:
        logger.error(f"Error in sending exception to Discord: {e}")

async def get_last_transaction(address):
    headers = {"Content-Type": "application/json"}
    data = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [address, {"limit": 1}]
    }

    await request_semaphore.acquire()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(SOL_API, headers=headers, json=data) as response:
                response_json = await response.json()
                # logger.info(response_json)
                return response_json.get("result", [])[0].get("signature", "")
    except Exception as e:
        logger.error(f"Error in getting transaction: {e}")
        return ""
    finally:
        request_semaphore.release()

    # result = response_json.get("result", [])
    # if not result:
    #     return ""

    # txnHash = result[0].get("signature", "")

    # return txnHash

async def find_values(json_input, key):
    if isinstance(json_input, dict):
        for k, v in json_input.items():
            if k == key:
                yield v
            elif isinstance(v, (dict, list)):
                async for item in find_values(v, key):
                    yield item
    elif isinstance(json_input, list):
        for item in json_input:
            async for found in find_values(item, key):
                yield found

async def get_Hash_Token(contract):
    tokens = set()
    headers = {"Content-Type": "application/json"}
    data = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [
            contract,
            {
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0
            }
        ]
    }

    await request_semaphore.acquire()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(SOL_API, headers=headers, json=data) as response:
                response_json = await response.json()
    except Exception as e:
        logger.error(f"Error in getting transaction: {e}")
        await send_exception_to_discord(e)
        return ""
    finally:
        request_semaphore.release()

    async for result in find_values(response_json, "mint"):
        if not result == "So11111111111111111111111111111111111111112":
            tokens.add(result)

    return tokens

async def get_name_symbol(token_address):
    try:
        headers = {
            "Accept": "application/json",
            "X-API-Key": MORALIS_API
        }
        url = f"https://solana-gateway.moralis.io/token/mainnet/{token_address}/metadata"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    return '', ''

                response_json = await response.json()
                name = response_json.get('name', '')
                symbol = response_json.get('symbol', '')

                logger.info(f"Name: {name}, Symbol: {symbol}")
                logger.info(response_json)

                return name, symbol
    except Exception as e:
        logger.error(f"Error in getting name and symbol: {e}")
        await send_exception_to_discord(e)
    return "", ""

async def process_transfers(txnHash, wallet):
    try:
        wallet_hash = wallet['hash']
        wallet_name = wallet.get('name', wallet_hash)
        txn_hash = txnHash

        logger.info(f"Processing transactions for wallet {wallet_name} with hash {wallet_hash} and txn hash {txn_hash}")

        tokens = await get_Hash_Token(txn_hash)
        logger.info(f"Tokens {wallet_name}: {tokens}")

        if not tokens:
            return

        message = ""
        for token in tokens:
            token_address = token

            # Check if this token for the wallet has been alerted
            if alerted_coins.find_one({"wallet_hash": wallet_hash, "token_address": token_address}):
                logger.info(f"Token {token_address} already alerted for wallet {wallet_name}")
                # await send_message_to_discord(f"Token {token_address} already alerted for wallet {wallet_name}", webhook_url)
                continue  # Skip this token

            name, symbol = await get_name_symbol(token_address)
            if not name or not symbol:
                logger.warning(f"Name or symbol not found for token {token_address} in wallet {wallet_name}")
                # await send_message_to_discord(f"Name or symbol not found for token {token_address} in wallet {wallet_name}", webhook_url)
                continue

            # Update the message and the alerted_coins collection
            message += f"[{token_address}](https://solscan.io/account/{token_address}) `{symbol}`\n"
            alerted_coins.insert_one({"wallet_hash": wallet_hash, "token_address": token_address})

        if message:
            message = f"New transactions for wallet [{wallet_name}](https://birdeye.so/profile/{wallet_hash}):\n-------------------------------------------\n" + message
            await send_message_to_discord(message + f"Hash: {txn_hash}", webhook_url)
            await send_message_to_discord(message, results_webhook_url)
        else:
            logger.info(f"No new transactions to alert for {wallet_name}")
    except Exception as e:
        logger.error(f"Error: {e}")
        await send_exception_to_discord(e)

async def main():
    try:
        start_time = time.time()
        # wallets = list(wallets_collection.find())
        # logger.info(wallets)
        # for wallet in wallets:
        #     wallet_hash = wallet['hash']
        #     wallet_name = wallet.get('name', wallet_hash)
        #     txnHash = await get_last_transaction(wallet_hash)
        #     if txnHash == -1:
        #         logger.warning(f"Error on Request for wallet {wallet_name}")
        #         continue  # Proceed to the next wallet hash
        #     await process_transfers(txnHash, wallet)
        #     # await asyncio.sleep(0.2)

        wallets = list(wallets_collection.find())
        tasks = [process_wallet(wallet) for wallet in wallets]
        await asyncio.gather(*tasks)

        logger.info(f"Total time taken: {time.time() - start_time}")
    except Exception as e:
        logger.error(f"Error: {e}")
        await send_exception_to_discord(e)

async def process_wallet(wallet):
    txnHash = await get_last_transaction(wallet['hash'])
    if txnHash:
        await process_transfers(txnHash, wallet)

async def schedule_main():
    try:
        while True:
            await main()
            await asyncio.sleep(30)
    except Exception as e:
        logger.error(f"Error: {e}")
        await send_exception_to_discord(e)
        ## Running the event loop

loop = asyncio.get_event_loop()
try:
    loop.run_until_complete(schedule_main())
except KeyboardInterrupt:
    pass
finally:
    loop.close()