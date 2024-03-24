from pymongo import MongoClient
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import io

load_dotenv()

# Replace 'MONGO_SESSION' with your actual MongoDB connection string
MONGO_SESSION = os.getenv("MONGO_SESSION")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

mongo_client = MongoClient(MONGO_SESSION)
db = mongo_client["tokenchange_alerts"]
wallets_collection = db["wallets"]

# Discord bot setup
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='*', intents=intents)

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')

# Discord command to add multiple wallets
@bot.command()
async def add(ctx, *, wallets_data: str):
    """
    Accepts wallets in the format: hash1 name1, hash2 name2, ...
    Example: /add 0x123... abc, 0x456... def
    """
    wallets_data = wallets_data.replace(',', '\n').replace(';', '\n')
    wallets_data = wallets_data.split('\n')
    added_count = 0
    duplicate_count = 0
    message = ""

    for wallet_data in wallets_data:
        try:
            hash, name = wallet_data.strip().split(' ', 1)
        except ValueError:
            message += f"Error parsing wallet data {wallet_data.strip()}. Please use the format: hash name\n"
            continue

        if wallets_collection.count_documents({"hash": hash}) > 0:
            duplicate_count += 1
            message += f"Wallet with hash {hash} already exists. Skipping...\n"
            continue

        wallet = {"hash": hash, "name": name}
        wallets_collection.insert_one(wallet)
        message += f"Added wallet with hash {hash}\n"
        added_count += 1

    summary_message = f"Operation summary:\n- Added wallets: {added_count}\n- Duplicates skipped: {duplicate_count}"
    if message:
        summary_message += f"\n\nDetails:\n{message}"
    await ctx.send(summary_message)

# Discord command to remove a wallet
@bot.command()
async def remove(ctx, hash: str):    
    result = wallets_collection.delete_one({"hash": hash})
    if result.deleted_count > 0:
        await ctx.send(f"Removed wallet with hash {hash}")
    else:
        await ctx.send("Wallet not found.")

# Discord command to list all wallets
@bot.command()
async def list_wallets(ctx):
    wallets = wallets_collection.find({})
    response = "Wallets:\n"
    for wallet in wallets:
        response += f"{wallet['name']} ({wallet['hash']})\n"
    if not wallets.retrieved:
        response = "No wallets found."

    max_length = 2000  # Discord's max message length
    if len(response) <= max_length:
        await ctx.send(response)
    else:
        # If the message is too long, send it as a file
        message_bytes = response.encode('utf-8')  # Encoding to bytes
        message_file = io.BytesIO(message_bytes)  # Creating a BytesIO object from the bytes
        message_file.seek(0)  # Seek to the start of the file
        await ctx.send(file=discord.File(fp=message_file, filename="words_and_descriptions_list.txt"))

# Enter your bot's token here
bot.run(DISCORD_BOT_TOKEN)
