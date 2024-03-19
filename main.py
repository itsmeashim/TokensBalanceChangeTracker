import requests
import os
import time
import asyncio
from traceback import format_exception
import json
import pymongo
import discord
from discord.ext import commands
import requests
from dotenv import load_dotenv


load_dotenv()

webhook_url = os.getenv("WEBHOOK_URL")
MORALIS_API = os.getenv("MORALIS_API")
MONGO_SESSION = os.getenv("MONGO_SESSION")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# MongoDB setup
mongo_client = pymongo.MongoClient(MONGO_SESSION)
db = mongo_client["tokenchange_alerts"]
wallets_collection = db["wallets"]

# Discord bot setup
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='/', intents=intents)

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    # Schedule the coroutine here
    asyncio.create_task(schedule_coroutine())

# Discord command to add a new wallet
@bot.command()
async def add(ctx, hash: str, name: str):
    if not hash or not name:
        await ctx.send("Invalid parameters")
        return
    wallet = {"hash": hash, "name": name}
    wallets_collection.insert_one(wallet)
    await ctx.send(f"Added wallet {name} ({hash})")

# Discord command to remove a wallet
@bot.command()
async def remove(ctx, hash: str):
    wallets_collection.delete_one({"hash": hash})
    await ctx.send(f"Removed wallet with hash {hash}")

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
                    message = f"Transaction: {txnHash} - {name} - {symbol}"
                    send_message_to_discord(message)           

        if not message:
            print("No new transactions found")
            send_message_to_discord(f"No new transactions found for wallet [{wallet_name}](https://solscan.io/account/{wallet_hash})")
        # send_message_to_discord(message)
        

    except Exception as e:
        print(f"Error on process txns: {e}")
        send_exception_to_discord(e)

def get_name_symbol(token_address):
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
        await asyncio.sleep(1)

# Adjusted to directly start the bot and incorporate the scheduling within its loop
async def schedule_coroutine():
    await bot.wait_until_ready()
    while not bot.is_closed():
        send_message_to_discord("Processing new one")
        await my_coroutine()
        await asyncio.sleep(60)

bot.run(DISCORD_BOT_TOKEN)
