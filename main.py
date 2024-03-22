import requests
import os
import time
import asyncio
from traceback import format_exception
import json
import pymongo
import requests
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO)

load_dotenv()

webhook_url = os.getenv("WEBHOOK_URL")
results_webhook_url = os.getenv("RESULTS_WEBHOOK_URL")
MORALIS_API = os.getenv("MORALIS_API")
MONGO_SESSION = os.getenv("MONGO_SESSION")
SOL_API = os.getenv("SOL_API")

# MongoDB setup
mongo_client = pymongo.MongoClient(MONGO_SESSION)
db = mongo_client["tokenchange_alerts"]
wallets_collection = db["wallets"]
alerted_coins = db["alerted_coins"]

# Function to send messages to Discord
def send_message_to_discord(message, webhook_url=webhook_url):
    try:
        data = {
            "embeds": [{
                "description": message,
                "color": 0x3498DB  # Blue color for informational message
            }]
        }
        response = requests.post(webhook_url, json=data)
        if response.status_code != 204:
            print(f"Request to Discord webhook failed with status code {response.status_code}")
    except:
        print("Error in sending message to Discord")

# Function to send exceptions to Discord
def send_exception_to_discord(exception):
    try:
        if not isinstance(exception, Exception):
            print("Parameter must be an Exception.")
            return
        exception_message = "".join(format_exception(type(exception), exception, exception.__traceback__))
        data = {
            "embeds": [{
                "title": "Exception Occurred",
                "description": f"```{exception_message}```",
                "color": 0xFF0000  # Red color for error
            }]
        }
        response = requests.post(webhook_url, json=data)
        if response.status_code != 204:
            print(f"Request to Discord webhook failed with status code {response.status_code}")
    except:
        print("Error in sending exception to Discord")

def get_last_transaction(address):
    headers = {"Content-Type": "application/json"}
    data = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [address, {"limit": 1}]
    }

    try:
        response = requests.post(SOL_API, headers=headers, data=json.dumps(data)).json()
        print(response)
    except Exception as e:
        print("Error in getting transaction ", e)
        return ""

    result = response.get("result", [])
    if not result:
        return ""

    txnHash = result[0].get("signature", "")

    return txnHash

def find_values(json_input, key):
    if isinstance(json_input, dict):
        for k, v in json_input.items():
            if k == key:
                yield v
            elif isinstance(v, (dict, list)):
                yield from find_values(v, key)
    elif isinstance(json_input, list):
        for item in json_input:
            yield from find_values(item, key)

def get_Hash_Token(contract):
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
        response = requests.post(SOL_API, headers=headers, data=json.dumps(data)).json()
    except Exception as e:
        print("Error in getting transaction ", e)
        send_exception_to_discord(e)
        return ""
    
    results = find_values(response, "mint")

    for result in results:
        if not result == "So11111111111111111111111111111111111111112":
            tokens.add(result)
            
    return tokens
    
def process_transfers(txnHash, wallet):
    try:
        wallet_hash = wallet['hash']
        wallet_name = wallet.get('name', wallet_hash)
        txn_hash = txnHash

        print(f"Processing transactions for wallet {wallet_name} with hash {wallet_hash} and txn hash {txn_hash}")

        tokens = get_Hash_Token(txn_hash)
        print(f"Tokens: {tokens}")

        if not tokens:
            # send_message_to_discord(f"No tokens found for wallet {wallet_name}")
            return

        send_message_to_discord(f"Tokens: {tokens} for wallet {wallet_name}")

        message = ""
        for token in tokens:
            token_address = token

            # Check if this token for the wallet has been alerted
            if alerted_coins.find_one({"wallet_hash": wallet_hash, "token_address": token_address}):
                send_message_to_discord(f"Token {token_address} already alerted for wallet {wallet_name}")
                continue  # Skip this token

            name, symbol = get_name_symbol(token_address)
            if not name or not symbol:
                send_message_to_discord(f"Name or symbol not found for token {token_address} in wallet {wallet_name}")
                continue

            # Update the message and the alerted_coins collection
            message += f"[{token_address}](https://solscan.io/account/{token_address}) `{symbol}`\n"
            alerted_coins.insert_one({"wallet_hash": wallet_hash, "token_address": token_address})

            if message:
                message = f"New transactions for wallet [{wallet_name}](https://birdeye.so/profile/{wallet_hash}):\n-------------------------------------------\n" + message
                send_message_to_discord(message  + f"Hash: {txn_hash}", webhook_url)
                send_message_to_discord(message, results_webhook_url)

        if not message:
            print("No new transactions to alert for", wallet_name)
    except Exception as e:
        send_exception_to_discord(e)
        print(f"Error: {e}")

def get_name_symbol(token_address):
    try:
        headers = {
            "Accept": "application/json",
            "X-API-Key": MORALIS_API
        }
        url = f"https://solana-gateway.moralis.io/token/mainnet/{token_address}/metadata"
        response = requests.request("GET", url, headers=headers)
        
        if response.status_code != 200:
            return '', ''
        
        response = response.json()
        name = response.get('name', '')
        symbol = response.get('symbol', '')

        print(name, symbol)
        print(response)

        return name, symbol
    except Exception as e:
        send_exception_to_discord(e)
    return "", ""

# Coroutine to process each wallet
async def my_coroutine():
    try:
        wallets = list(wallets_collection.find())
        print(wallets)
        for wallet in wallets:
            wallet_hash = wallet['hash']
            wallet_name = wallet['name']
            txnHash = get_last_transaction(wallet_hash)
            if txnHash == -1:
                print(f"Error on Request for wallet {wallet_name}")
                continue  # Proceed to the next wallet hash

            process_transfers(txnHash, wallet)
            await asyncio.sleep(1)
    except Exception as e:
        send_exception_to_discord(e)
        print(f"Error: {e}")

# Coroutine to schedule the execution
async def schedule_coroutine():
    try:
        while True:
            # send_message_to_discord("Processing new one")
            await my_coroutine()
            await asyncio.sleep(30)
    except Exception as e:
        print(f"Error: {e}")
        send_exception_to_discord(e)

# Running the event loop
loop = asyncio.get_event_loop()
try:
    loop.run_until_complete(schedule_coroutine())
except KeyboardInterrupt:
    pass
finally:
    loop.close()