import asyncio
import httpx
import json
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

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
from telegram.constants import ParseMode, ChatAction


# ═══════════════════════════════════════════════════════════════════════════════
# 🎯 CORE CONFIGURATION & SETUP
# ═══════════════════════════════════════════════════════════════════════════════

# Create directories FIRST, before logging setup
Path("data").mkdir(exist_ok=True)
Path("logs").mkdir(exist_ok=True)

# Premium logging setup (AFTER directory creation)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("logs/premium_bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Premium configuration
TELEGRAM_BOT_TOKEN = "7615802418:AAGKxCpVrDVGFbyd3aQi0_9G9CHGcJMCLEY"
CHECKER_API_URL = "https://sigmabro766-1.onrender.com"
BINLIST_API_URL = "https://lookup.binlist.net/"

# Admin configuration (Add your Telegram user IDs here)
ADMIN_IDS = [7675426356, 987654321]  # Replace with actual admin Telegram IDs

# Premium headers
COMMON_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}


# ═══════════════════════════════════════════════════════════════════════════════
# 💎 PREMIUM DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════

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
    current_site: Optional[str] = None
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


# ═══════════════════════════════════════════════════════════════════════════════
# 🎨 PREMIUM UI COMPONENTS
# ═══════════════════════════════════════════════════════════════════════════════

class PremiumUI:
    # Premium spinners for different tiers
    SPINNERS = {
        MembershipLevel.FREE: ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
        MembershipLevel.PREMIUM: ["💎", "✨", "💫", "⭐", "🌟", "✨", "💫", "⭐"],
        MembershipLevel.VIP: ["👑", "💎", "🔥", "⚡", "🚀", "💎", "🔥", "⚡"],
        MembershipLevel.ELITE: ["⭐", "🌟", "✨", "💫", "🔥", "⚡", "🚀", "💎"]
    }

    @staticmethod
    def create_header(title: str, width: int = 35) -> str:
        """Create a premium box-drawing header"""
        padding = max(0, width - len(title) - 2)
        left_pad = padding // 2
        right_pad = padding - left_pad
        
        return f"""╔{'═' * width}╗
║{' ' * left_pad}{title}{' ' * right_pad}║
╚{'═' * width}╝"""

    @staticmethod
    def create_progress_bar(progress: float, width: int = 20) -> str:
        """Create an animated progress bar"""
        filled = int(progress * width)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}] {progress:.1%}"

    @staticmethod
    def create_stats_box(user: UserProfile) -> str:
        """Create a premium stats display"""
        return f"""┌─── 📊 YOUR STATS ───┐
│ Success Rate: {PremiumUI.create_progress_bar(user.success_rate/100, 10)} {user.success_rate:.1f}% │
│ Total Checks: {user.total_checks:,} │
│ Member Since: {(datetime.now() - user.join_date).days} days │
│ Membership: {user.membership_emoji} {user.membership.value.upper()} │
└─────────────────────────────────┘"""


# ═══════════════════════════════════════════════════════════════════════════════
# 💾 PREMIUM DATA MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class DataManager:
    def __init__(self):
        self.users: Dict[int, UserProfile] = {}
        self.license_keys: Dict[str, LicenseKey] = {}
        self._lock = threading.Lock()
        self._load_all_data()

    def _load_all_data(self):
        """Load all persistent data"""
        try:
            # Load user profiles
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

            # Load license keys
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
        """Save all data atomically"""
        with self._lock:
            try:
                # Save user profiles
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

                # Save license keys
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
        """Get or create user profile"""
        if user_id not in self.users:
            self.users[user_id] = UserProfile(user_id=user_id, username=username)
            self._save_all_data()
        else:
            # Update username if provided
            if username and self.users[user_id].username != username:
                self.users[user_id].username = username
                self._save_all_data()
        
        # Check daily reset
        user = self.users[user_id]
        if datetime.now().date() > user.last_daily_reset.date():
            user.daily_checks = 0
            user.last_daily_reset = datetime.now()
            self._save_all_data()
        
        user.last_active = datetime.now()
        return user

    def update_user(self, user: UserProfile):
        """Update user profile"""
        self.users[user.user_id] = user
        self._save_all_data()

    def generate_license_key(self, tier: MembershipLevel, duration_days: int, created_by: int) -> str:
        """Generate a new license key"""
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
        """Redeem a license key"""
        if key not in self.license_keys or self.license_keys[key].is_used:
            return False
        
        license_key = self.license_keys[key]
        license_key.is_used = True
        license_key.used_by = user_id
        license_key.used_at = datetime.now()
        
        # Update user membership
        user = self.users[user_id]
        user.membership = license_key.tier
        user.premium_expires = datetime.now() + timedelta(days=license_key.duration_days)
        
        self._save_all_data()
        return True


