import logging
import os
import re
import asyncio
import aiohttp
import requests
from threading import Thread
from flask import Flask
from telegram import ReplyKeyboardMarkup, KeyboardButton
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
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7613950530:AAEUaQ2Qs8PJYhud4G2eNmG-ZdDJ8xO9JOM")
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb+srv://aaroha:aaroha@cluster0.8z6ob17.mongodb.net/Cluster0?retryWrites=true&w=majority&appName=Cluster0")
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

# ----------------- Bot Commands -----------------
def get_main_menu():
    keyboard = [
        [KeyboardButton("🏠 Start")],
        [KeyboardButton("📊 Balance"), KeyboardButton("👤 Account"), KeyboardButton("💸 Withdraw")],
        [KeyboardButton("ℹ️ Help"), KeyboardButton("✨ Features"), KeyboardButton("🔑 Set API")],
        [KeyboardButton("🚪 Logout")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
# Modify start to show menu
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_name = update.message.from_user.full_name
    welcome_message = (
        f"Hello {user_name}! 👋😃\n\n"
        "🚀 Welcome to Linxshort BOT - Your Personal URL Shortener Bot. 🌐\n\n"
        "Just send me a link, and I'll work my magic to shorten it for you. Plus, I'll keep track of your earnings! 💰💼\n\n"
        "⚡️Still Have Doubts? Contact 👉 @Linxshort"
    )
    await update.message.reply_text(welcome_message, reply_markup=get_main_menu())

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
        
# ----------------- Balance & Withdraw -----------------
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
        
# ----------------- Account Info -----------------
async def account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users_collection.find_one({"user_id": user_id})

    if not user:
        await update.message.reply_text("⚠️ You are not logged in. Use /login <API_KEY>")
        return

    api_key = user["api_key"]
    url = f"https://linxshort.me/account-api.php?api={api_key}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()

        if data.get("status") != "success":
            await update.message.reply_text("❌ Invalid API key or error fetching data.")
            return

        # Format response
        msg = (
    f"👤 <b>Account Details</b>\n\n"
    f"👤 Username: {data.get('username')}\n"
    f"📧 Email: {data.get('email')}\n"
    f"🔑 API Token: {data.get('api_token')}\n\n"
    f"💰 Publisher Earnings: {data.get('publisher_earnings')}\n"
    f"🤝 Referral Earnings: {data.get('referral_earnings')}\n\n"
    f"👤 Name: {data.get('first_name')} {data.get('last_name')}\n"
    f"📞 Phone: {data.get('phone_number')}\n\n"
    f"🏠 Address:\n"
    f"Address Line 1: {data.get('address1')}\n"
    f"City: {data.get('city')}\n"
    f"State: {data.get('state')}\n"
    f"ZIP: {data.get('zip')}\n"
    f"Country: {data.get('country')}\n\n"
    f"💳 Withdrawal Method: {data.get('withdrawal_method')}\n"
)

        await update.message.reply_text(msg, parse_mode="HTML")

    except Exception as e:
        logger.error(e)
        await update.message.reply_text("⚠️ Error fetching account details.")

# ----------------- Withdraw Feature -----------------
WITHDRAW_AMOUNT, WITHDRAW_METHOD, WITHDRAW_DETAILS = range(3)

async def withdraw_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💰 Enter the amount you want to withdraw:")
    return WITHDRAW_AMOUNT

async def withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text)
        if amount <= 0:
            await update.message.reply_text("❌ Amount must be greater than 0. Enter again:")
            return WITHDRAW_AMOUNT
        context.user_data["withdraw_amount"] = amount

        user_id = update.message.from_user.id
        user_data = users_collection.find_one({"user_id": user_id})
        api_key = context.user_data.get("api_key") or user_data.get("api_key")
        resp = requests.get(f"https://linxshort.me/withdraw-methods-api.php?api={api_key}", timeout=10).json()

        if resp["status"] != "success" or not resp["methods"]:
            await update.message.reply_text("❌ No withdrawal methods found.")
            return ConversationHandler.END

        methods = [m for m in resp["methods"] if m["status"]]
        context.user_data["withdraw_methods"] = methods

        buttons = [[InlineKeyboardButton(m["name"], callback_data=m["id"])] for m in methods]
        reply_markup = InlineKeyboardMarkup(buttons)
        await update.message.reply_text("Select a withdrawal method:", reply_markup=reply_markup)
        return WITHDRAW_METHOD

    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Enter a numeric value:")
        return WITHDRAW_AMOUNT
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        return ConversationHandler.END

async def withdraw_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method_id = query.data
    context.user_data["withdraw_method"] = method_id

    method = next((m for m in context.user_data["withdraw_methods"] if m["id"] == method_id), None)
    if not method:
        await query.edit_message_text("❌ Invalid method selected.")
        return ConversationHandler.END

    context.user_data["withdraw_method_name"] = method["name"]

    # Only ask for account if method requires it
    if method.get("account_required", False):
        await query.edit_message_text(f"Enter your account info for {method['name']}:")
        return WITHDRAW_DETAILS
    else:
        return await submit_withdrawal(query, context)

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
        }
        if "withdraw_account" in context.user_data:
            payload["account"] = context.user_data["withdraw_account"]

        resp = requests.get(f"https://linxshort.me/withdraw-api.php", params=payload, timeout=10).json()
        if resp["status"] == "success":
            msg = f"✅ Withdrawal request submitted!\nAmount: {payload['amount']}\nMethod: {context.user_data['withdraw_method_name']}"
        else:
            msg = f"❌ Withdrawal failed: {resp.get('message', 'Unknown error')}"

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


# ----------------- Handle Menu Buttons -----------------
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "🏠 Start":
        await start(update, context)
    elif text == "🔑 Set API":
        await update.message.reply_text("Use /setapi <API_KEY> to set your API key.")
    elif text == "📊 Balance":
        await balance(update, context)
    elif text == "👤 Account":
        await account(update, context)
    elif text == "🚪 Logout":
        await logout(update, context)
    elif text == "ℹ️ Help":
        await help(update, context)
    elif text == "✨ Features":
        await features(update, context)
    else:
        await handle_message(update, context)


# ----------------- Main -----------------
def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Withdraw conversation
    withdraw_handler = ConversationHandler(
        entry_points=[
            CommandHandler("withdraw", withdraw_start),
            MessageHandler(filters.Regex("^💸 Withdraw$"), withdraw_start)  # menu button also works
        ],
        states={
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_amount)],
            WITHDRAW_METHOD: [CallbackQueryHandler(withdraw_method)],
            WITHDRAW_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_details)],
        },
        fallbacks=[CommandHandler("cancel", cancel_withdraw)],
    )
    application.add_handler(withdraw_handler)   # 👈 add this FIRST


    # Other commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setapi", set_api_key))
    application.add_handler(CommandHandler("logout", logout))
    application.add_handler(CommandHandler("help", help))
    application.add_handler(CommandHandler("features", features))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("account", account))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))
    application.add_handler(MessageHandler(filters.PHOTO, handle_message))
    
    # Start polling
    application.run_polling()

if __name__ == "__main__":
    main()
