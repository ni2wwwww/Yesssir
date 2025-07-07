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
CHECKER_API_URL = "https://sigmabro766-1.onrender.com"
BINLIST_API_URL = "https://lookup.binlist.net/"

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

# --- UI/Spinner Helpers ---
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
        return {
            "error": "Invalid BIN", "bin": bin_number, "scheme": "N/A", "type": "N/A",
            "brand": "N/A", "bank_name": "N/A", "country_name": "N/A", "country_emoji": "🏳️"
        }
    try:
        request_headers = {'Accept-Version': '3', **COMMON_HTTP_HEADERS}
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{BINLIST_API_URL}{bin_number}", headers=request_headers, timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                return {
                    "bin": bin_number, "scheme": data.get("scheme", "N/A").upper(),
                    "type": data.get("type", "N/A").upper(), "brand": data.get("brand", "N/A").upper(),
                    "bank_name": data.get("bank", {}).get("name", "N/A"),
                    "country_name": data.get("country", {}).get("name", "N/A"),
                    "country_emoji": data.get("country", {}).get("emoji", "🏳️")
                }
            elif response.status_code == 404:
                return {"error": "BIN not found", "bin": bin_number, "scheme": "N/A", "type": "N/A",
                        "brand": "N/A", "bank_name": "N/A", "country_name": "N/A", "country_emoji": "🏳️"}
            else:
                logger.error(f"Binlist API error for BIN {bin_number}: Status {response.status_code}")
                return {"error": f"API Error {response.status_code}", "bin": bin_number, "scheme": "N/A", "type": "N/A",
                        "brand": "N/A", "bank_name": "N/A", "country_name": "N/A", "country_emoji": "🏳️"}
    except Exception as e:
        logger.exception(f"Error fetching BIN details for {bin_number}")
        return {"error": "Lookup failed", "bin": bin_number, "scheme": "N/A", "type": "N/A",
                "brand": "N/A", "bank_name": "N/A", "country_name": "N/A", "country_emoji": "🏳️"}

