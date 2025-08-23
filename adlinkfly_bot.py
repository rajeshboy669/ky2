import logging
import os
import re
import asyncio
import aiohttp
import requests
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from pymongo import MongoClient
from pymongo.uri_parser import parse_uri

# ----------------- Logging -----------------
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------- Flask Health -----------------
app = Flask(__name__)

@app.route('/health', methods=['GET'])
def health_check():
    try:
        return 'OK', 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return 'Service Unavailable', 503

# ----------------- Environment Variables -----------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "<YOUR_BOT_TOKEN>")
MONGODB_URI = os.getenv("MONGODB_URI", "<YOUR_MONGODB_URI>")
ADLINKFLY_API_URL = "https://linxshort.me/api"

if not TELEGRAM_BOT_TOKEN or not MONGODB_URI:
    raise ValueError("Missing required environment variables.")

# ----------------- MongoDB -----------------
parsed_uri = parse_uri(MONGODB_URI)
db_name = parsed_uri.get("database")
if not db_name:
    raise ValueError("Database name not found in MONGODB_URI.")

client = MongoClient(MONGODB_URI)
db = client[db_name]
users_collection = db["users"]

# ----------------- URL Shortening -----------------
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

async def process_text(text: str, api_key: str) -> str:
    async def replace_link(match):
        link = match.group(0)
        if "https://t.me/" in link:
            return link
        return await shorten_link(link, api_key)
    
    tasks = [replace_link(match) for match in URL_REGEX.finditer(text)]
    shortened_links = await asyncio.gather(*tasks)
    for match, shortened in zip(URL_REGEX.finditer(text), shortened_links):
        text = text.replace(match.group(0), shortened)
    return text