# ═══════════════════════════════════════════════════════════════════════════════
# 🔧 YOUR ORIGINAL WORKING FUNCTIONS - FIXED FOR TIMEOUT ONLY
# ═══════════════════════════════════════════════════════════════════════════════

# UI/Spinner Helpers from your original code
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

# Your original BIN function
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

# Your original parser function - WORKING!
def parse_checker_api_response(response_text: str):
    """
    YOUR ORIGINAL WORKING PARSER
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


# ═══════════════════════════════════════════════════════════════════════════════
# 👑 PREMIUM BOT CLASS - USING YOUR ORIGINAL LOGIC
# ═══════════════════════════════════════════════════════════════════════════════

class PremiumBot:
    def __init__(self):
        self.data_manager = DataManager()
        self.ui = PremiumUI()

    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return user_id in ADMIN_IDS

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Premium start command with beautiful UI"""
        user = update.effective_user
        profile = self.data_manager.get_user(user.id, user.username or user.first_name)
        
        welcome_text = f"""<pre>{self.ui.create_header("PREMIUM CHECKER v2.0")}</pre>

Welcome back, <b>{html.escape(profile.username)}</b> {profile.membership_emoji}

{self.ui.create_stats_box(profile)}

<pre>🚀 System Status: Online</pre>
<pre>⚡ Your Speed: {profile.membership.value.upper()} ({profile.processing_delay}s delay)</pre>"""

        keyboard = [
            [
                InlineKeyboardButton("🔗 Set Site", callback_data="site:set"),
                InlineKeyboardButton("📊 My Stats", callback_data="stats:show")
            ],
            [
                InlineKeyboardButton("💳 Single Check", callback_data="check:single"),
                InlineKeyboardButton("🗂️ Mass Check", callback_data="check:mass")
            ],
            [
                InlineKeyboardButton("🎫 Redeem Key", callback_data="key:redeem"),
                InlineKeyboardButton("📖 Commands", callback_data="help:commands")
            ]
        ]

        # Add admin button for admins
        if self.is_admin(user.id):
            keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin:panel")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:
            try:
                await update.callback_query.message.edit_text(
                    welcome_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=welcome_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
        else:
            await update.message.reply_text(
                welcome_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
            )

    async def chk_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """YOUR ORIGINAL CHK COMMAND - JUST FIXED TIMEOUT"""
        user_id = update.effective_user.id
        profile = self.data_manager.get_user(user_id, update.effective_user.username or update.effective_user.first_name)
        telegram_user = update.effective_user
        user_display_name = html.escape(telegram_user.username if telegram_user.username else telegram_user.first_name)

        if not profile.current_site:
            await update.message.reply_text("⚠️ No Shopify site set. Use /setsite <code>&lt;site_url&gt;</code> first.", parse_mode=ParseMode.HTML)
            return
        if not context.args:
            await update.message.reply_text("⚠️ Card details missing.\nFormat: /check <code>N|M|Y|C</code>", parse_mode=ParseMode.HTML)
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

        params = {"site": profile.current_site, "cc": cc_details_full}
        final_card_status_text = "Error Initializing Check"
        final_card_status_emoji = "❓"
        final_api_response_display = "N/A"
        checker_api_gateway = "N/A"
        checker_api_price = "0.00"

        try:
            async with httpx.AsyncClient(headers=COMMON_HTTP_HEADERS, timeout=120.0) as client:  # INCREASED TIMEOUT HERE
                response = await client.get(CHECKER_API_URL, params=params)

            if response.status_code == 200:
                # **YOUR ORIGINAL WORKING PARSER**
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

        except httpx.TimeoutException:
            final_card_status_emoji = "⏱️"
            final_card_status_text = "API Timeout"
            final_api_response_display = "Request to checker API timed out after 120 seconds."
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

        # Update user stats
        profile.total_checks += 1
        profile.daily_checks += 1
        self.data_manager.update_user(profile)

        # --- YOUR ORIGINAL FORMATTING ---
        escaped_cc_details = html.escape(cc_details_full)
        escaped_shopify_site = html.escape(profile.current_site)
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
            [InlineKeyboardButton("💳 Check Another", callback_data="check:single")],
            [
                InlineKeyboardButton("🔗 Change Site", callback_data="site:set"),
                InlineKeyboardButton("« Main Menu", callback_data="nav:start")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard_buttons)
        await update.message.reply_text(result_message, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

    async def setsite_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set target site"""
        user = update.effective_user
        profile = self.data_manager.get_user(user.id, user.username or user.first_name)

        if not context.args:
            await update.message.reply_text(
                "🔗 <b>Set Target Site:</b>\n/setsite <code>https://your-shopify-site.com</code>",
                parse_mode=ParseMode.HTML
            )
            return

        site_url = context.args[0]
        if not (site_url.startswith("http://") or site_url.startswith("https://")):
            await update.message.reply_text(
                "⚠️ <b>Invalid URL!</b> Must start with http:// or https://",
                parse_mode=ParseMode.HTML
            )
            return

        profile.current_site = site_url
        self.data_manager.update_user(profile)

        response_text = f"""<pre>{self.ui.create_header("SITE CONFIGURED")}</pre>

✅ <b>Target site updated successfully!</b>

<pre>🔗 Target: {html.escape(site_url)}</pre>
<pre>🚀 Speed: {profile.membership.value.upper()} Tier</pre>
<pre>📊 Ready for checks!</pre>"""

        keyboard = [
            [
                InlineKeyboardButton("💳 Single Check", callback_data="check:single"),
                InlineKeyboardButton("🗂️ Mass Check", callback_data="check:mass")
            ],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="nav:start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            response_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup
        )

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user statistics"""
        user = update.effective_user
        profile = self.data_manager.get_user(user.id, user.username or user.first_name)

        stats_text = f"""<pre>{self.ui.create_header("YOUR PREMIUM STATS")}</pre>

{self.ui.create_stats_box(profile)}

<pre>📈 Detailed Analytics:</pre>
<pre>├ Total Checks: {profile.total_checks:,}</pre>
<pre>├ Successful: {profile.successful_checks:,}</pre>
<pre>├ Failed: {profile.failed_checks:,}</pre>
<pre>├ Today: {profile.daily_checks:,}</pre>
<pre>└ Speed Tier: {profile.membership.value.upper()}</pre>

<pre>🎯 Current Site: {html.escape(profile.current_site or "Not Set")}</pre>"""

        keyboard = [
            [
                InlineKeyboardButton("🔄 Refresh", callback_data="stats:show"),
                InlineKeyboardButton("📈 Upgrade", callback_data="upgrade:info")
            ],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="nav:start")]
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

    async def redeem_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Redeem license key"""
        user = update.effective_user
        profile = self.data_manager.get_user(user.id, user.username or user.first_name)

        if not context.args:
            await update.message.reply_text(
                "🎫 <b>Redeem License Key:</b>\n/redeem <code>PRE-XXXX-YYYY</code>",
                parse_mode=ParseMode.HTML
            )
            return

        key = context.args[0].upper()
        
        if self.data_manager.redeem_license_key(key, user.id):
            profile = self.data_manager.get_user(user.id)  # Refresh profile
            
            success_text = f"""<pre>{self.ui.create_header("KEY REDEEMED!")}</pre>

🎉 <b>License key activated successfully!</b>

<pre>🎫 Key: {html.escape(key)}</pre>
<pre>👑 New Tier: {profile.membership_emoji} {profile.membership.value.upper()}</pre>
<pre>⚡ Speed: {profile.processing_delay}s delay</pre>
<pre>📅 Expires: {profile.premium_expires.strftime('%Y-%m-%d') if profile.premium_expires else 'Never'}</pre>

Welcome to the premium experience! 🚀"""

            keyboard = [
                [
                    InlineKeyboardButton("💳 Start Checking", callback_data="check:single"),
                    InlineKeyboardButton("📊 My Stats", callback_data="stats:show")
                ],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="nav:start")]
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

    async def genkey_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Generate license key - admin only"""
        user = update.effective_user
        
        if not self.is_admin(user.id):
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
        key = self.data_manager.generate_license_key(tier, days, user.id)

        key_text = f"""<pre>{self.ui.create_header("LICENSE KEY GENERATED")}</pre>

🎫 <b>New License Key Created!</b>

<pre>🔑 Key: {key}</pre>
<pre>👑 Tier: {tier.value.upper()}</pre>
<pre>📅 Duration: {days} days</pre>
<pre>👤 Created by: @{user.username}</pre>
<pre>🕐 Created: {datetime.now().strftime('%Y-%m-%d %H:%M')}</pre>

Ready for redemption! 🚀"""

        await update.message.reply_text(key_text, parse_mode=ParseMode.HTML)

    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all callback queries"""
        query = update.callback_query
        data = query.data
        await query.answer()

        if data == "nav:start":
            await self.start_command(update, context)
        elif data == "stats:show":
            await self.stats_command(update, context)
        elif data == "site:set":
            await query.message.reply_text(
                "🔗 <b>Set Target Site:</b>\n/setsite <code>https://your-shopify-site.com</code>",
                parse_mode=ParseMode.HTML
            )
        elif data == "check:single":
            await query.message.reply_text(
                "💳 <b>Single Check:</b>\n/check <code>1234567890123456|12|25|123</code>",
                parse_mode=ParseMode.HTML
            )
        elif data == "key:redeem":
            await query.message.reply_text(
                "🎫 <b>Redeem License Key:</b>\n/redeem <code>PRE-XXXX-YYYY</code>",
                parse_mode=ParseMode.HTML
            )


def main():
    """Initialize and run the premium bot"""
    print(f"""
╔═══════════════════════════════════════════════════════════╗
║               PREMIUM SHOPIFY CHECKER v2.0                ║
║                  USING ORIGINAL LOGIC                     ║
╚═══════════════════════════════════════════════════════════╝

🚀 Using your original working functions...
💎 Just fixed the timeout issue...
⚡ Ready to rock!
""")

    bot = PremiumBot()
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register handlers
    application.add_handler(CommandHandler("start", bot.start_command))
    application.add_handler(CommandHandler("check", bot.chk_command))
    application.add_handler(CommandHandler("setsite", bot.setsite_command))
    application.add_handler(CommandHandler("stats", bot.stats_command))
    application.add_handler(CommandHandler("redeem", bot.redeem_command))
    application.add_handler(CommandHandler("genkey", bot.genkey_command))
    application.add_handler(CallbackQueryHandler(bot.callback_handler))

    logger.info("🚀 Premium Bot with original logic is running!")
    application.run_polling()


if __name__ == "__main__":
    main()
