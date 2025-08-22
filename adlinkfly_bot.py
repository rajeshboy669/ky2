import logging
import os
import re
import asyncio
import aiohttp
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
BALANCE_API_URL = "https://linxshort.me/balance-api.php"  # Replace with your actual domain

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
                    data = await response.json()
                    return data.get("shortenedUrl", link)
        return link
    except Exception as e:
        logger.error(f"Error shortening link: {e}")
        return link

async def get_balance_info(api_key: str) -> dict:
    try:
        params = {"api": api_key}
        async with aiohttp.ClientSession() as session:
            async with session.get(BALANCE_API_URL, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
        return {"status": "error", "message": "Failed to fetch balance information"}
    except Exception as e:
        logger.error(f"Error fetching balance: {e}")
        return {"status": "error", "message": str(e)}

async def process_text(text: str, api_key: str) -> str:
    async def replace_link(match):
        link = match.group(0)
        if "https://t.me/" in link:
            return link  # Skip Telegram links
        return await shorten_link(link, api_key)
    
    tasks = [replace_link(match) for match in URL_REGEX.finditer(text)]
    shortened_links = await asyncio.gather(*tasks)
    for match, shortened in zip(URL_REGEX.finditer(text), shortened_links):
        text = text.replace(match.group(0), shortened)
    return text

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_name = update.message.from_user.full_name  # Get the user's full name
    
    # Creating an inline button
    keyboard = [[InlineKeyboardButton("Sign Up", url="https://linxshort.me/auth/signup")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_message = (
        f"Hello AA {user_name}! 👋😃\n\n"
        "🚀 Welcome to Linxshort BOT - Your Personal URL Shortener Bot. 🌐\n\n"
        "Just send me a link, and I'll work my magic to shorten it for you. Plus, I'll keep track of your earnings! 💰💼\n\n"
        "Get started now and experience the power of Linxshort BOT. 💪🔗\n\n"
        "⚡️Still Have Doubts?\n"
        "⚡️Want to Report Any Bug?\n"
        "😌Send Here 👉 @Linxshort"
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

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        user_id = update.message.from_user.id
        api_key = context.user_data.get("api_key")
        if not api_key:
            user_data = users_collection.find_one({"user_id": user_id})
            api_key = user_data.get("api_key") if user_data else None
            if api_key:
                context.user_data["api_key"] = api_key
            else:
                await update.message.reply_text("Please set your Linxshort API key using /setapi first.")
                return

        # Show waiting message
        wait_msg = await update.message.reply_text("🔄 Fetching your balance information...")
        
        # Get balance information
        balance_data = await get_balance_info(api_key)
        
        # Delete waiting message
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=wait_msg.message_id)
        
        if balance_data.get("status") == "success":
            # Format the balance information
            balance_text = (
                f"💰 *Balance Information for {balance_data.get('username', 'User')}* 💰\n\n"
                f"👤 User ID: `{balance_data.get('user_id', 'N/A')}`\n"
                f"📧 Email: {balance_data.get('email', 'N/A')}\n\n"
                f"💵 Current Balance: ${balance_data.get('balance', 0):.2f}\n"
                f"🏧 Total Withdrawn: ${balance_data.get('withdrawn', 0):.2f}\n"
                f"👥 Referral Earnings: ${balance_data.get('referrals', 0):.2f}\n"
                f"🔗 Total Links: {balance_data.get('total_links', 0)}\n\n"
                f"🌐 Dashboard: https://linxshort.me/dashboard"
            )
            
            await update.message.reply_text(balance_text, parse_mode="Markdown")
        else:
            error_msg = balance_data.get("message", "Unknown error occurred")
            await update.message.reply_text(f"❌ Error: {error_msg}")
            
    except Exception as e:
        logger.error(f"Error checking balance: {e}")
        await update.message.reply_text("An error occurred while fetching your balance. Please try again.")

async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    users_collection.delete_one({"user_id": user_id})
    context.user_data.pop("api_key", None)
    await update.message.reply_text("You have been logged out.")

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[InlineKeyboardButton("24/7 support", url="https://t.me/Linxshort_support")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    help_text = (
        "Welcome to the Linxshort Bulk Link Shortener Bot!\n\n"
        "Here are the commands you can use:\n"
        "/start - Start the bot and get an introduction.\n"
        "/setapi <API_KEY> - Set your Linxshort API key to start shortening links.\n"
        "/balance - Check your earnings balance and statistics.\n"
        "/logout - Log out from the bot and remove your API key.\n"
        "/help - Get a list of available commands and their explanations.\n"
        "/features - View the features offered by the bot.\n"
        "\nTo shorten links, simply send a message with a URL, and the bot will handle the rest."
    )

    await update.message.reply_text(help_text, reply_markup=reply_markup)

async def features(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    features_text = (
        "Features of the Linxshort Bulk Link Shortener Bot:\n\n"
        "1. URL Shortening: Automatically shorten URLs in your messages using the Linxshort API.\n\n"
        "2. Bulk Processing: The bot can handle multiple URLs in a single message.\n\n"
        "3. Balance Tracking: Check your earnings, withdrawals, and statistics with /balance.\n\n"
        "4. Telegram Link Exclusion: Links to Telegram channels and chats are ignored to prevent modification.\n\n"
        "5. Easy Setup: Set up your Linxshort API key with a simple /setapi <API_KEY> command.\n\n"
        "6. Logout: Securely log out with the /logout command, which removes your API key from the bot.\n\n"
    )
    await update.message.reply_text(features_text)

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

# Run the Flask app in a separate thread
Thread(target=app.run, kwargs={'host': '0.0.0.0', 'port': 8000, 'debug': False}).start()

def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setapi", set_api_key))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("logout", logout))
    application.add_handler(CommandHandler("help", help))
    application.add_handler(CommandHandler("features", features))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))
    application.run_polling()

if __name__ == '__main__':
    main()