# ----------------- Bot Commands -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_name = update.message.from_user.full_name
    keyboard = [[InlineKeyboardButton("Sign Up", url="https://linxshort.me/auth/signup")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_message = (
        f"Hello {user_name}! 👋😃\n\n"
        "🚀 Welcome to Linxshort BOT - Your Personal URL Shortener Bot. 🌐\n\n"
        "Just send me a link, and I'll work my magic to shorten it for you. Plus, I'll keep track of your earnings! 💰💼\n\n"
        "Get started now and experience the power of Linxshort BOT. 💪🔗\n\n"
        "⚡️Still Have Doubts? Contact 👉 @Linxshort"
    )
    await update.message.reply_text(welcome_message, reply_markup=reply_markup)

async def set_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    api_key = context.args[0] if context.args else None
    if not api_key:
        await update.message.reply_text("Please provide an API key. Example: /setapi <API_KEY>")
        return
    users_collection.update_one({"user_id": user_id}, {"$set": {"api_key": api_key}}, upsert=True)
    context.user_data["api_key"] = api_key
    await update.message.reply_text("API key set successfully!")

async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    users_collection.delete_one({"user_id": user_id})
    context.user_data.pop("api_key", None)
    await update.message.reply_text("You have been logged out.")

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[InlineKeyboardButton("24/7 support", url="https://t.me/Linxshort_support")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    help_text = (
        "/start - Start the bot\n"
        "/setapi <API_KEY> - Set your API key\n"
        "/logout - Log out\n"
        "/balance - View balance & stats\n"
        "/withdraw - Withdraw your earnings\n"
        "/help - Show help message\n"
        "Send links to shorten automatically."
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
        "6. Balance & stats with /balance\n"
        "7. Withdraw earnings with /withdraw"
    )
    await update.message.reply_text(features_text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    api_key = context.user_data.get("api_key") or users_collection.find_one({"user_id": user_id}, {"api_key": 1}).get("api_key")
    if not api_key:
        await update.message.reply_text("Please set your API key using /setapi.")
        return

    text = update.message.text or update.message.caption
    if text:
        processed_text = await process_text(text, api_key)
        await update.message.reply_text(processed_text)

# ----------------- Balance & Withdraw -----------------
WITHDRAW_AMOUNT, WITHDRAW_METHOD, WITHDRAW_DETAILS = range(3)

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_data = users_collection.find_one({"user_id": user_id})
    api_key = context.user_data.get("api_key") or user_data.get("api_key")
    if not api_key:
        await update.message.reply_text("Set API key first using /setapi.")
        return
    try:
        resp = requests.get(f"https://linxshort.me/balance-api.php?api={api_key}", timeout=10).json()
        if resp["status"] == "success":
            msg = (
                f"👤 Username: {resp['username']}\n"
                f"💰 Balance: {resp['balance']}\n"
                f"✅ Withdrawn: {resp['withdrawn']}\n"
                f"🔗 Total Links: {resp['total_links']}\n"
                f"💸 Referrals: {resp['referrals']}"
            )
        else:
            msg = f"❌ Error: {resp.get('message', 'Unknown')}"
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {e}")

async def withdraw_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💰 Enter withdrawal amount:")
    return WITHDRAW_AMOUNT

async def withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text)
        context.user_data["withdraw_amount"] = amount
        user_id = update.message.from_user.id
        user_data = users_collection.find_one({"user_id": user_id})
        api_key = context.user_data.get("api_key") or user_data.get("api_key")
        resp = requests.get(f"https://linxshort.me/withdraw-methods-api.php?api={api_key}", timeout=10).json()
        methods = [m for m in resp.get("methods", []) if m.get("status")]
        context.user_data["withdraw_methods"] = methods
        buttons = [[InlineKeyboardButton(m["name"], callback_data=m["id"])] for m in methods]
        await update.message.reply_text("Select withdraw method:", reply_markup=InlineKeyboardMarkup(buttons))
        return WITHDRAW_METHOD
    except:
        await update.message.reply_text("Enter a valid number:")
        return WITHDRAW_AMOUNT

async def withdraw_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method_id = query.data
    context.user_data["withdraw_method"] = method_id

    # Check if last account exists
    user_id = query.from_user.id
    last_account = users_collection.find_one({"user_id": user_id}, {"last_withdraw_account": 1}).get("last_withdraw_account")
    if last_account:
        context.user_data["withdraw_account"] = last_account
        return await submit_withdrawal(query, context)
    else:
        await query.edit_message_text("Enter account info for withdrawal:")
        return WITHDRAW_DETAILS

async def withdraw_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["withdraw_account"] = update.message.text
    return await submit_withdrawal(update, context)

async def submit_withdrawal(update_obj, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update_obj.from_user.id
        user_data = users_collection.find_one({"user_id": user_id})
        api_key = context.user_data.get("api_key") or user_data.get("api_key")
        payload = {
            "api": api_key,
            "amount": context.user_data["withdraw_amount"],
            "method": context.user_data["withdraw_method"],
            "account": context.user_data["withdraw_account"]
        }
        resp = requests.get(f"https://linxshort.me/withdraw-api.php", params=payload, timeout=10).json()

        # Save last account
        users_collection.update_one({"user_id": user_id}, {"$set": {"last_withdraw_account": context.user_data["withdraw_account"]}}, upsert=True)

        if resp["status"] == "success":
            msg = f"✅ Withdrawal submitted! Amount: {payload['amount']}"
        else:
            msg = f"❌ Withdrawal failed: {resp.get('message', 'Unknown')}"
        if isinstance(update_obj, Update):
            await update_obj.message.reply_text(msg)
        else:
            await update_obj.edit_message_text(msg)
        return ConversationHandler.END
    except Exception as e:
        await update_obj.message.reply_text(f"❌ Error: {e}")
        return ConversationHandler.END

async def cancel_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Withdrawal canceled.")
    return ConversationHandler.END

# ----------------- Run Flask -----------------
Thread(target=app.run, kwargs={'host': '0.0.0.0', 'port': 8000, 'debug': False}).start()

# ----------------- Main -----------------
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setapi", set_api_key))
    application.add_handler(CommandHandler("logout", logout))
    application.add_handler(CommandHandler("help", help))
    application.add_handler(CommandHandler("features", features))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))

    # Withdraw ConversationHandler
    withdraw_handler = ConversationHandler(
        entry_points=[CommandHandler("withdraw", withdraw_start)],
        states={
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_amount)],
            WITHDRAW_METHOD: [CallbackQueryHandler(withdraw_method)],
            WITHDRAW_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_details)],
        },
        fallbacks=[CommandHandler("cancel", cancel_withdraw)],
    )
    application.add_handler(withdraw_handler)

    application.run_polling()

if __name__ == '__main__':
    main()
