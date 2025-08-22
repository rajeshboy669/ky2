import logging
import os
import re
import asyncio
import aiohttp
import requests
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from pymongo import MongoClient
from pymongo.uri_parser import parse_uri

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app for health check
app = Flask(__name__)

@app.route('/health', methods=['GET'])
def health_check():
    try:
        return 'OK', 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return 'Service Unavailable', 503

# Read environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7613950530:AAEUaQ2Qs8PJYhud4G2eNmG-ZdDJ8xO9JOM")
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb+srv://aaroha:aaroha@cluster0.8z6ob17.mongodb.net/Cluster0?retryWrites=true&w=majority&appName=Cluster0")
ADLINKFLY_API_URL = "https://linxshort.me/api"

# Validate environment variables
if not TELEGRAM_BOT_TOKEN or not MONGODB_URI:
    raise ValueError("Missing required environment variables.")

# Parse MongoDB URI to extract database name
parsed_uri = parse_uri(MONGODB_URI)
db_name = parsed_uri.get("database")
if not db_name:
    raise ValueError("Database name not found in MONGODB_URI.")

# Initialize MongoDB client and database
client = MongoClient(MONGODB_URI)
db = client[db_name]
users_collection = db["users"]

# Regular expression to find URLs in text
URL_REGEX = re.compile(r'https?://[^\s]+')

async def shorten_link(link: str, api_key: str) -> str:
    try:
        params = {"api": api_key, "url": link}
        async with aiohttp.ClientSession() as session:
            async with session.get(ADLINKFLY_API_URL, params=params) as response:
                if response.status == 200:
                    try:
                        data = await response.json()
                        return data.get("shortenedUrl", link)
                    except Exception:
                        return link
        return link
    except Exception as e:
        logger.error(f"Error shortening link: {e}")
        return link

async def process_text(text: str, api_key: str) -> str:
    mapping = []
    async def replace_link(match):
        link = match.group(0)
        if "https://t.me/" in link:
            return link  # Skip Telegram links
        short = await shorten_link(link, api_key)
        mapping.append((link, short))
        return short
    
    tasks = [replace_link(match) for match in URL_REGEX.finditer(text)]
    await asyncio.gather(*tasks)
    
    # Build summary
    summary = text
    if mapping:
        summary += "\n\n🔗 Shortened Links:\n"
        for orig, short in mapping:
            summary += f"{orig} → {short}\n"
    return summary

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_name = update.message.from_user.full_name
    keyboard = [[InlineKeyboardButton("Sign Up", url="https://linxshort.me/auth/signup")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_message = (
        f"Hello {user_name}! 👋😃\n\n"
        "🚀 Welcome to Linxshort BOT - Your Personal URL Shortener Bot. 🌐\n\n"
        "Send me a link, and I'll shorten it for you and track your earnings! 💰\n\n"
        "⚡️ Support: @Linxshort"
    )
    await update.message.reply_text(welcome_message, reply_markup=reply_markup)

async def set_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        user_id = update.message.from_user.id
        api_key = context.args[0] if context.args else None
        if not api_key:
            await update.message.reply_text("Please provide an API key. Example: /setapi <API_KEY>")
            return
        users_collection.update_one({"user_id": user_id}, {"$set": {"api_key": api_key}}, upsert=True)
        context.user_data["api_key"] = api_key
        await update.message.reply_text("API key set successfully!")
    except Exception as e:
        logger.error(f"Error setting API key: {e}")
        await update.message.reply_text("An error occurred. Please try again.")

async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    users_collection.delete_one({"user_id": user_id})
    context.user_data.pop("api_key", None)
    await update.message.reply_text("You have been logged out.")

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[InlineKeyboardButton("24/7 support", url="https://t.me/Linxshort_support")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    help_text = (
        "Commands:\n"
        "/start - Start the bot\n"
        "/setapi <API_KEY> - Set your API key\n"
        "/logout - Log out\n"
        "/balance - View your balance and stats\n"
        "/help - Show this help message\n"
        "/features - Show bot features\n"
        "Send a message with URLs to shorten them automatically."
    )
    await update.message.reply_text(help_text, reply_markup=reply_markup)

async def features(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    features_text = (
        "Bot Features:\n"
        "1. URL Shortening\n"
        "2. Bulk URL Processing\n"
        "3. Telegram link exclusion\n"
        "4. Easy API setup with /setapi\n"
        "5. Logout with /logout\n"
        "6. Balance & stats with /balance"
    )
    await update.message.reply_text(features_text)

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    user_data = users_collection.find_one({"user_id": user_id})
    if not user_data or "api_key" not in user_data:
        await update.message.reply_text("Please set your API key using /setapi first.")
        return
    api_key = user_data["api_key"]
    api_url = f"https://linxshort.me/balance-api.php?api={api_key}"
    try:
        resp = requests.get(api_url, timeout=10).json()
        if resp["status"] == "success":
            msg = (
                f"👤 Username: {resp['username']}\n"
                f"💰 Balance: {resp['balance']}\n"
                f"✅ Withdrawn: {resp['withdrawn']}\n"
                f"🔗 Total Links: {resp['total_links']}\n"
                f"💸 Referrals: {resp['referrals']}"
            )
        else:
            msg = f"❌ Error: {resp.get('message', 'Unknown error')}"
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to fetch balance: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        user_id = update.message.from_user.id
        api_key = context.user_data.get("api_key")
        if not api_key:
            user_data = users_collection.find_one({"user_id": user_id})
            api_key = user_data.get("api_key") if user_data else None
            if api_key:
                context.user_data["api_key"] = api_key
            else:
                await update.message.reply_text("Please set your Linxshort API key using /setapi.")
                return

        text = update.message.text or update.message.caption
        if text:
            processed_text = await process_text(text, api_key)
            if update.message.text:
                await update.message.reply_text(processed_text)
            elif update.message.caption:
                await update.message.reply_photo(update.message.photo[-1].file_id, caption=processed_text)
    except Exception as e:
        logger.error(f"Error handling message: {e}")
        await update.message.reply_text("An error occurred. Please try again.")

# Run Flask health check in separate thread
Thread(target=app.run, kwargs={'host': '0.0.0.0', 'port': 8000, 'debug': False}).start()

def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setapi", set_api_key))
    application.add_handler(CommandHandler("logout", logout))
    application.add_handler(CommandHandler("help", help))
    application.add_handler(CommandHandler("features", features))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))
    application.run_polling()

if __name__ == '__main__':
    main()
