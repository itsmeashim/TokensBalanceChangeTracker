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
MORALIS_API = os.getenv("MORALIS_API")
MONGO_SESSION = os.getenv("MONGO_SESSION")

# MongoDB setup
mongo_client = pymongo.MongoClient(MONGO_SESSION)
db = mongo_client["tokenchange_alerts"]
wallets_collection = db["wallets"]

# Function to send messages to Discord
def send_message_to_discord(message):
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

# Function to get transfers for a specific wallet hash
def get_transfers(wallet):
    time_now = int(time.time())
    time_ago = int(time_now - 80)
    current_page = 1
    results = []

    wallet_hash = wallet['hash']
    while True:
        url = f"https://api.solana.fm/v0/accounts/{wallet_hash}/transfers?utcFrom={str(time_ago)}&utcTo={str(time_now)}&page={str(current_page)}"
        print(url)
        try:
            response = requests.get(url).json()
        except Exception as e:
            print(f"Error: {e}")
            send_exception_to_discord(e)
            return -1
        
        try:
            total_page = 1
            if 'pagination' in response and 'totalPages' in response["pagination"]:
                total_page = response["pagination"]["totalPages"] if response["pagination"]["totalPages"] else 1
                print(total_page)
        except Exception as e:
            print(f"Error: {e}")
            send_exception_to_discord(e)
            total_page = 1
        if 'results' in response:
            current_result = response["results"]
            results += current_result
        current_page += 1
        if current_page > total_page:
            break

    return results[::-1]

# Function to process transfers
def process_transfers(result: list, wallet):
    try:
        wallet_hash = wallet['hash']
        wallet_name = wallet['name']
        print(f"Processing transfers for wallet {wallet_name}...")
        send_message_to_discord(f"Processing transfers for wallet {wallet_name}...")

        message = ""

        for elem in result:
            txnHash = elem['transactionHash']
            datas = elem['data']
            added = False
            for data in datas:
                action = data['action']
                token = data['token']

                if token and action == "transferChecked":
                    name, symbol = get_name_symbol(token)
                    if not name or not symbol:
                        continue
                    message += f"Transaction: {txnHash} - {name} - {symbol}"           

        if not message:
            print("No new transactions found")
            send_message_to_discord(f"No new transactions found for wallet [{wallet_name}](https://solscan.io/account/{wallet_hash})")
        send_message_to_discord(message)

    except Exception as e:
        print(f"Error on process txns: {e}")
        send_exception_to_discord(e)

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
    for wallet in wallets:
        wallet_hash = wallet['hash']
        wallet_name = wallet['name']
        results = get_transfers(wallet)
        if results == -1:
            print(f"Error on Request for wallet {wallet_name}")
            continue  # Proceed to the next wallet hash

        process_transfers(results, wallet)
        await asyncio.sleep(0.2)

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