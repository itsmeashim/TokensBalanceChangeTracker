import requests
import os
import time
import asyncio
from traceback import format_exception
import json
import pymongo
import requests
from dotenv import load_dotenv

load_dotenv()

webhook_url = os.getenv("WEBHOOK_URL")
results_webhook_url = os.getenv("RESULTS_WEBHOOK_URL")
MORALIS_API = os.getenv("MORALIS_API")
MONGO_SESSION = os.getenv("MONGO_SESSION")

# MongoDB setup
mongo_client = pymongo.MongoClient(MONGO_SESSION)
db = mongo_client["tokenchange_alerts"]
wallets_collection = db["wallets"]
alerted_coins = db["alerted_coins"]

# Function to send messages to Discord
def send_message_to_discord(message, webhook_url=webhook_url):
    data = {
        "embeds": [{
            "description": message,
            "color": 0x3498DB  # Blue color for informational message
        }]
    }
    response = requests.post(webhook_url, json=data)
    if response.status_code != 204:
        print(f"Request to Discord webhook failed with status code {response.status_code}")

# Function to send exceptions to Discord
def send_exception_to_discord(exception):
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
        print(response.json())

# Function to get transfers for a specific wallet hash
def get_transfers(wallet):
    time_now = int(time.time())
    time_ago = int(time_now - 800)
    current_page = 1
    results = []

    wallet_hash = wallet['hash']
    
    url = f"https://api.solana.fm/v0/accounts/{wallet_hash}/transfers?utcFrom={str(time_ago)}&utcTo={str(time_now)}&page={str(current_page)}"
    print(url)
    try:
        response = requests.get(url).json()
    except Exception as e:
        print(f"Error: {e}")
        send_exception_to_discord(e)
        return -1
    
    if 'results' in response:
        current_result = response["results"]
        results += current_result

    return results

def process_transfers(results, wallet):
    wallet_hash = wallet['hash']
    wallet_name = wallet.get('name', wallet_hash)
    message = ""
    txn_hash = ""
    
    for elem in results:
        txn_hash = elem['transactionHash']
        message = ""
        for data in elem.get('data', []):
            if data.get('token', ""):
                token_address = data['token']

                # Check if this token for the wallet has been alerted
                if alerted_coins.find_one({"wallet_hash": wallet_hash, "token_address": token_address}):
                    continue  # Skip this token

                name, symbol = get_name_symbol(token_address)
                if not name or not symbol:
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

def get_name_symbol(token_address):
    try:
        headers = {
            "Accept": "application/json",
            "X-API-Key": MORALIS_API
        }
        url = f"https://solana-gateway.moralis.io/token/mainnet/{token_address}/metadata"
        response = requests.request("GET", url, headers=headers)
        print(response.status_code)
        print(response.json())
        
        if response.status_code != 200:
            return '', ''
        
        response = response.json()
        name = response.get('name', '')
        symbol = response.get('symbol', '')

        print(name, symbol)

        return name, symbol
    except Exception as e:
        send_exception_to_discord(e)
    return "", ""

# Coroutine to process each wallet
async def my_coroutine():
    wallets = list(wallets_collection.find())
    print(wallets)
    for wallet in wallets:
        wallet_hash = wallet['hash']
        wallet_name = wallet['name']
        results = get_transfers(wallet)
        if results == -1:
            print(f"Error on Request for wallet {wallet_name}")
            continue  # Proceed to the next wallet hash

        process_transfers(results, wallet)
        await asyncio.sleep(1)

# Coroutine to schedule the execution
async def schedule_coroutine():
    try:
        while True:
            send_message_to_discord("Processing new one")
            await my_coroutine()
            await asyncio.sleep(60)
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