import asyncio
import os
import json
from traceback import format_exception
import pymongo
import aiohttp
from dotenv import load_dotenv

load_dotenv()

# Environment variables
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
RESULTS_WEBHOOK_URL = os.getenv("RESULTS_WEBHOOK_URL", "")
MORALIS_API = os.getenv("MORALIS_API", "")
MONGO_SESSION = os.getenv("MONGO_SESSION", "")
SOL_API = os.getenv("SOL_API", "")

# MongoDB setup
mongo_client = pymongo.MongoClient(MONGO_SESSION)
db = mongo_client["tokenchange_alerts"]
wallets_collection = db["wallets"]
alerted_coins = db["alerted_coins4"]

async def send_message_to_discord(session, message, webhook_url):
    """Sends messages to Discord."""
    data = {
        "embeds": [{
            "description": message,
            "color": 0x3498DB  # Blue color for informational message
        }]
    }
    try:
        async with session.post(webhook_url, json=data) as response:
            if response.status != 204:
                print(f"Request to Discord webhook failed with status code {response.status}")
    except Exception as e:
        print(f"Failed to send message to Discord: {e}")

async def send_exception_to_discord(session, exception):
    """Sends exceptions to Discord."""
    exception_message = "".join(format_exception(type(exception), exception, exception.__traceback__))
    data = {
        "embeds": [{
            "title": "Exception Occurred",
            "description": f"```{exception_message}```",
            "color": 0xFF0000  # Red color for error
        }]
    }
    await send_message_to_discord(session, data, WEBHOOK_URL)

async def get_last_transaction(session, address):
    """Retrieves the last transaction for a given address."""
    headers = {"Content-Type": "application/json"}
    data = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [address, {"limit": 1}]
    }

    try:
        async with session.post(SOL_API, headers=headers, json=data) as response:
            response_json = await response.json()
            result = response_json.get("result", [])
            if not result:
                return ""
            txn_hash = result[0].get("signature", "")
            return txn_hash
    except Exception as e:
        print(f"Error in getting transaction: {e}")
        return ""

async def get_Hash_Token(session, contract):
    """Retrieves tokens from a transaction hash."""
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

    try:
        async with session.post(SOL_API, headers=headers, json=data) as response:
            response_json = await response.json()
            results = list(find_values(response_json, "mint"))
            for result in results:
                if result != "So11111111111111111111111111111111111111112":
                    tokens.add(result)
        return tokens
    except Exception as e:
        print(f"Error in getting transaction details: {e}")
        await send_exception_to_discord(session, e)
        return tokens

def find_values(json_input, key):
    """Yields all values for a specified key in a JSON structure."""
    if isinstance(json_input, dict):
        for k, v in json_input.items():
            if k == key:
                yield v
            elif isinstance(v, (dict, list)):
                yield from find_values(v, key)
    elif isinstance(json_input, list):
        for item in json_input:
            yield from find_values(item, key)

async def process_transfers(session, txn_hash, wallet):
    """Processes transfers for a given transaction hash and wallet."""
    wallet_hash = wallet['hash']
    wallet_name = wallet.get('name', wallet_hash)

    print(f"Processing transactions for wallet {wallet_name} with hash {wallet_hash} and txn hash {txn_hash}")

    tokens = await get_Hash_Token(session, txn_hash)
    if not tokens:
        return

    message = ""
    for token in tokens:
        token_address = token

        # Check if this token for the wallet has been alerted
        if alerted_coins.find_one({"wallet_hash": wallet_hash, "token_address": token_address}):
            continue  # Skip this token

        name, symbol = await get_name_symbol(session, token_address)
        if not name or not symbol:
            continue

        print(name, symbol)

        # Update the message and the alerted_coins collection
        message += f"[{token_address}](https://solscan.io/account/{token_address}) `{symbol}`\n"
        alerted_coins.insert_one({"wallet_hash": wallet_hash, "token_address": token_address})

    if message:
        message = f"New transactions for wallet [{wallet_name}](https://birdeye.so/profile/{wallet_hash}):\n-------------------------------------------\n" + message
        await send_message_to_discord(session, message, RESULTS_WEBHOOK_URL)

    if not message:
        print("No new transactions to alert for", wallet_name)

async def get_name_symbol(session, token_address):
    """Gets the name and symbol of a token given its address."""
    try:
        headers = {
            "Accept": "application/json",
            "X-API-Key": MORALIS_API
        }
        url = f"https://solana-gateway.moralis.io/token/mainnet/{token_address}/metadata"
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                return '', ''
            
            response_json = await response.json()
            name = response_json.get('name', '')
            symbol = response_json.get('symbol', '')

            return name, symbol
    except Exception as e:
        await send_exception_to_discord(session, e)
        return "", ""

async def my_coroutine(session):
    """Coroutine to process each wallet."""
    wallets = list(wallets_collection.find())
    for wallet in wallets:
        wallet_hash = wallet['hash']
        txn_hash = await get_last_transaction(session, wallet_hash)
        if not txn_hash:
            print(f"No transactions found for wallet {wallet['name']}")
            continue
        await process_transfers(session, txn_hash, wallet)
        await asyncio.sleep(0.1)  # Throttle requests

async def schedule_coroutine():
    """Schedules the execution."""
    async with aiohttp.ClientSession() as session:
        try:
            while True:
                print("Starting to process wallets...")
                await my_coroutine(session)
                print("Waiting for the next cycle...")
                await asyncio.sleep(30)  # Interval between each cycle
        except asyncio.CancelledError:
            print("Coroutine was cancelled")
        except Exception as e:
            print(f"Unhandled error: {e}")
            await send_exception_to_discord(session, e)

if __name__ == "__main__":
    try:
        asyncio.run(schedule_coroutine())
    except KeyboardInterrupt:
        print("Process interrupted by the user.")
    except Exception as e:
        print(f"An error occurred: {e}")
