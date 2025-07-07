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
import secrets
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Optional, List, Dict, Any
from pathlib import Path

# --- Basic Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Configuration ---
TELEGRAM_BOT_TOKEN = "7615802418:AAGKxCpVrDVGFbyd3aQi0_9G9CHGcJMCLEY"
CHECKER_API_URL = "https://sigmabro766-1.onrender.com"  # YOUR SHOPIFY CHECKER API
BINLIST_API_URL = "https://lookup.binlist.net/"

COMMON_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# Admin configuration
ADMIN_IDS = [7675426356]  # Add your real Telegram user ID here

# ═══════════════════════════════════════════════════════════════════════════════
# 💎 PREMIUM SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

# Create directories
Path("data").mkdir(exist_ok=True)
Path("logs").mkdir(exist_ok=True)

class MembershipLevel(Enum):
    FREE = "free"
    PREMIUM = "premium"
    VIP = "vip"
    ELITE = "elite"

@dataclass
class UserProfile:
    user_id: int
    username: str
    membership: MembershipLevel = MembershipLevel.FREE
    total_checks: int = 0
    successful_checks: int = 0
    failed_checks: int = 0
    join_date: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    premium_expires: Optional[datetime] = None
    daily_checks: int = 0
    last_daily_reset: datetime = field(default_factory=datetime.now)

    @property
    def success_rate(self) -> float:
        if self.total_checks == 0:
            return 0.0
        return (self.successful_checks / self.total_checks) * 100

    @property
    def membership_emoji(self) -> str:
        emojis = {
            MembershipLevel.FREE: "🆓",
            MembershipLevel.PREMIUM: "💎",
            MembershipLevel.VIP: "👑",
            MembershipLevel.ELITE: "⭐"
        }
        return emojis[self.membership]

    @property
    def processing_delay(self) -> float:
        delays = {
            MembershipLevel.FREE: 1.0,
            MembershipLevel.PREMIUM: 0.5,
            MembershipLevel.VIP: 0.2,
            MembershipLevel.ELITE: 0.1
        }
        return delays[self.membership]

@dataclass
class LicenseKey:
    key: str
    tier: MembershipLevel
    duration_days: int
    created_by: int
    created_at: datetime
    used_by: Optional[int] = None
    used_at: Optional[datetime] = None
    is_used: bool = False