def parse_checker_api_response(response_text: str):
    """
    Parses the potentially dirty response from the checker API.
    It finds the first '{' and tries to decode the JSON from there.
    Returns the decoded JSON dictionary or None if parsing fails.
    """
    if not response_text:
        return None
    # Find the first character of a JSON object
    json_start_index = response_text.find('{')
    if json_start_index == -1:
        return None # No JSON object found
    
    # Extract the potential JSON string
    json_string = response_text[json_start_index:]
    
    try:
        # Try to load the extracted string as JSON
        return json.loads(json_string)
    except json.JSONDecodeError:
        # Return None if the extracted string is still not valid JSON
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
        try:
            await update.callback_query.message.edit_text(welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        except Exception:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
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
        (e.g., /add <code>https://shop.com</code>)
    ✧ /my_site - Displays your current site.
    ✧ /chk <code>N|M|Y|C</code> - Single card check.
        (e.g., <code>123...|01|25|123</code>)
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
    message_text = ""
    reply_markup = None

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

    try:
        card_number, _, _, _ = cc_details_full.split('|')
    except ValueError:
        await update.message.reply_text("⚠️ Invalid card format. Use: <code>N|M|Y|C</code>", parse_mode=ParseMode.HTML)
        return

    spinner_text_template = f"Checking <code>{html.escape(card_number[:6])}XX...</code>" + "{}"
    spinner_msg = await send_spinner_message(context, update.effective_chat.id, spinner_text_template)
    
    start_time = time.time()
    bin_data = await get_bin_details(card_number[:6])

    params = {"site": shopify_site, "cc": cc_details_full}
    final_card_status_text = "Error Initializing Check"
    final_card_status_emoji = "❓"
    final_api_response_display = "N/A"
    checker_api_gateway = "N/A"
    checker_api_price = "0.00"

    try:
        async with httpx.AsyncClient(headers=COMMON_HTTP_HEADERS) as client:
            response = await client.get(CHECKER_API_URL, params=params, timeout=45.0)

        if response.status_code == 200:
            # **MODIFICATION START**
            # Use the robust parser instead of response.json()
            api_data = parse_checker_api_response(response.text)
            
            if api_data:
                checker_api_response_text = api_data.get("Response", "Unknown API Response")
                checker_api_gateway = api_data.get("Gateway", "N/A")
                checker_api_price = api_data.get("Price", "0.00")

                if checker_api_response_text == "CARD_DECLINED":
                    final_card_status_emoji = "❌"
                    final_card_status_text = "Declined"
                    final_api_response_display = "CARD_DECLINED"
                elif "Thank You" in checker_api_response_text or "ORDER_PLACED" in checker_api_response_text.upper():
                    final_card_status_emoji = "💎"
                    final_card_status_text = "Charged"
                    final_api_response_display = "ORDER_PLACED"
                else:
                    final_card_status_emoji = "ℹ️"
                    final_card_status_text = "Info"
                    final_api_response_display = checker_api_response_text
            else:
                # Parsing failed even after cleaning
                final_card_status_emoji = "❓"
                final_card_status_text = "API Response Parse Error"
                final_api_response_display = response.text[:100].strip() if response.text else "Empty or non-JSON response"
                logger.error(f"CHK: JSONDecodeError (after cleaning) for user {user_id}. Raw: {response.text[:200]}")
            # **MODIFICATION END**
        else:
            final_card_status_emoji = "⚠️"
            final_card_status_text = f"API Error ({response.status_code})"
            final_api_response_display = response.text[:100].strip() if response.text else f"Status {response.status_code}, no content."
            logger.error(f"CHK: HTTP Error for user {user_id}: {response.status_code} - Text: {response.text[:200]}")

    except httpx.TimeoutException:
        final_card_status_emoji = "⏱️"
        final_card_status_text = "API Timeout"
        final_api_response_display = "Request to checker API timed out."
    except httpx.RequestError as e:
        final_card_status_emoji = "🌐"
        final_card_status_text = "Network Issue"
        final_api_response_display = f"Could not connect: {str(e)[:60]}"
    except Exception as e:
        final_card_status_emoji = "💥"
        final_card_status_text = "Unexpected Error"
        final_api_response_display = str(e)[:60]
        logger.exception(f"CHK: Unexpected error for user {user_id}")

    await delete_spinner_message(context, spinner_msg)
    time_taken = round(time.time() - start_time, 2)

    # --- Formatting the final result message ---
    escaped_cc_details = html.escape(cc_details_full)
    escaped_shopify_site = html.escape(shopify_site)
    escaped_gateway = html.escape(checker_api_gateway if checker_api_gateway.lower() != "normal" else "Normal Shopify")
    escaped_price = html.escape(str(checker_api_price))
    escaped_api_response = html.escape(final_api_response_display)
    escaped_bin_num = html.escape(bin_data.get('bin', 'N/A'))
    bin_info_parts = [bin_data.get('scheme', 'N/A'), bin_data.get('type', 'N/A'), bin_data.get('brand', 'N/A')]
    bin_info_str = " - ".join(filter(lambda x: x and x != 'N/A', bin_info_parts)) or "N/A"
    escaped_bin_info = html.escape(bin_info_str)
    escaped_bank_name = html.escape(bin_data.get('bank_name', 'N/A'))
    escaped_country_name = html.escape(bin_data.get('country_name', 'N/A'))
    country_emoji = bin_data.get('country_emoji', '🏳️')
    user_membership_emoji_display = "⚜️ [Elite]"

    result_message = (
        f"<b>[#AutoShopify] | ✨ Result</b>\n"
        f"<pre>─────────────────</pre>\n"
        f"💳 <b>Card:</b> <code>{escaped_cc_details}</code>\n"
        f"🌍 <b>Site:</b> <pre>{escaped_shopify_site}</pre>\n"
        f"⚙️ <b>Gateway:</b> {escaped_gateway} ({escaped_price}$)\n"
        f"{final_card_status_emoji} <b>Status:</b> {html.escape(final_card_status_text)}\n"
        f"🗣️ <b>Response:</b> <pre>{escaped_api_response}</pre>\n"
        f"<pre>─ ─ ─ BIN Info ─ ─ ─</pre>\n"
        f"<b>BIN:</b> <code>{escaped_bin_num}</code>\n"
        f"<b>Info:</b> {escaped_bin_info}\n"
        f"<b>Bank:</b> {escaped_bank_name} {('🏦' if escaped_bank_name != 'N/A' else '')}\n"
        f"<b>Country:</b> {escaped_country_name} {country_emoji}\n"
        f"<pre>─ ─ ─ Meta ─ ─ ─</pre>\n"
        f"👤 <b>Checked By:</b> {user_display_name} {user_membership_emoji_display}\n"
        f"⏱️ <b>Time:</b> {time_taken}s | Prox: [Live ⚡️]"
    )
    
    keyboard_buttons = [
        [InlineKeyboardButton("💳 Check Another", callback_data="chk:prompt_another")],
        [
            InlineKeyboardButton("🔗 Change Site", callback_data="site:prompt_add"),
            InlineKeyboardButton("« Main Menu", callback_data="nav:show_start")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard_buttons)
    await update.message.reply_text(result_message, parse_mode=ParseMode.HTML, reply_markup=reply_markup)


async def mchk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    shopify_site = get_site_for_user(user_id)
    user = update.effective_user
    user_display_for_log = f"ID: {user.id}, User: @{user.username}" if user.username else f"ID: {user.id}"

    if not shopify_site:
        await update.message.reply_text("⚠️ No Shopify site set. Use /add <code>&lt;site_url&gt;</code> first.", parse_mode=ParseMode.HTML)
        return

    document = update.message.document or (update.message.reply_to_message and update.message.reply_to_message.document)
    if not document:
        await update.message.reply_text("⚠️ File missing. Reply to a <code>.txt</code> file with /mchk.", parse_mode=ParseMode.HTML)
        return

    if document.mime_type != 'text/plain':
        await update.message.reply_text("⚠️ Invalid file type. Please upload a <code>.txt</code> file.", parse_mode=ParseMode.HTML)
        return

    file_obj = await context.bot.get_file(document.file_id)
    file_content = (await file_obj.download_as_bytearray()).decode('utf-8')
    ccs_to_check = [line.strip() for line in file_content.splitlines() if line.strip() and line.strip().count('|') == 3]

    if not ccs_to_check:
        await update.message.reply_text("⚠️ File contains no valid card lines (<code>N|M|Y|C</code>).", parse_mode=ParseMode.HTML)
        return

    total_ccs = len(ccs_to_check)
    approved, declined, other, errors = 0, 0, 0, 0
    results_log = [f"--- Mass Check Results for {user_display_for_log} ---", f"Site: {shopify_site}\n"]

    status_msg = await update.message.reply_text(f"Starting mass check for {total_ccs} cards...", parse_mode=ParseMode.HTML)
    start_mass_time = time.time()

    async with httpx.AsyncClient(headers=COMMON_HTTP_HEADERS) as client:
        for i, cc_details in enumerate(ccs_to_check):
            params = {"site": shopify_site, "cc": cc_details}
            log_entry = f"{html.escape(cc_details)} -> "

            try:
                response = await client.get(CHECKER_API_URL, params=params, timeout=45.0)
                
                # **MODIFICATION START**
                api_data = parse_checker_api_response(response.text)
                
                if api_data:
                    api_response = api_data.get("Response", "Unknown")
                    if api_response == "CARD_DECLINED":
                        declined += 1
                        log_entry += "❌ DECLINED"
                    elif "Thank You" in api_response or "ORDER_PLACED" in api_response.upper():
                        approved += 1
                        log_entry += f"✅ APPROVED (Price: {api_data.get('Price', 'N/A')})"
                    else:
                        other += 1
                        log_entry += f"ℹ️ OTHER ({html.escape(api_response)})"
                elif response.status_code != 200:
                     errors += 1
                     log_entry += f"⚠️ API ERROR ({response.status_code})"
                else:
                    errors += 1
                    log_entry += f"⚠️ API PARSE ERROR (Raw: {html.escape(response.text[:70])})"
                # **MODIFICATION END**

            except (httpx.TimeoutException, httpx.RequestError):
                errors += 1
                log_entry += "⏱️ NETWORK/TIMEOUT ERROR"
            except Exception as e:
                errors += 1
                log_entry += f"💥 UNEXPECTED ERROR ({html.escape(str(e))})"
            
            results_log.append(log_entry)

            if (i + 1) % 5 == 0 or (i + 1) == total_ccs:
                try:
                    await context.bot.edit_message_text(
                        chat_id=status_msg.chat_id, message_id=status_msg.message_id,
                        text=f"Progress: {i+1}/{total_ccs}\n✅ Approved: {approved} | ❌ Declined: {declined} | ⚠️ Errors: {errors}"
                    )
                except Exception:
                    pass
            await asyncio.sleep(0.95)

    total_time = round(time.time() - start_mass_time, 2)
    final_summary = (
        f"<b>Mass Check Complete</b>\n"
        f"Processed {total_ccs} cards in {total_time}s.\n\n"
        f"✅ Approved: {approved}\n"
        f"❌ Declined: {declined}\n"
        f"ℹ️ Other: {other}\n"
        f"⚠️ Errors: {errors}"
    )
    await status_msg.edit_text(final_summary, parse_mode=ParseMode.HTML)

    result_file_content = "\n".join(results_log)
    result_filename = f"Results_{user.id}_{int(time.time())}.txt"
    with open(result_filename, "w", encoding="utf-8") as f:
        f.write(result_file_content)
    
    with open(result_filename, "rb") as f_to_send:
        await update.message.reply_document(
            document=f_to_send,
            filename=f"ShopifyResults_{approved}hits.txt",
            caption=f"Results for <pre>{html.escape(shopify_site)}</pre>",
            parse_mode=ParseMode.HTML
        )
    os.remove(result_filename)


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
        current_site = get_site_for_user(user_id)
        if current_site:
            await query.message.reply_text(f"💳 Ready to check.\nUse /chk <code>N|M|Y|C</code>", parse_mode=ParseMode.HTML)
        else:
            await query.message.reply_text("⚠️ Site not set. Use 'Set/Update Site' first.", parse_mode=ParseMode.HTML)
    elif data == "mchk:prompt_now":
        current_site = get_site_for_user(user_id)
        if current_site:
            await query.message.reply_text(f"🗂️ Mass check ready.\nUpload a <code>.txt</code> file and reply with /mchk.", parse_mode=ParseMode.HTML)
        else:
            await query.message.reply_text("⚠️ Site not set. Use 'Set/Update Site' first.", parse_mode=ParseMode.HTML)


def main():
    """Start the bot."""
    if not TELEGRAM_BOT_TOKEN or "AAGKxCpVrDVGFbyd3aQi0_9G9CHGcJMCLEY" in TELEGRAM_BOT_TOKEN and len(TELEGRAM_BOT_TOKEN) < 20: # Simple placeholder check
         logger.critical("CRITICAL: Telegram Bot Token is a placeholder or missing. Please update the script.")
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
    # Handler for when a .txt file is uploaded with /mchk in the caption
    application.add_handler(MessageHandler(filters.CAPTION & filters.Regex(r'^/mchk$') & filters.Document.TEXT, mchk_command))


    logger.info("Bot is polling for updates.")
    application.run_polling()

if __name__ == "__main__":
    main()