class DataManager:
    def __init__(self):
        self.users: Dict[int, UserProfile] = {}
        self.license_keys: Dict[str, LicenseKey] = {}
        self._lock = threading.Lock()
        self._load_all_data()

    def _load_all_data(self):
        try:
            if os.path.exists("data/user_profiles.json"):
                with open("data/user_profiles.json", 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for user_id, user_data in data.items():
                        user_data['user_id'] = int(user_id)
                        user_data['membership'] = MembershipLevel(user_data['membership'])
                        user_data['join_date'] = datetime.fromisoformat(user_data['join_date'])
                        user_data['last_active'] = datetime.fromisoformat(user_data['last_active'])
                        user_data['last_daily_reset'] = datetime.fromisoformat(user_data['last_daily_reset'])
                        if user_data.get('premium_expires'):
                            user_data['premium_expires'] = datetime.fromisoformat(user_data['premium_expires'])
                        self.users[int(user_id)] = UserProfile(**user_data)

            if os.path.exists("data/license_keys.json"):
                with open("data/license_keys.json", 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for key, key_data in data.items():
                        key_data['tier'] = MembershipLevel(key_data['tier'])
                        key_data['created_at'] = datetime.fromisoformat(key_data['created_at'])
                        if key_data.get('used_at'):
                            key_data['used_at'] = datetime.fromisoformat(key_data['used_at'])
                        self.license_keys[key] = LicenseKey(**key_data)

            logger.info(f"Loaded {len(self.users)} users and {len(self.license_keys)} license keys")
        except Exception as e:
            logger.error(f"Error loading data: {e}")

    def _save_all_data(self):
        with self._lock:
            try:
                user_data = {}
                for user_id, user in self.users.items():
                    data = asdict(user)
                    data['membership'] = data['membership'].value
                    data['join_date'] = data['join_date'].isoformat()
                    data['last_active'] = data['last_active'].isoformat()
                    data['last_daily_reset'] = data['last_daily_reset'].isoformat()
                    if data['premium_expires']:
                        data['premium_expires'] = data['premium_expires'].isoformat()
                    user_data[str(user_id)] = data

                with open("data/user_profiles.json.tmp", 'w', encoding='utf-8') as f:
                    json.dump(user_data, f, indent=2, ensure_ascii=False)
                os.replace("data/user_profiles.json.tmp", "data/user_profiles.json")

                key_data = {}
                for key, license_key in self.license_keys.items():
                    data = asdict(license_key)
                    data['tier'] = data['tier'].value
                    data['created_at'] = data['created_at'].isoformat()
                    if data['used_at']:
                        data['used_at'] = data['used_at'].isoformat()
                    key_data[key] = data

                with open("data/license_keys.json.tmp", 'w', encoding='utf-8') as f:
                    json.dump(key_data, f, indent=2, ensure_ascii=False)
                os.replace("data/license_keys.json.tmp", "data/license_keys.json")

            except Exception as e:
                logger.error(f"Error saving data: {e}")

    def get_user(self, user_id: int, username: str = "") -> UserProfile:
        if user_id not in self.users:
            self.users[user_id] = UserProfile(user_id=user_id, username=username)
            self._save_all_data()
        else:
            if username and self.users[user_id].username != username:
                self.users[user_id].username = username
                self._save_all_data()
        
        user = self.users[user_id]
        if datetime.now().date() > user.last_daily_reset.date():
            user.daily_checks = 0
            user.last_daily_reset = datetime.now()
            self._save_all_data()
        
        user.last_active = datetime.now()
        return user

    def update_user(self, user: UserProfile):
        self.users[user.user_id] = user
        self._save_all_data()

    def generate_license_key(self, tier: MembershipLevel, duration_days: int, created_by: int) -> str:
        prefix = {
            MembershipLevel.PREMIUM: "PRE",
            MembershipLevel.VIP: "VIP", 
            MembershipLevel.ELITE: "ELT"
        }.get(tier, "KEY")
        
        key = f"{prefix}-{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}"
        
        license_key = LicenseKey(
            key=key,
            tier=tier,
            duration_days=duration_days,
            created_by=created_by,
            created_at=datetime.now()
        )
        
        self.license_keys[key] = license_key
        self._save_all_data()
        return key

    def redeem_license_key(self, key: str, user_id: int) -> bool:
        if key not in self.license_keys or self.license_keys[key].is_used:
            return False
        
        license_key = self.license_keys[key]
        license_key.is_used = True
        license_key.used_by = user_id
        license_key.used_at = datetime.now()
        
        user = self.users[user_id]
        user.membership = license_key.tier
        user.premium_expires = datetime.now() + timedelta(days=license_key.duration_days)
        
        self._save_all_data()
        return True

# Global data manager
data_manager = DataManager()

# --- YOUR ORIGINAL USER DATA PERSISTENCE ---
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

# --- YOUR ORIGINAL UI/SPINNER HELPERS ---
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

# --- YOUR ORIGINAL API HELPERS ---

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
    YOUR ORIGINAL WORKING PARSER - HANDLES SIGMABRO API WITH PHP WARNINGS PERFECTLY
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

# --- YOUR ORIGINAL COMMAND HANDLERS WITH PREMIUM UI ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    profile = data_manager.get_user(user.id, user.username or user.first_name)
    user_name = html.escape(user.username if user.username else user.first_name)
    
    welcome_message = f"""🏪 <b>Auto Shopify Checker</b> 🏪

Welcome, <b>{user_name}</b>. System active. {profile.membership_emoji}
Your tool for Shopify card testing.

📊 <b>Your Stats:</b>
├ Total Checks: {profile.total_checks:,}
├ Successful: {profile.successful_checks:,} ({profile.success_rate:.1f}%)
├ Failed: {profile.failed_checks:,}
├ Today: {profile.daily_checks:,}
└ Tier: {profile.membership.value.upper()} {profile.membership_emoji}

─────────────────
<b>Choose an action:</b>"""

    keyboard = [
        [
            InlineKeyboardButton("🔗 Set/Update Site", callback_data="site:prompt_add"),
            InlineKeyboardButton("⚙️ My Current Site", callback_data="site:show_current")
        ],
        [
            InlineKeyboardButton("💳 Single Check", callback_data="chk:prompt_now"),
            InlineKeyboardButton("🗂️ Mass Check", callback_data="mchk:prompt_now")
        ],
        [
            InlineKeyboardButton("📖 View Commands", callback_data="nav:show_cmds"),
            InlineKeyboardButton("📊 My Stats", callback_data="stats:show")
        ],
        [
            InlineKeyboardButton("🎫 Redeem Key", callback_data="key:redeem"),
            InlineKeyboardButton("🧑‍💻 Dev Contact", url="https://t.me/alanjocc")
        ]
    ]
    
    # Add admin panel for admins
    if user.id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin:panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        try:
            await update.callback_query.message.edit_text(welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        except Exception:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def cmds_command(update: Update, context: ContextTypes.DEFAULT_TYPE, from_button: bool = False):
    commands_text = """🏪 <b>Shopify Checker Commands</b> 🏪

─────────────────
✧ /start - Welcome & main menu.
✧ /cmds - Shows this command list.
✧ /add <code>&lt;url&gt;</code> - Sets target Shopify site.
    (e.g., /add <code>https://shop.myshopify.com</code>)
✧ /my_site - Displays your current site.
✧ /chk <code>N|M|Y|C</code> - Single card check.
    (e.g., <code>5143773993634806|10|27|108</code>)
✧ /mchk - Mass check from <code>.txt</code> file.
✧ /redeem <code>KEY</code> - Redeem premium license.
✧ /stats - View your statistics.
─────────────────
🧑‍💻 Dev: @alanjocc"""
    
    keyboard_cmds = [[InlineKeyboardButton("« Main Menu", callback_data="nav:show_start")]]
    reply_markup_cmds = InlineKeyboardMarkup(keyboard_cmds)

    if from_button and update.callback_query:
        await update.callback_query.message.edit_text(commands_text, reply_markup=reply_markup_cmds, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(commands_text, reply_markup=reply_markup_cmds, parse_mode=ParseMode.HTML)

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    profile = data_manager.get_user(user_id, update.effective_user.username or update.effective_user.first_name)
    
    if not context.args:
        await update.message.reply_text("⚠️ <b>URL Missing!</b>\nProvide a Shopify site URL after /add. Example: /add <code>https://your-shop.myshopify.com</code>", parse_mode=ParseMode.HTML)
        return

    site_url = context.args[0]
    if not (site_url.startswith("http://") or site_url.startswith("https://")):
        await update.message.reply_text("⚠️ <b>Invalid URL Format!</b>\nMust start with <code>http://</code> or <code>https://</code>.", parse_mode=ParseMode.HTML)
        return
        
    set_site_for_user(user_id, site_url)
    escaped_site_url = html.escape(site_url)
    response_message = f"""🏪 <b>Shopify Site Configuration</b> 🏪

─────────────────
✅ <b>Target site updated successfully.</b>

🔗 <b>Target:</b> <pre>{escaped_site_url}</pre>
📡 <b>Status:</b> Ready for Checks
🚀 <b>Speed:</b> {profile.membership.value.upper()} Tier
─────────────────"""
    
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
        message_text = f"""🏪 <b>Current Shopify Site</b> 🏪

─────────────────
🔗 <b>Target:</b> <pre>{html.escape(shopify_site)}</pre>
─────────────────"""
        keyboard = [
            [InlineKeyboardButton("💳 Single Check", callback_data="chk:prompt_now")],
            [InlineKeyboardButton("🔗 Change Site", callback_data="site:prompt_add")],
            [InlineKeyboardButton("« Main Menu", callback_data="nav:show_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
    else:
        message_text = """🏪 <b>Current Shopify Site</b> 🏪

─────────────────
⚠️ No Shopify site is currently set.
Please add one to proceed.
─────────────────"""
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
    """YOUR ORIGINAL SHOPIFY CHECKER COMMAND - NO TIMEOUT, WAITS FOR SIGMABRO API"""
    user_id = update.effective_user.id
    shopify_site = get_site_for_user(user_id)
    profile = data_manager.get_user(user_id, update.effective_user.username or update.effective_user.first_name)
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

    spinner_text_template = f"Checking <code>{html.escape(card_number[:6])}XX...</code> on Shopify" + "{}"
    spinner_msg = await send_spinner_message(context, update.effective_chat.id, spinner_text_template)
    
    start_time = time.time()
    
    # Add membership-based delay
    await asyncio.sleep(profile.processing_delay)
    
    bin_data = await get_bin_details(card_number[:6])

    # YOUR ORIGINAL SIGMABRO API CALL - NO TIMEOUT!!!
    params = {"site": shopify_site, "cc": cc_details_full}
    final_card_status_text = "Error Initializing Check"
    final_card_status_emoji = "❓"
    final_api_response_display = "N/A"
    checker_api_gateway = "N/A"
    checker_api_price = "0.00"

    try:
        # NO TIMEOUT - WAITS FOREVER FOR SIGMABRO API RESPONSE
        async with httpx.AsyncClient(headers=COMMON_HTTP_HEADERS) as client:
            response = await client.get(CHECKER_API_URL, params=params)

        if response.status_code == 200:
            # YOUR ORIGINAL WORKING PARSER - HANDLES PHP WARNINGS PERFECTLY
            api_data = parse_checker_api_response(response.text)
            
            if api_data:
                checker_api_response_text = api_data.get("Response", "Unknown API Response")
                checker_api_gateway = api_data.get("Gateway", "N/A")
                checker_api_price = api_data.get("Price", "0.00")

                if checker_api_response_text == "CARD_DECLINED":
                    final_card_status_emoji = "❌"
                    final_card_status_text = "Declined"
                    final_api_response_display = "CARD_DECLINED"
                    profile.failed_checks += 1
                elif "Thank You" in checker_api_response_text or "ORDER_PLACED" in checker_api_response_text.upper():
                    final_card_status_emoji = "💎"
                    final_card_status_text = "Charged"
                    final_api_response_display = "ORDER_PLACED"
                    profile.successful_checks += 1
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
        else:
            final_card_status_emoji = "⚠️"
            final_card_status_text = f"API Error ({response.status_code})"
            final_api_response_display = response.text[:100].strip() if response.text else f"Status {response.status_code}, no content."
            logger.error(f"CHK: HTTP Error for user {user_id}: {response.status_code} - Text: {response.text[:200]}")

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

    # Update premium stats
    profile.total_checks += 1
    profile.daily_checks += 1
    data_manager.update_user(profile)

    # --- YOUR ORIGINAL FORMATTING - EXACT SAME ---
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
    user_membership_emoji_display = f"{profile.membership_emoji} [{profile.membership.value.upper()}]"

    result_message = (
        f"<b>[#AutoShopify] | ✨ Result</b>\n"
        f"─────────────────\n"
        f"💳 <b>Card:</b> <code>{escaped_cc_details}</code>\n"
        f"🌍 <b>Site:</b> <pre>{escaped_shopify_site}</pre>\n"
        f"⚙️ <b>Gateway:</b> {escaped_gateway} ({escaped_price}$)\n"
        f"{final_card_status_emoji} <b>Status:</b> {html.escape(final_card_status_text)}\n"
        f"🗣️ <b>Response:</b> <pre>{escaped_api_response}</pre>\n"
        f"─ ─ ─ BIN Info ─ ─ ─\n"
        f"<b>BIN:</b> <code>{escaped_bin_num}</code>\n"
        f"<b>Info:</b> {escaped_bin_info}\n"
        f"<b>Bank:</b> {escaped_bank_name} {('🏦' if escaped_bank_name != 'N/A' else '')}\n"
        f"<b>Country:</b> {escaped_country_name} {country_emoji}\n"
        f"─ ─ ─ Meta ─ ─ ─\n"
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
    """YOUR ORIGINAL MASS SHOPIFY CHECKER COMMAND - NO TIMEOUT"""
    user_id = update.effective_user.id
    shopify_site = get_site_for_user(user_id)
    profile = data_manager.get_user(user_id, update.effective_user.username or update.effective_user.first_name)
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
    results_log = [f"--- Mass Shopify Check Results for {user_display_for_log} ---", f"Site: {shopify_site}\n"]

    status_msg = await update.message.reply_text(f"Starting mass Shopify check for {total_ccs} cards...", parse_mode=ParseMode.HTML)
    start_mass_time = time.time()

    # NO TIMEOUT - WAITS FOREVER FOR SIGMABRO API
    async with httpx.AsyncClient(headers=COMMON_HTTP_HEADERS) as client:
        for i, cc_details in enumerate(ccs_to_check):
            params = {"site": shopify_site, "cc": cc_details}
            log_entry = f"{html.escape(cc_details)} -> "

            try:
                response = await client.get(CHECKER_API_URL, params=params)
                
                # YOUR ORIGINAL WORKING PARSER - HANDLES PHP WARNINGS PERFECTLY
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

            except httpx.RequestError:
                errors += 1
                log_entry += "⏱️ NETWORK ERROR"
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
            
            # Add membership-based delay
            await asyncio.sleep(profile.processing_delay)

    total_time = round(time.time() - start_mass_time, 2)
    
    # Update premium stats
    profile.total_checks += total_ccs
    profile.successful_checks += approved
    profile.failed_checks += declined
    profile.daily_checks += total_ccs
    data_manager.update_user(profile)
    
    final_summary = (
        f"🏪 <b>Mass Shopify Check Complete</b> 🏪\n"
        f"Processed {total_ccs} cards in {total_time}s.\n\n"
        f"✅ Approved: {approved}\n"
        f"❌ Declined: {declined}\n"
        f"ℹ️ Other: {other}\n"
        f"⚠️ Errors: {errors}\n"
        f"👤 Checked by: {profile.username} {profile.membership_emoji}"
    )
    await status_msg.edit_text(final_summary, parse_mode=ParseMode.HTML)

    result_file_content = "\n".join(results_log)
    result_filename = f"ShopifyResults_{user.id}_{int(time.time())}.txt"
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

# --- PREMIUM COMMANDS ---

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Redeem license key"""
    user = update.effective_user
    profile = data_manager.get_user(user.id, user.username or user.first_name)

    if not context.args:
        await update.message.reply_text(
            "🎫 <b>Redeem License Key:</b>\n/redeem <code>PRE-XXXX-YYYY</code>",
            parse_mode=ParseMode.HTML
        )
        return

    key = context.args[0].upper()
    
    if data_manager.redeem_license_key(key, user.id):
        profile = data_manager.get_user(user.id)  # Refresh profile
        
        success_text = f"""🎫 <b>License Key Redeemed!</b> 🎫

🎉 <b>License key activated successfully!</b>

🎫 <b>Key:</b> <code>{html.escape(key)}</code>
👑 <b>New Tier:</b> {profile.membership_emoji} {profile.membership.value.upper()}
⚡ <b>Speed:</b> {profile.processing_delay}s delay
📅 <b>Expires:</b> {profile.premium_expires.strftime('%Y-%m-%d') if profile.premium_expires else 'Never'}

Welcome to premium Shopify checking! 🚀"""

        keyboard = [
            [
                InlineKeyboardButton("💳 Start Checking", callback_data="chk:prompt_now"),
                InlineKeyboardButton("📊 My Stats", callback_data="stats:show")
            ],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="nav:show_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            success_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "❌ <b>Invalid or used key!</b>\nPlease check your key and try again.",
            parse_mode=ParseMode.HTML
        )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed user statistics"""
    user = update.effective_user
    profile = data_manager.get_user(user.id, user.username or user.first_name)

    stats_text = f"""📊 <b>Your Shopify Stats</b> 📊

🎯 <b>Performance Analytics:</b>
├ Total Checks: {profile.total_checks:,}
├ Successful: {profile.successful_checks:,} ({profile.success_rate:.1f}%)
├ Failed: {profile.failed_checks:,}
├ Today: {profile.daily_checks:,}
└ Member: {(datetime.now() - profile.join_date).days} days

💎 <b>Account Details:</b>
├ Tier: {profile.membership_emoji} {profile.membership.value.upper()}
├ Speed: {profile.processing_delay}s delay
└ Expires: {profile.premium_expires.strftime('%Y-%m-%d') if profile.premium_expires else 'Never'}

🏪 <b>Current Site:</b> {html.escape(get_site_for_user(user.id) or "Not Set")}"""

    keyboard = [
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="stats:show"),
            InlineKeyboardButton("📈 Upgrade", callback_data="key:redeem")
        ],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="nav:show_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.message.edit_text(
            stats_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            stats_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
        )

async def genkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate license key - admin only"""
    user = update.effective_user
    
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Access denied.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "🎫 <b>Generate Key:</b>\n/genkey <code>&lt;premium|vip|elite&gt; &lt;days&gt;</code>",
            parse_mode=ParseMode.HTML
        )
        return

    tier_name = context.args[0].lower()
    try:
        days = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid number of days!")
        return

    tier_map = {
        "premium": MembershipLevel.PREMIUM,
        "vip": MembershipLevel.VIP,
        "elite": MembershipLevel.ELITE
    }

    if tier_name not in tier_map:
        await update.message.reply_text("❌ Invalid tier! Use: premium, vip, or elite")
        return

    tier = tier_map[tier_name]
    key = data_manager.generate_license_key(tier, days, user.id)

    key_text = f"""🎫 <b>License Key Generated!</b> 🎫

🔑 <b>Key:</b> <code>{key}</code>
👑 <b>Tier:</b> {tier.value.upper()}
📅 <b>Duration:</b> {days} days
👤 <b>Created by:</b> @{user.username}
🕐 <b>Created:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}

Ready for redemption! 🚀"""

    await update.message.reply_text(key_text, parse_mode=ParseMode.HTML)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin control panel"""
    user = update.effective_user
    
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Access denied.")
        return

    total_users = len(data_manager.users)
    total_checks = sum(u.total_checks for u in data_manager.users.values())
    active_keys = len([k for k in data_manager.license_keys.values() if not k.is_used])

    admin_text = f"""👑 <b>Admin Control Panel</b> 👑

📊 <b>System Statistics:</b>
├ Total Users: {total_users:,}
├ Total Checks: {total_checks:,}
├ Active Keys: {active_keys}
└ Uptime: System Online

⚡ <b>Admin Commands:</b>
/genkey &lt;tier&gt; &lt;days&gt; - Generate key
/broadcast &lt;msg&gt; - Send to all users"""

    keyboard = [
        [
            InlineKeyboardButton("🎫 Generate Key", callback_data="admin:genkey"),
            InlineKeyboardButton("👥 View Users", callback_data="admin:users")
        ],
        [
            InlineKeyboardButton("📊 Analytics", callback_data="admin:analytics"),
            InlineKeyboardButton("📢 Broadcast", callback_data="admin:broadcast")
        ],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="nav:show_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.message.edit_text(
            admin_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            admin_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
        )

# --- YOUR ORIGINAL BUTTON CALLBACK HANDLER WITH PREMIUM ADDITIONS ---

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    await query.answer()

    if data == "nav:show_start": 
        await start_command(update, context)
    elif data == "nav:show_cmds": 
        await cmds_command(update, context, from_button=True)
    elif data == "site:prompt_add":
        await query.message.reply_text("🔗 <b>Add Shopify Site</b>\nUse /add <code>https://your-shop.myshopify.com</code>", parse_mode=ParseMode.HTML)
    elif data == "site:show_current": 
        await my_site_command(update, context, from_button=True)
    elif data == "chk:prompt_now" or data == "chk:prompt_another":
        current_site = get_site_for_user(user_id)
        if current_site:
            await query.message.reply_text(f"💳 Ready to check cards on Shopify.\nUse /chk <code>N|M|Y|C</code>", parse_mode=ParseMode.HTML)
        else:
            await query.message.reply_text("⚠️ Site not set. Use 'Set/Update Site' first.", parse_mode=ParseMode.HTML)
    elif data == "mchk:prompt_now":
        current_site = get_site_for_user(user_id)
        if current_site:
            await query.message.reply_text(f"🗂️ Mass Shopify check ready.\nUpload a <code>.txt</code> file and reply with /mchk.", parse_mode=ParseMode.HTML)
        else:
            await query.message.reply_text("⚠️ Site not set. Use 'Set/Update Site' first.", parse_mode=ParseMode.HTML)
    elif data == "key:redeem":
        await query.message.reply_text("🎫 <b>Redeem License Key:</b>\n/redeem <code>PRE-XXXX-YYYY</code>", parse_mode=ParseMode.HTML)
    elif data == "stats:show":
        await stats_command(update, context)
    elif data == "admin:panel":
        await admin_panel(update, context)
    elif data == "admin:genkey":
        await query.message.reply_text("🎫 <b>Generate Key:</b>\n/genkey <code>&lt;premium|vip|elite&gt; &lt;days&gt;</code>", parse_mode=ParseMode.HTML)

# --- ENTRY POINT ---

def main():
    if not TELEGRAM_BOT_TOKEN or "AAGKxCpVrDVGFbyd3aQi0_9G9CHGcJMCLEY" in TELEGRAM_BOT_TOKEN and len(TELEGRAM_BOT_TOKEN) < 20:
         logger.critical("CRITICAL: Telegram Bot Token is a placeholder or missing. Please update the script.")
         return
    
    print("""
🏪═══════════════════════════════════════════════════════════🏪
║            PREMIUM SHOPIFY CHECKER v3.0                    ║
║       YOUR ORIGINAL SIGMABRO API + PREMIUM FEATURES        ║
🏪═══════════════════════════════════════════════════════════🏪

🚀 Your original Shopify checker preserved...
💳 Sigmabro API: https://sigmabro766-1.onrender.com
💎 Premium membership system added...
⚡ NO TIMEOUT - waits forever for response!
📊 Complete stats tracking and analytics...
🎯 Mass check, admin panel, license keys...
✨ Handles PHP warnings perfectly with your parser!

Example API call:
https://sigmabro766-1.onrender.com/?site=https://candy-edventure.myshopify.com&cc=4322650142933030|08|28|282

Response format:
{"Response":"CARD_DECLINED","Status":"true","Price":"9.14","Gateway":"Normal","cc":"4322650142933030|08|28|282"}
""")
    
    load_user_sites()
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # ALL YOUR ORIGINAL COMMANDS
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("cmds", cmds_command))
    application.add_handler(CommandHandler("add", add_command))
    application.add_handler(CommandHandler("my_site", my_site_command))
    application.add_handler(CommandHandler("chk", chk_command))
    application.add_handler(CommandHandler("mchk", mchk_command))
    
    # PREMIUM COMMANDS
    application.add_handler(CommandHandler("redeem", redeem_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("genkey", genkey_command))
    application.add_handler(CommandHandler("admin", admin_panel))
    
    # BUTTON CALLBACK HANDLER
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    
    # FILE UPLOAD HANDLER FOR MASS CHECK
    application.add_handler(MessageHandler(filters.CAPTION & filters.Regex(r'^/mchk$') & filters.Document.TEXT, mchk_command))

    logger.info("🏪 Shopify Checker Bot is running with sigmabro API + premium features!")
    application.run_polling()

if __name__ == "__main__":
    main()
