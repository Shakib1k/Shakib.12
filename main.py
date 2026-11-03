import os
import time
import uuid
import json
import logging
import html
import re
from datetime import datetime, timedelta
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import threading
import random
import sys
import hashlib
import asyncio
import requests
from types import SimpleNamespace

# =====================================================
#           🔐 USERBOT & AI INTEGRATION
# =====================================================
try:
    import userbot as ub_module
    USERBOT_AVAILABLE = True
except ImportError:
    USERBOT_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.error("userbot.py not found or dependencies missing!")

USERBOT_LOOP = asyncio.new_event_loop()

def _run_userbot_loop():
    asyncio.set_event_loop(USERBOT_LOOP)
    USERBOT_LOOP.run_forever()

threading.Thread(target=_run_userbot_loop, daemon=True).start()

def run_async(coro):
    future = asyncio.run_coroutine_threadsafe(coro, USERBOT_LOOP)
    return future.result(timeout=60)

# =====================================================
#           🔐 ADMIN AUTH
# =====================================================

# Set ADMIN_PASSWORD and BOT_TOKEN as environment variables before starting the bot.
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()  # Set a strong value in Render -> Environment
ADMIN_PASSWORD_HASH = hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()
SESSION_FILE = "admin_session.json"

def load_session():
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_session(data):
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return True
    except:
        return False

def verify_admin_password(password):
    return hashlib.sha256(password.encode()).hexdigest() == ADMIN_PASSWORD_HASH

def is_admin_logged_in(user_id):
    # Admin login is stored in the main database and remains active until Logout.
    session = user_sessions.get(user_id, {})
    if session.get("logged_in", False):
        return True

    saved = db.get("admin_sessions", {}).get(str(user_id), {})
    if saved.get("logged_in", False):
        try:
            login_time = datetime.fromisoformat(saved.get("login_time", datetime.now().isoformat()))
        except (TypeError, ValueError):
            login_time = datetime.now()
        user_sessions[user_id] = {
            "logged_in": True, "login_time": login_time,
            "remember": True, "auto_login": True
        }
        return True

    legacy = load_session()
    old = legacy.get(str(user_id), {})
    if old.get("logged_in", False):
        user_sessions[user_id] = {
            "logged_in": True, "login_time": datetime.now(),
            "remember": True, "auto_login": True
        }
        db.setdefault("admin_sessions", {})[str(user_id)] = {
            "logged_in": True,
            "login_time": old.get("login_time", datetime.now().isoformat())
        }
        sync_db()
        return True
    return False


def login_admin(user_id, password, remember=True):
    if not verify_admin_password(password):
        return False
    login_time = datetime.now()
    user_sessions[user_id] = {
        "logged_in": True, "login_time": login_time,
        "remember": True, "auto_login": True
    }
    db.setdefault("admin_sessions", {})[str(user_id)] = {
        "logged_in": True, "login_time": login_time.isoformat()
    }
    sync_db()
    return True


def logout_admin(user_id):
    user_sessions[user_id] = {
        "logged_in": False, "login_time": None,
        "remember": False, "auto_login": False
    }
    db.setdefault("admin_sessions", {}).pop(str(user_id), None)
    sync_db()
    saved = load_session()
    saved.pop(str(user_id), None)
    save_session(saved)
    return True

user_sessions = {}
live_schedule_messages = {}  
live_deletion_messages = {} 
BOT_NAME = "SHAKIB"

try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False

# =====================================================
#           ⚙️ CONFIG
# =====================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()  # Set in Render -> Environment
ADMIN_ID = 7058712225
DB_FILE = "bot_database.json"
LOG_FILE = "bot_activity.log"
BACKUP_INTERVAL = 300

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

def print_banner():
    os.system('clear' if os.name == 'posix' else 'cls')
    print("\033[96m" + "═" * 55)
    print(f"\033[93m   ✨ {BOT_NAME} PREMIUM BOT ✨   \033[96m")
    print("═" * 55)
    print("\033[92m✅ Bot Ready!\033[0m")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Add BOT_TOKEN in Render -> Environment, then redeploy.")
if not ADMIN_PASSWORD:
    raise RuntimeError("ADMIN_PASSWORD is missing. Add a strong ADMIN_PASSWORD in Render -> Environment, then redeploy.")

bot = telebot.TeleBot(BOT_TOKEN)

# =====================================================
#   ✅ HELPER FUNCTIONS (Auto Clean)
# =====================================================

def clean_msg(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass

def send_clean_prompt(chat_id, text, reply_markup=None, parse_mode=None):
    st = user_states.get(chat_id)
    if isinstance(st, dict) and "last_bot_msg" in st:
        clean_msg(chat_id, st["last_bot_msg"])
    
    msg = bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    
    if isinstance(user_states.get(chat_id), dict):
        user_states[chat_id]["last_bot_msg"] = msg.message_id
    else:
        user_states[chat_id] = {"last_bot_msg": msg.message_id}
    return msg

# =====================================================
#   ✅ SMART PARSERS
# =====================================================

def extract_public_username(text):
    if not text:
        return None
    raw = str(text).strip()
    if raw.startswith("@") and raw[1:].isdigit():
        return None
    if "t.me/" in raw:
        p = raw.split("t.me/")[-1].strip("/").split("/")[0].split("?")[0]
        if p.startswith("+") or p.startswith("joinchat"):
            return None
        if p:
            return "@" + p
    if raw.startswith("@") and len(raw) > 1:
        u = raw[1:].split("/")[0].split("?")[0]
        if u.isdigit():
            return None
        return "@" + u
    if not raw.startswith("-") and not raw.startswith("http") and " " not in raw and "/" not in raw:
        return "@" + raw
    return None

def extract_join_url(text):
    if not text:
        return None
    raw = str(text).strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if raw.startswith("@"):
        return f"https://t.me/{raw[1:]}"
    if not raw.startswith("-") and not raw.startswith("+") and " " not in raw:
        return f"https://t.me/{raw}"
    return None

def extract_chat_id(text):
    if not text:
        return None
    raw = str(text).strip()
    if "|" in raw:
        raw = raw.split("|")[0].strip()
    if raw.startswith("@") and raw[1:].isdigit():
        d = raw[1:]
        return "-" + d if d.startswith("100") else "-100" + d
    if raw.startswith("@-"):
        f = raw[1:]
        if f.startswith("-100") and f[4:].isdigit():
            return f
    if raw.isdigit() and len(raw) >= 10:
        return "-" + raw if raw.startswith("100") else "-100" + raw
    if raw.startswith("-100") and raw[4:].isdigit():
        return raw
    if raw.startswith("-") and raw[1:].isdigit():
        return raw
    return None

def validate_channel(identifier):
    if not identifier:
        return None
    try:
        chat = bot.get_chat(identifier)
        return {
            "id": chat.id,
            "title": chat.title or chat.first_name or "Unknown",
            "username": chat.username,
            "type": chat.type
        }
    except Exception as e:
        logger.error(f"Validate error ({identifier}): {e}")
        return None

def check_bot_admin(chat_id):
    try:
        bi = bot.get_me()
        m = bot.get_chat_member(chat_id, bi.id)
        return m.status in ['administrator', 'creator']
    except Exception as e:
        logger.error(f"Bot admin check error: {e}")
        return False

def check_bot_delete_permission(chat_id):
    try:
        bi = bot.get_me()
        m = bot.get_chat_member(chat_id, bi.id)
        if m.status in ['administrator', 'creator']:
            if getattr(m, 'can_delete_messages', False):
                return True
        return False
    except Exception as e:
            logger.error(f"Permission check error: {e}")
            return False

# =====================================================
#   ✅ CHANNEL SYSTEM
# =====================================================

def get_all_channels():
    channels = []
    try:
        if isinstance(bot_settings.get("channels"), list):
            for ch in bot_settings["channels"]:
                if ch:
                    channels.append({
                        "id": ch.get("id", "ch_" + str(uuid.uuid4().hex[:6])),
                        "name": ch.get("name", "Channel"),
                        "type": ch.get("type", "unknown"),
                        "join_url": ch.get("join_url", ""),
                        "chat_id": ch.get("chat_id", "")
                    })
    except Exception as e:
        logger.error(f"get_all_channels error: {e}")
    return channels

def add_channel(name, ch_type, join_url, chat_id):
    if "channels" not in bot_settings or not isinstance(bot_settings["channels"], list):
        bot_settings["channels"] = []
    new_ch = {
        "id": "ch_" + str(uuid.uuid4().hex[:8]),
        "name": name,
        "type": ch_type,
        "join_url": join_url or "",
        "chat_id": str(chat_id) if chat_id else "",
        "added_at": datetime.now().isoformat()
    }
    bot_settings["channels"].append(new_ch)
    sync_db()
    return new_ch

def remove_channel_by_id(ch_id):
    if isinstance(bot_settings.get("channels"), list):
        bot_settings["channels"] = [c for c in bot_settings["channels"] if c.get("id") != ch_id]
    sync_db()

def get_unjoined_channels(user_id):
    unjoined = []
    if not bot_settings.get("force_join", True):
        return unjoined
    for ch in get_all_channels():
        try:
            chat_id = ch.get("chat_id", "").strip()
            join_url = ch.get("join_url", "").strip()
            identifier = None
            if chat_id:
                if chat_id.startswith("@"):
                    identifier = chat_id
                elif chat_id.startswith("-"):
                    identifier = chat_id
            elif ch.get("type") == "public" and join_url:
                identifier = extract_public_username(join_url)
            if not identifier:
                continue
            member = bot.get_chat_member(identifier, user_id)
            if member.status in ['left', 'kicked']:
                unjoined.append(ch)
        except Exception as e:
            logger.error(f"Membership check error ({ch.get('name')}): {e}")
            continue
    return unjoined

def get_join_message(unjoined):
    title = bot_settings.get("force_join_title", "🔒 ACCESS RESTRICTED")
    msg_body = bot_settings.get("force_join_message", "📌 Join {count} channel(s) to continue")
    try:
        body = msg_body.replace("{count}", str(len(unjoined)))
    except:
        body = msg_body
    return f"{title}\n\n{body}".strip()

def get_my_admin_channels():
    result = []
    try:
        bi = bot.get_me()
        for ch in get_all_channels():
            try:
                identifier = ch.get("chat_id") or ch.get("join_url", "")
                if not identifier:
                    continue
                if not str(identifier).startswith("-") and not str(identifier).startswith("@"):
                    identifier = extract_public_username(identifier)
                if not identifier:
                    continue
                try:
                    member = bot.get_chat_member(identifier, bi.id)
                    if member.status in ['administrator', 'creator']:
                        info = validate_channel(identifier)
                        result.append({
                            "id": ch.get("id"),
                            "name": ch.get("name", "Channel"),
                            "chat_id": identifier,
                            "title": info["title"] if info else ch.get("name", "Channel"),
                            "username": info["username"] if info else None
                        })
                except:
                    continue
            except:
                continue
    except:
        pass
    return result

# =====================================================
#           💾 DATABASE
# =====================================================

def get_default_db():
    return {
        "file_database": {},
        "project_files": [],
        "admin_sessions": {},
        "registered_users": [],
        "banned_users": [],
        "user_activity": {},
        "user_ranks": {},
        "bot_settings": {
            "force_join": True,
            "force_join_title": "🔒 ACCESS RESTRICTED",
            "force_join_message": "📌 Join {count} channel(s) to continue",
            "channels": [],
            "custom_commands": {},
            "maintenance_mode": False,
            "welcome_message": f"✨ Welcome to {BOT_NAME} Premium Bot! ✨\n\n👋 Hello {{name}}!",
            "auto_delete": False,
            "delete_after": 60,
            "log_channel": None,
            "auto_reply": {},
            "referral_bonus": 5,
            "daily_reward": 10,
            "sub_admins": [],
            "admin_password": ADMIN_PASSWORD_HASH,
            "conn_sources": [],
            "conn_dest": "",
            "conn_settings": {"copy_text": True, "copy_files": True, "copy_links": True},
            "reaction_bots": [],
            "saved_bot_tokens": [],
            "user_limit_enabled": True
        },
        "scheduled_messages": [],
        "scheduled_posts": [],
        "scheduled_deletions": [],
        "giveaway": {"active": False, "prize": "", "participants": [], "end_time": None, "winners": []},
        "referrals": {}
    }

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                default = get_default_db()
                for k in default:
                    if k not in data:
                        data[k] = default[k]
                for k in default["bot_settings"]:
                    if k not in data["bot_settings"]:
                        data["bot_settings"][k] = default["bot_settings"][k]
                for k in default["giveaway"]:
                    if k not in data["giveaway"]:
                        data["giveaway"][k] = default["giveaway"][k]
                if not isinstance(data["bot_settings"].get("channels"), list):
                    data["bot_settings"]["channels"] = []
                if not isinstance(data.get("scheduled_posts"), list):
                    data["scheduled_posts"] = []
                if not isinstance(data.get("scheduled_deletions"), list):
                    data["scheduled_deletions"] = []
                return data
        except Exception as e:
            logger.error(f"DB load error: {e}")
            return get_default_db()
    return get_default_db()

def save_db(data):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        with open(f"{DB_FILE}.backup", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
            logger.error(f"DB save error: {e}")

db = load_db()
file_database = db["file_database"]
registered_users = set(db["registered_users"])
banned_users = set(db.get("banned_users", []))
user_activity = db.get("user_activity", {})
bot_settings = db["bot_settings"]
scheduled_messages = db.get("scheduled_messages", [])
scheduled_posts = db.get("scheduled_posts", [])
scheduled_deletions = db.get("scheduled_deletions", [])
giveaway = db.get("giveaway", {"active": False, "prize": "", "participants": [], "end_time": None, "winners": []})
referrals = db.get("referrals", {})
user_states = {}
data_lock = threading.Lock()

def sync_db():
    with data_lock:
        db["file_database"] = file_database
        db["project_files"] = db.get("project_files", [])
        db.setdefault("admin_sessions", {})
        db["registered_users"] = list(registered_users)
        db["banned_users"] = list(banned_users)
        db["user_activity"] = user_activity
        db["bot_settings"] = bot_settings
        db["scheduled_messages"] = scheduled_messages
        db["scheduled_posts"] = scheduled_posts
        db["scheduled_deletions"] = scheduled_deletions
        db["giveaway"] = giveaway
        db["referrals"] = referrals
        save_db(db)

def auto_backup():
    while True:
        try:
            time.sleep(BACKUP_INTERVAL)
            sync_db()
        except Exception as e:
            logger.error(f"Backup error: {e}")

def log_user_activity(user_id, action):
    with data_lock:
        if user_id not in user_activity:
            user_activity[user_id] = {"total_actions": 0, "last_active": None, "actions": [], "points": 0, "rank": "Member"}
        user_activity[user_id]["total_actions"] += 1
        user_activity[user_id]["last_active"] = datetime.now().isoformat()
        if "points" not in user_activity[user_id]:
            user_activity[user_id]["points"] = 0
        if action not in ["voice_generated", "daily_reward"]:
            user_activity[user_id]["points"] += 1
        p = user_activity[user_id]["points"]
        if p >= 100:
            user_activity[user_id]["rank"] = "💎 Diamond"
        elif p >= 50:
            user_activity[user_id]["rank"] = "🥇 Gold"
        elif p >= 25:
            user_activity[user_id]["rank"] = "🥈 Silver"
        elif p >= 10:
            user_activity[user_id]["rank"] = "🥉 Bronze"
    sync_db()

def is_user_banned(user_id):
    return user_id in banned_users

# =====================================================
#           🎨 KEYBOARDS
# =====================================================

def get_join_keyboard(file_id_param=None, unjoined=None):
    markup = InlineKeyboardMarkup(row_width=2)
    if unjoined is None:
        unjoined = get_all_channels()
    join_buttons = []
    for ch in unjoined:
        url = ch.get("join_url", "").strip()
        name = ch.get("name", "Channel")
        if url and (url.startswith("http://") or url.startswith("https://")):
            join_buttons.append(InlineKeyboardButton(text=f"📢 {name}", url=url))
    for i in range(0, len(join_buttons), 2):
        if i + 1 < len(join_buttons):
            markup.row(join_buttons[i], join_buttons[i + 1])
        else:
            markup.row(join_buttons[i])
    callback = f"verify_{file_id_param}" if file_id_param else "check_verification"
    markup.row(InlineKeyboardButton(text="✅ Verify & Continue", callback_data=callback))
    return markup

def get_main_keyboard():
    if not bot_settings.get("user_limit_enabled", True):
        return telebot.types.ReplyKeyboardRemove()
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("🎙️ Voice"), KeyboardButton("📊 Stats"), KeyboardButton("🎁 Daily Reward"))
    markup.add(KeyboardButton("ℹ️ Help"), KeyboardButton("👤 Profile"), KeyboardButton("🏆 Leaderboard"))
    return markup

def get_login_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🔑 Login as Admin", callback_data="admin_login"),
        InlineKeyboardButton("👤 Continue as User", callback_data="continue_as_user")
    )
    markup.add(InlineKeyboardButton("💾 Save & Auto-Login", callback_data="admin_login_save"))
    return markup

def get_admin_panel_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    
    auto = "🔄 Auto-Login: ✅" if is_admin_logged_in(ADMIN_ID) else "🔄 Auto-Login: ❌"
    fs = "✅ Force Join: ON" if bot_settings["force_join"] else "❌ Force Join: OFF"
    ms = "🛠️ Maintenance: ON" if bot_settings.get("maintenance_mode", False) else "🛠️ Maintenance: OFF"
    
    markup.add(
        InlineKeyboardButton(text=auto, callback_data="auto_login_status"),
        InlineKeyboardButton(text=fs, callback_data="toggle_force_join")
    )
    markup.add(
        InlineKeyboardButton(text=ms, callback_data="toggle_maintenance"),
        InlineKeyboardButton("📊 Stats", callback_data="view_stats")
    )
    
    markup.add(
        InlineKeyboardButton("📢 Channel Manager", callback_data="channel_manager"),
        InlineKeyboardButton("🔗 Connect Channel", callback_data="conn_main")
    )
    user_limit_label = "👥 User Limit: ON" if bot_settings.get("user_limit_enabled", True) else "👥 User Limit: OFF"
    markup.add(
        InlineKeyboardButton(user_limit_label, callback_data="toggle_user_limit"),
        InlineKeyboardButton("📁 Project Files", callback_data="project_files_main")
    )
    
    markup.add(
        InlineKeyboardButton("🤖 AI Auto-Reply", callback_data="ub_main"),
        InlineKeyboardButton("🔄 Reset Userbot", callback_data="ub_reset")
    )

    markup.add(
        InlineKeyboardButton("🎭 Reaction Bot", callback_data="rb_main"),
        InlineKeyboardButton("🗑️ Clear All Data", callback_data="admin_clear_data")
    )
    
    markup.add(
        InlineKeyboardButton("📝 Join Text Editor", callback_data="join_text_editor"),
        InlineKeyboardButton("👋 Welcome Msg Editor", callback_data="welcome_editor")
    )
    
    markup.add(
        InlineKeyboardButton("📤 Auto Post Scheduler", callback_data="aps_main"),
        InlineKeyboardButton("🗑️ Delete Channel Msg", callback_data="del_main")
    )
    
    markup.add(
        InlineKeyboardButton("🔑 Create Key", callback_data="admin_create_key"),
        InlineKeyboardButton("📋 View Files", callback_data="admin_view_files")
    )
    markup.add(
        InlineKeyboardButton("🗑️ Delete File", callback_data="admin_delete_file"),
        InlineKeyboardButton("🔑 Keys Count", callback_data="admin_view_keys_count")
    )
    
    markup.add(
        InlineKeyboardButton("👥 Users", callback_data="admin_view_users"),
        InlineKeyboardButton("🎁 Giveaway", callback_data="admin_giveaway")
    )
    markup.add(
        InlineKeyboardButton("⛔ Ban User", callback_data="admin_ban_user"),
        InlineKeyboardButton("✅ Unban User", callback_data="admin_unban_user")
    )
    
    markup.add(
        InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
        InlineKeyboardButton("📝 Auto Reply", callback_data="admin_auto_reply")
    )
    
    markup.add(
        InlineKeyboardButton("📋 Settings", callback_data="view_settings"),
        InlineKeyboardButton("👑 Admins", callback_data="admin_manage_admins")
    )
    
    markup.add(
        InlineKeyboardButton("🚪 Logout", callback_data="admin_logout"),
        InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")
    )
    
    return markup

def get_project_files_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("➕ Add Project", callback_data="project_add"))
    markup.add(InlineKeyboardButton("📋 View Projects", callback_data="project_view"))
    markup.add(InlineKeyboardButton("🗑️ Delete Project", callback_data="project_delete"))
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="back_to_main"))
    return markup


def get_project_confirm_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("💾 Save", callback_data="project_save"),
        InlineKeyboardButton("✖️ Close", callback_data="project_close")
    )
    return markup


def _project_file_kind(message):
    if message.document:
        return message.document.file_id, "document", message.document.file_name or "document"
    if message.photo:
        return message.photo[-1].file_id, "photo", "photo.jpg"
    if message.video:
        return message.video.file_id, "video", message.video.file_name or "video.mp4"
    if message.audio:
        return message.audio.file_id, "audio", message.audio.file_name or "audio"
    if message.voice:
        return message.voice.file_id, "voice", "voice.ogg"
    if message.animation:
        return message.animation.file_id, "animation", message.animation.file_name or "animation.mp4"
    if message.sticker:
        return message.sticker.file_id, "sticker", "sticker.webp"
    if getattr(message, "video_note", None):
        return message.video_note.file_id, "video_note", "video_note.mp4"
    return None, None, None


def _send_project_file(chat_id, item):
    fid = item.get("file_id")
    kind = item.get("file_type", "document")
    caption = f"📁 {html.escape(item.get('name', 'Project'))}\n📎 {html.escape(item.get('file_name', 'file'))}"
    methods = {
        "document": bot.send_document, "photo": bot.send_photo,
        "video": bot.send_video, "audio": bot.send_audio,
        "voice": bot.send_voice, "animation": bot.send_animation,
        "sticker": bot.send_sticker, "video_note": bot.send_video_note
    }
    method = methods.get(kind, bot.send_document)
    if kind in ("sticker", "video_note"):
        method(chat_id, fid)
    else:
        method(chat_id, fid, caption=caption)


def get_rb_main_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("➕ Add Bot", callback_data="rb_add"))
    markup.add(InlineKeyboardButton("💾 Save Bot Tokens", callback_data="rb_saved_main"))
    markup.add(InlineKeyboardButton("👁️ Preview Bot", callback_data="rb_preview"))
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="back_to_main"))
    return markup

def get_rb_remove_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    bots_list = bot_settings.get("reaction_bots", [])
    if not bots_list:
        markup.add(InlineKeyboardButton("❌ No bots found", callback_data="rb_main"))
    else:
        for i, b in enumerate(bots_list):
            emoji = b.get('emoji', '❓')
            bot_id = b.get('bot_id', 'Unknown')
            markup.add(InlineKeyboardButton(f"🗑️ Delete {emoji} {bot_id}", callback_data=f"rb_del_{i}"))
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="rb_main"))
    return markup

def get_ub_main_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("➕ Connect New AI", callback_data="ub_connect"))
    markup.add(InlineKeyboardButton("📋 AI Session List", callback_data="ub_list"))
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="back_to_main"))
    return markup

def get_welcome_editor_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✏️ Edit Welcome Text", callback_data="welcome_edit_text"),
        InlineKeyboardButton("👁️ Live Preview", callback_data="welcome_preview")
    )
    markup.add(InlineKeyboardButton("🔄 Reset to Default", callback_data="welcome_reset"))
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="back_to_main"))
    return markup

def get_conn_main_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("➕ Setup New Connection", callback_data="conn_setup"))
    if bot_settings.get("conn_dest"):
        markup.add(InlineKeyboardButton("📊 View Active Connection", callback_data="conn_view"))
        markup.add(InlineKeyboardButton("⚙️ Copy Settings (Filters)", callback_data="conn_settings"))
        markup.add(InlineKeyboardButton("🔴 Remove Connection", callback_data="conn_remove"))
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="back_to_main"))
    return markup

def get_conn_settings_keyboard():
    settings = bot_settings.get("conn_settings", {"copy_text": True, "copy_files": True, "copy_links": True})
    t_txt = "✅ Copy Text: ON" if settings.get("copy_text", True) else "❌ Copy Text: OFF"
    t_file = "✅ Copy Files: ON" if settings.get("copy_files", True) else "❌ Copy Files: OFF"
    t_link = "✅ Copy Links: ON" if settings.get("copy_links", True) else "❌ Copy Links: OFF"
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton(t_txt, callback_data="conn_toggle_text"))
    markup.add(InlineKeyboardButton(t_file, callback_data="conn_toggle_files"))
    markup.add(InlineKeyboardButton(t_link, callback_data="conn_toggle_links"))
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="conn_main"))
    return markup

def get_channel_manager_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("➕ Add Channel 1", callback_data="ch_add_1"),
        InlineKeyboardButton("➕ Add Channel 2", callback_data="ch_add_2")
    )
    markup.add(InlineKeyboardButton("➕ Add More Channel (3, 4, 5...)", callback_data="ch_add_more"))
    markup.add(InlineKeyboardButton("📋 View All Channels", callback_data="ch_view_all"))
    markup.add(InlineKeyboardButton("🗑️ Delete a Channel", callback_data="ch_delete_menu"))
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="back_to_main"))
    return markup

def get_channel_type_keyboard(slot):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🌐 Public Channel", callback_data=f"chtype_public_{slot}"),
        InlineKeyboardButton("🔒 Private Channel", callback_data=f"chtype_private_{slot}")
    )
    markup.add(InlineKeyboardButton("🔙 Cancel", callback_data="channel_manager"))
    return markup

def get_channel_type_keyboard_for_more(name):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🌐 Public Channel", callback_data="chtype_more_public"),
        InlineKeyboardButton("🔒 Private Channel", callback_data="chtype_more_private")
    )
    markup.add(InlineKeyboardButton("🔙 Cancel", callback_data="channel_manager"))
    return markup

def get_join_text_editor_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✏️ Edit Title", callback_data="jtext_edit_title"),
        InlineKeyboardButton("✏️ Edit Message", callback_data="jtext_edit_msg")
    )
    markup.add(
        InlineKeyboardButton("🔘 Edit Button Names", callback_data="jtext_edit_btns")
    )
    markup.add(
        InlineKeyboardButton("👁️ Preview", callback_data="jtext_preview"),
        InlineKeyboardButton("🔄 Reset", callback_data="jtext_reset")
    )
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="back_to_main"))
    return markup

def get_aps_main_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("📄 File Post", callback_data="aps_type_file"))
    markup.add(InlineKeyboardButton("🖼️ Photo Post", callback_data="aps_type_photo"))
    markup.add(InlineKeyboardButton("🎬 Video Post", callback_data="aps_type_video"))
    markup.add(InlineKeyboardButton("🔄 Forward Post (Auto)", callback_data="aps_type_forward")) # NEW
    markup.add(InlineKeyboardButton("📋 My Admin Channels", callback_data="aps_my_admin_channels"))
    markup.add(InlineKeyboardButton("📅 View Scheduled Posts", callback_data="aps_view_scheduled"))
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="back_to_main"))
    return markup

def get_aps_time_keyboard():
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton("⏱️ Minutes", callback_data="aps_cat_min"),
        InlineKeyboardButton("🕐 Hours", callback_data="aps_cat_hour"),
        InlineKeyboardButton("📅 Days", callback_data="aps_cat_day")
    )
    markup.add(InlineKeyboardButton("🔙 Cancel", callback_data="aps_main"))
    return markup

def get_aps_caption_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✍️ Add Text", callback_data="aps_cap_text"),
        InlineKeyboardButton("🎤 Add Voice", callback_data="aps_cap_voice")
    )
    markup.add(
        InlineKeyboardButton("➕ Add Custom Buttons", callback_data="aps_cap_add_btn"),
        InlineKeyboardButton("↩️ Add Reply", callback_data="aps_cap_reply")
    )
    markup.add(InlineKeyboardButton("🔗 Set Join Button Link", callback_data="aps_cap_join_btn"))
    markup.add(InlineKeyboardButton("⏭️ Skip", callback_data="aps_cap_skip"))
    return markup

def get_aps_after_voice_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✍️ Add File Text", callback_data="aps_cap_text"),
        InlineKeyboardButton("📝 Add Voice Text", callback_data="aps_cap_vtext")
    )
    markup.add(
        InlineKeyboardButton("➕ Add File Buttons", callback_data="aps_cap_add_btn"),
        InlineKeyboardButton("↩️ Add Reply", callback_data="aps_cap_reply")
    )
    markup.add(InlineKeyboardButton("🔗 Set Join Button Link", callback_data="aps_cap_join_btn"))
    markup.add(
        InlineKeyboardButton("🔗 Add Voice Buttons", callback_data="aps_cap_add_vbtn")
    )
    markup.add(InlineKeyboardButton("⏭️ Next / Skip", callback_data="aps_cap_skip"))
    return markup

def get_aps_after_text_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎤 Add Voice", callback_data="aps_cap_voice"),
        InlineKeyboardButton("📝 Add Voice Text", callback_data="aps_cap_vtext")
    )
    markup.add(
        InlineKeyboardButton("➕ Add Custom Buttons", callback_data="aps_cap_add_btn"),
        InlineKeyboardButton("↩️ Add Reply", callback_data="aps_cap_reply")
    )
    markup.add(InlineKeyboardButton("⏭️ Next / Skip", callback_data="aps_cap_skip"))
    return markup

def get_del_time_keyboard():
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton("⏱️ Minutes", callback_data="del_cat_min"),
        InlineKeyboardButton("🕐 Hours", callback_data="del_cat_hour"),
        InlineKeyboardButton("📅 Days", callback_data="del_cat_day")
    )
    markup.add(InlineKeyboardButton("🔙 Cancel", callback_data="back_to_main"))
    return markup

# =====================================================
#           📁 FILE SENDING
# =====================================================

def send_target_file(chat_id, file_key):
    if file_key not in file_database:
        bot.send_message(chat_id, "❌ Link expired or file not found.", reply_markup=get_main_keyboard())
        return False
    data = file_database[file_key]
    if data.get("is_text_key"):
        panel = data.get("panel_name", "PANEL")
        key = data.get("secret_value", "NO KEY")
        msg = (
            f"🔐 **{panel}**\n\n"
            "✅ Verification Successful!\n"
            "🔑 **Your Secret Key:**\n\n"
            f"`{key}`"
        )
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📋 Copy Secret Key", callback_data=f"copy_val|{key}"))
        bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=markup)
        log_user_activity(chat_id, "secret_key_accessed")
        return True
    else:
        fid = data["file_id"]
        ftype = data["file_type"]
        fname = data.get("file_name", "file")
        safe_fname = html.escape(fname)
        msg = (
            "✅ **Verification Successful!**\n\n"
            f"📁 File: `{safe_fname}`\n"
            "📥 Your file is ready!"
        )
        bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=get_main_keyboard())
        try:
            if ftype == 'document':
                bot.send_document(chat_id, fid)
            elif ftype == 'photo':
                bot.send_photo(chat_id, fid)
            elif ftype == 'video':
                bot.send_video(chat_id, fid)
            elif ftype == 'audio':
                bot.send_audio(chat_id, fid)
            elif ftype == 'sticker':
                bot.send_sticker(chat_id, fid)
            elif ftype == 'animation':
                bot.send_animation(chat_id, fid)
            log_user_activity(chat_id, "file_accessed")
            return True
        except Exception as e:
            logger.error(f"File send error: {e}")
            bot.send_message(chat_id, "❌ File send error.")
    return False

# =====================================================
#           📝 LIVE UPDATERS
# =====================================================

def generate_scheduled_text(pending):
    msg = "📅 **Scheduled Posts:**\n━━━━━━━━━━━━━━━━━━━━━\n"
    markup = InlineKeyboardMarkup(row_width=1)
    for idx, item in enumerate(pending, 1):
        try:
            when = datetime.fromisoformat(item["scheduled_time"])
            remain = when - datetime.now()
            secs = int(remain.total_seconds())
            if secs > 0:
                d = secs // 86400
                h = (secs % 86400) // 3600
                m = (secs % 3600) // 60
                s = secs % 60
                parts = []
                if d > 0: parts.append(f"{d}d")
                if h > 0: parts.append(f"{h}h")
                if m > 0: parts.append(f"{m}m")
                if s > 0 or (d==0 and h==0 and m==0): parts.append(f"{s}s") 
                remain_str = " ".join(parts)
            else:
                remain_str = "Sending..."
        except:
            remain_str = "?"
        ptype = item.get("post_type", "file")
        emoji = {"file": "📄", "photo": "🖼️", "video": "🎬", "forward": "🔄"}.get(ptype, "📄")
        
        files = item.get("files", [])
        if len(files) == 1:
            file_text = f"`{html.escape(files[0]['file_name'])}`"
        elif len(files) > 1:
            file_text = f"`{len(files)}` files"
        else:
            file_text = "No files"
            
        msg += f"\n{idx}. {emoji} **{file_text}**\n"
        
        ch_ids = item.get("channel_ids", [])
        if ch_ids:
            for ch in ch_ids:
                ch_title = ch.get("title", "Unknown")
                msg += f"   📢 Channel: **{html.escape(ch_title)}**\n"
        else:
            msg += f"   📢 Channel: **None**\n"
            
        msg += f"   ⏰ In: **{remain_str}**\n"
        
        # 🔥 Added Edit Button here 🔥
        markup.add(InlineKeyboardButton(
            text=f"❌ Cancel #{idx}",
            callback_data=f"aps_cancel_{item['id']}"
        ))
        markup.add(InlineKeyboardButton(
            text=f"✏️ Edit Post #{idx}",
            callback_data=f"aps_edit_{item['id']}"
        ))
        # 🔥 END 🔥

    markup.add(InlineKeyboardButton("🔄 Refresh", callback_data="aps_view_scheduled"))
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="aps_main"))
    return msg, markup

def generate_deletion_text(pending):
    msg = "🗑️ **Scheduled Deletions:**\n━━━━━━━━━━━━━━━━━━━━━\n"
    markup = InlineKeyboardMarkup(row_width=1)
    for idx, item in enumerate(pending, 1):
        try:
            when = datetime.fromisoformat(item["delete_at"])
            remain = when - datetime.now()
            secs = int(remain.total_seconds())
            if secs > 0:
                d = secs // 86400
                h = (secs % 86400) // 3600
                m = (secs % 3600) // 60
                s = secs % 60
                parts = []
                if d > 0: parts.append(f"{d}d")
                if h > 0: parts.append(f"{h}h")
                if m > 0: parts.append(f"{m}m")
                if s > 0 or (d==0 and h==0 and m==0): parts.append(f"{s}s") 
                remain_str = " ".join(parts)
            else:
                remain_str = "Deleting..."
        except:
            remain_str = "?"
        
        msg += f"\n{idx}. 📢 **{html.escape(item.get('channel_title', 'Unknown'))}**\n"
        msg += f"   🆔 Message ID: `{item.get('message_id')}`\n"
        msg += f"   ⏰ Deletes in: **{remain_str}**\n"
        markup.add(InlineKeyboardButton(
            text=f"❌ Cancel Deletion #{idx}",
            callback_data=f"del_cancel_{item['id']}"
        ))
    markup.add(InlineKeyboardButton("🔄 Refresh", callback_data="del_view"))
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="back_to_main"))
    return msg, markup

def live_updater():
    while True:
        try:
            time.sleep(3)
            
            if live_schedule_messages:
                for chat_id, msg_id in list(live_schedule_messages.items()):
                    pending = [x for x in scheduled_posts if not x.get("sent")]
                    if not pending:
                        try:
                            bot.edit_message_text("❌ No pending scheduled posts.", chat_id, msg_id)
                        except:
                            pass
                        if chat_id in live_schedule_messages:
                            del live_schedule_messages[chat_id]
                        continue
                    
                    msg, markup = generate_scheduled_text(pending)
                    try:
                        bot.edit_message_text(msg, chat_id, msg_id, parse_mode="Markdown", reply_markup=markup)
                    except Exception as e:
                        if "message is not modified" not in str(e).lower():
                            if chat_id in live_schedule_messages:
                                del live_schedule_messages[chat_id]

            if live_deletion_messages:
                for chat_id, msg_id in list(live_deletion_messages.items()):
                    pending = [x for x in scheduled_deletions if not x.get("deleted")]
                    if not pending:
                        try:
                            bot.edit_message_text("❌ No pending scheduled deletions.", chat_id, msg_id)
                        except:
                            pass
                        if chat_id in live_deletion_messages:
                            del live_deletion_messages[chat_id]
                        continue
                    
                    msg, markup = generate_deletion_text(pending)
                    try:
                        bot.edit_message_text(msg, chat_id, msg_id, parse_mode="Markdown", reply_markup=markup)
                    except Exception as e:
                        if "message is not modified" not in str(e).lower():
                            if chat_id in live_deletion_messages:
                                del live_deletion_messages[chat_id]

        except Exception as e:
            logger.error(f"Live updater error: {e}")

# =====================================================
#           📝 COMMAND HANDLERS
# =====================================================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        chat_id = message.chat.id
        user_id = message.from_user.id
        first_name = message.from_user.first_name

        try:
            bot.delete_message(chat_id, message.message_id)
        except:
            pass

        if is_user_banned(user_id):
            bot.send_message(chat_id, "⛔ You are banned!")
            return
        if user_id != ADMIN_ID and bot_settings.get("maintenance_mode", False):
            bot.send_message(chat_id, "🔧 Bot is under maintenance. Please try again later.")
            return

        user_states[chat_id] = None
        args = message.text.split()

        if len(args) > 1 and args[1].startswith("ref_"):
            try:
                ref_id = int(args[1].replace("ref_", ""))
                if ref_id != user_id and user_id not in registered_users:
                    if "referrals" not in db:
                        db["referrals"] = {}
                    if str(ref_id) not in db["referrals"]:
                        db["referrals"][str(ref_id)] = []
                    if user_id not in db["referrals"][str(ref_id)]:
                        db["referrals"][str(ref_id)].append(user_id)
                        sync_db()
                        bot.send_message(ref_id, f"🎉 New referral!")
            except:
                pass

        if user_id not in registered_users:
            registered_users.add(user_id)
            log_user_activity(user_id, "registered")
            sync_db()

        file_key = args[1] if len(args) > 1 and not args[1].startswith("ref_") else None

        if user_id == ADMIN_ID:
            if is_admin_logged_in(user_id):
                bot.send_message(chat_id, f"👋 Welcome {BOT_NAME} Admin!\n🛠️ Bot Control Panel", reply_markup=get_admin_panel_keyboard())
            else:
                bot.send_message(chat_id, "🔐 Admin Login Required!", reply_markup=get_login_keyboard())
            return

        unjoined = get_unjoined_channels(user_id)
        if not unjoined:
            if file_key:
                send_target_file(chat_id, file_key)
            else:
                welcome_text = bot_settings.get("welcome_message", f"✨ Welcome to {BOT_NAME} Premium Bot! ✨\n\n👋 Hello {{name}}!")
                formatted_welcome = welcome_text.replace("{name}", first_name).replace("{id}", str(user_id))
                
                try:
                    bot.send_message(chat_id, formatted_welcome, reply_markup=get_main_keyboard(), parse_mode="HTML")
                except:
                    bot.send_message(chat_id, formatted_welcome, reply_markup=get_main_keyboard())
            return

        msg = get_join_message(unjoined)
        bot.send_message(chat_id, msg, reply_markup=get_join_keyboard(file_key, unjoined))
    except Exception as e:
        logger.error(f"Start error: {e}")

# =====================================================
#           📝 CALLBACK HANDLER
# =====================================================

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    # GLOBAL DECLARATION FIX
    global db, file_database, registered_users, banned_users, user_activity, bot_settings, scheduled_messages, scheduled_posts, scheduled_deletions, giveaway, referrals

    try:
        chat_id = call.message.chat.id
        user_id = call.from_user.id
        message_id = call.message.message_id

        try:
            bot.answer_callback_query(call.id)
        except:
            pass

        if is_user_banned(user_id) and user_id != ADMIN_ID:
            bot.answer_callback_query(call.id, "⛔ Banned!", show_alert=True)
            return

        if call.data.startswith("copy_val|"):
            val = call.data.split("copy_val|", 1)[1]
            bot.answer_callback_query(call.id, text=f"✅ Copied!\n\n{val}", show_alert=True)
            return

        if call.data.startswith("copy_key|"):
            key = call.data.split("copy_key|", 1)[1]
            try:
                bi = bot.get_me()
                link = f"https://t.me/{bi.username}?start={key}"
                bot.answer_callback_query(call.id, text="✅ Link sent below! Tap to copy.")
                bot.send_message(chat_id, f"🔗 Your Link:\n`{link}`", parse_mode="Markdown")
            except Exception as e:
                bot.answer_callback_query(call.id, text=f"❌ Error generating link.", show_alert=True)
            return

        if call.data == "admin_login":
            user_states[chat_id] = {"stage": "waiting_for_admin_password"}
            send_clean_prompt(chat_id, "🔑 Enter admin password (saved until Logout):")
            return
        if call.data == "admin_login_save":
            user_states[chat_id] = {"stage": "waiting_for_admin_password_save"}
            send_clean_prompt(chat_id, "🔑 Enter admin password (saved until Logout):")
            return
        if call.data == "auto_login_status":
            s = "🔄 Auto-Login: ✅ ON\n⏰ Until manual Logout" if is_admin_logged_in(user_id) else "🔄 Auto-Login: ❌ OFF"
            bot.answer_callback_query(call.id, s, show_alert=True)
            return
        if call.data == "toggle_user_limit" or call.data.startswith("project_"):
            if user_id != ADMIN_ID or not is_admin_logged_in(user_id):
                bot.answer_callback_query(call.id, "Admin login required.", show_alert=True)
                return

        if call.data == "toggle_user_limit":
            bot_settings["user_limit_enabled"] = not bot_settings.get("user_limit_enabled", True)
            sync_db()
            enabled = bot_settings["user_limit_enabled"]
            # Refresh reply keyboards for registered users so OFF hides the menu immediately.
            markup = get_main_keyboard()
            delivered = 0
            for target_uid in list(registered_users):
                if target_uid == ADMIN_ID:
                    continue
                try:
                    bot.send_message(target_uid, "👥 User menu is now ON." if enabled else "👥 User menu is now OFF.", reply_markup=markup, disable_notification=True)
                    delivered += 1
                    time.sleep(0.04)
                except Exception as exc:
                    logger.info("Could not refresh user keyboard for %s: %s", target_uid, exc)
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=get_admin_panel_keyboard())
            except Exception:
                bot.send_message(chat_id, f"✅ User Limit is now {'ON' if enabled else 'OFF'}. Refreshed {delivered} user keyboard(s).", reply_markup=get_admin_panel_keyboard())
            return

        if call.data == "project_files_main":
            projects = db.setdefault("project_files", [])
            text = ("📁 **Project File Manager**\n━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Saved projects: **{len(projects)}**\n\nChoose an action:")
            try:
                bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown", reply_markup=get_project_files_keyboard())
            except Exception:
                bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=get_project_files_keyboard())
            return

        if call.data == "project_add":
            user_states[chat_id] = {"stage": "project_waiting_name"}
            send_clean_prompt(chat_id, "📝 Send your project name:")
            return

        if call.data == "project_view":
            projects = db.setdefault("project_files", [])
            if not projects:
                bot.send_message(chat_id, "📁 No projects saved yet.", reply_markup=get_project_files_keyboard())
                return
            bot.send_message(chat_id, f"📁 **Saved Projects: {len(projects)}**", parse_mode="Markdown")
            for item in projects[-50:]:
                label = html.escape(item.get("name", "Unnamed project"))
                fname = html.escape(item.get("file_name", "file"))
                mk = InlineKeyboardMarkup(row_width=1)
                mk.add(InlineKeyboardButton("📥 Send Project File", callback_data=f"project_send_{item.get('id')}"))
                bot.send_message(chat_id, f"📦 **{label}**\n📎 `{fname}`\n🗓 {html.escape(item.get('uploaded_at', '')[:10])}", parse_mode="Markdown", reply_markup=mk)
            bot.send_message(chat_id, "Project list", reply_markup=get_project_files_keyboard())
            return

        if call.data == "project_delete":
            projects = db.setdefault("project_files", [])
            if not projects:
                bot.send_message(chat_id, "📁 No projects to delete.", reply_markup=get_project_files_keyboard())
                return
            mk = InlineKeyboardMarkup(row_width=1)
            for item in projects[-50:]:
                mk.add(InlineKeyboardButton(f"🗑️ {item.get('name', 'Unnamed')[:45]}", callback_data=f"project_del_{item.get('id')}"))
            mk.add(InlineKeyboardButton("🔙 Back", callback_data="project_files_main"))
            bot.send_message(chat_id, f"🗑️ Choose a project to delete ({len(projects)} total):", reply_markup=mk)
            return

        if call.data == "project_save":
            st = user_states.get(chat_id) or {}
            pending = st.get("pending_project")
            if st.get("stage") != "project_confirm" or not pending:
                bot.answer_callback_query(call.id, "No pending project to save.", show_alert=True)
                return
            projects = db.setdefault("project_files", [])
            projects.append(pending)
            sync_db()
            user_states[chat_id] = None
            bot.edit_message_text(f"✅ Project **{html.escape(pending.get('name', 'Unnamed'))}** saved!\nTotal projects: **{len(projects)}**", chat_id, message_id, parse_mode="Markdown", reply_markup=get_project_files_keyboard())
            return

        if call.data == "project_close":
            user_states[chat_id] = None
            try:
                bot.edit_message_text("✖️ Project upload closed. Nothing was saved.", chat_id, message_id, reply_markup=get_project_files_keyboard())
            except Exception:
                bot.send_message(chat_id, "✖️ Project upload closed. Nothing was saved.", reply_markup=get_project_files_keyboard())
            return

        if call.data.startswith("project_send_"):
            project_id = call.data.rsplit("_", 1)[-1]
            item = next((x for x in db.setdefault("project_files", []) if str(x.get("id")) == project_id), None)
            if not item:
                bot.answer_callback_query(call.id, "Project not found.", show_alert=True)
                return
            _send_project_file(chat_id, item)
            return

        if call.data.startswith("project_del_"):
            project_id = call.data.rsplit("_", 1)[-1]
            projects = db.setdefault("project_files", [])
            before = len(projects)
            db["project_files"] = [x for x in projects if str(x.get("id")) != project_id]
            if len(db["project_files"]) != before:
                sync_db()
                bot.answer_callback_query(call.id, "Project deleted.")
                try:
                    bot.delete_message(chat_id, message_id)
                except Exception:
                    pass
                bot.send_message(chat_id, f"✅ Project deleted. Remaining: {len(db['project_files'])}", reply_markup=get_project_files_keyboard())
            else:
                bot.answer_callback_query(call.id, "Project not found.", show_alert=True)
            return

        if call.data == "continue_as_user":
            try:
                bot.delete_message(chat_id, message_id)
            except:
                pass
            bot.send_message(chat_id, "👤 User mode.", reply_markup=get_main_keyboard())
            return
        if call.data == "admin_logout":
            logout_admin(user_id)
            bot.answer_callback_query(call.id, "✅ Logged out!")
            bot.edit_message_text("🚪 Logged out.", chat_id, message_id)
            return

        if call.data.startswith("verify_"):
            file_key = call.data.split("verify_")[-1]
            unjoined = get_unjoined_channels(user_id)
            if not unjoined:
                try:
                    bot.delete_message(chat_id, message_id)
                except:
                    pass
                if file_key and file_key != "None":
                    send_target_file(chat_id, file_key)
                else:
                    welcome_text = bot_settings.get("welcome_message", f"✨ Welcome to {BOT_NAME} Premium Bot! ✨\n\n👋 Hello {{name}}!")
                    formatted_welcome = welcome_text.replace("{name}", call.from_user.first_name).replace("{id}", str(user_id))
                    try:
                        bot.send_message(chat_id, formatted_welcome, reply_markup=get_main_keyboard(), parse_mode="HTML")
                    except:
                        bot.send_message(chat_id, formatted_welcome, reply_markup=get_main_keyboard())
                bot.answer_callback_query(call.id, "✅ Verified!")
            else:
                bot.answer_callback_query(call.id, f"❌ Join {len(unjoined)} more!", show_alert=True)
                msg = get_join_message(unjoined)
                try:
                    bot.edit_message_text(msg, chat_id, message_id, reply_markup=get_join_keyboard(file_key, unjoined))
                except:
                    pass
            return

        if call.data == "check_verification":
            unjoined = get_unjoined_channels(user_id)
            if not unjoined:
                try:
                    bot.delete_message(chat_id, message_id)
                except:
                    pass
                welcome_text = bot_settings.get("welcome_message", f"✨ Welcome to {BOT_NAME} Premium Bot! ✨\n\n👋 Hello {{name}}!")
                formatted_welcome = welcome_text.replace("{name}", call.from_user.first_name).replace("{id}", str(user_id))
                try:
                    bot.send_message(chat_id, formatted_welcome, reply_markup=get_main_keyboard(), parse_mode="HTML")
                except:
                    bot.send_message(chat_id, formatted_welcome, reply_markup=get_main_keyboard())
                bot.answer_callback_query(call.id, "✅ Verified!")
            else:
                bot.answer_callback_query(call.id, f"❌ Join {len(unjoined)} more!", show_alert=True)
            return

        if call.data == "my_stats":
            if user_id in user_activity:
                s = user_activity[user_id]
                bot.send_message(chat_id, f"📊 **Stats:**\n🔄 {s['total_actions']}\n⭐ {s.get('points', 0)}\n🏅 {s.get('rank', 'Member')}")
            return
        if call.data == "daily_reward":
            today = datetime.now().date().isoformat()
            if user_activity.get(user_id, {}).get("last_daily") == today:
                bot.answer_callback_query(call.id, "❌ Already claimed!", show_alert=True)
                return
            if user_id not in user_activity:
                user_activity[user_id] = {"points": 0}
            user_activity[user_id]["points"] = user_activity[user_id].get("points", 0) + bot_settings.get("daily_reward", 10)
            user_activity[user_id]["last_daily"] = today
            sync_db()
            bot.answer_callback_query(call.id, f"🎁 +{bot_settings.get('daily_reward', 10)} points!")
            return
        if call.data == "get_referral":
            bi = bot.get_me()
            rl = f"https://t.me/{bi.username}?start=ref_{user_id}"
            rc = len(db.get("referrals", {}).get(str(user_id), []))
            bot.send_message(chat_id, f"🔗 `{rl}`\n\n📊 Count: {rc}", parse_mode="Markdown")
            return
        if call.data == "user_help":
            bot.send_message(chat_id, f"✨ {BOT_NAME}\n\n🎙️ Voice\n📊 Stats\n🎁 Daily\n🏆 Leaderboard")
            return

        if user_id != ADMIN_ID:
            bot.answer_callback_query(call.id, "❌ Admin only!", show_alert=True)
            return
        if not is_admin_logged_in(user_id):
            bot.answer_callback_query(call.id, "🔐 Login first!", show_alert=True)
            return

        if call.data == "toggle_force_join":
            bot_settings["force_join"] = not bot_settings["force_join"]
            sync_db()
            bot.edit_message_reply_markup(chat_id, message_id, reply_markup=get_admin_panel_keyboard())
        elif call.data == "toggle_maintenance":
            bot_settings["maintenance_mode"] = not bot_settings.get("maintenance_mode", False)
            sync_db()
            bot.edit_message_reply_markup(chat_id, message_id, reply_markup=get_admin_panel_keyboard())
        elif call.data == "admin_clear_data":
            mk = InlineKeyboardMarkup(row_width=2)
            mk.add(
                InlineKeyboardButton("✅ Yes, Clear All", callback_data="admin_clear_confirm"),
                InlineKeyboardButton("❌ Cancel", callback_data="back_to_main")
            )
            bot.edit_message_text(
                "⚠️ **Are you absolutely sure?**\n\n"
                "This will delete ALL data including Channels, Reaction Bots, Files, Users, and Settings. This action cannot be undone!",
                chat_id, message_id, parse_mode="Markdown", reply_markup=mk
            )
        elif call.data == "admin_clear_confirm":
            db = get_default_db()
            file_database = db["file_database"]
            registered_users = set(db["registered_users"])
            banned_users = set(db["banned_users"])
            user_activity = db["user_activity"]
            bot_settings = db["bot_settings"]
            scheduled_messages = db["scheduled_messages"]
            scheduled_posts = db["scheduled_posts"]
            scheduled_deletions = db["scheduled_deletions"]
            giveaway = db["giveaway"]
            referrals = db["referrals"]
            sync_db()
            
            if os.path.exists(DB_FILE):
                os.remove(DB_FILE)
            
            bot.edit_message_text("✅ **All data cleared successfully!** Bot is now like new.", chat_id, message_id, reply_markup=get_admin_panel_keyboard())

        # ============ REACTION BOT ============
        elif call.data == "rb_main":
            text = (
                "🎭 **Reaction Bot Manager**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "Here you can add multiple Telegram bots to react with emojis on channel posts automatically."
            )
            try: bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown", reply_markup=get_rb_main_keyboard())
            except: bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=get_rb_main_keyboard())

        elif call.data == "rb_saved_confirm_save":
            st = user_states.get(chat_id) or {}
            if st.get("stage") != "rb_saved_confirm":
                bot.answer_callback_query(call.id, "Save session expired.", show_alert=True); return
            saved = bot_settings.setdefault("saved_bot_tokens", [])
            existing = {x.get("token") for x in saved}
            added = 0
            for item in st.get("saved_collected", []):
                if item.get("token") and item["token"] not in existing:
                    saved.append({"token": item["token"], "bot_id": item.get("bot_id", "Unknown")})
                    existing.add(item["token"]); added += 1
            sync_db(); user_states[chat_id] = None
            bot.edit_message_text(f"✅ **Saved {added} bot token(s)!**\nTotal saved: {len(saved)}", chat_id, message_id, parse_mode="Markdown", reply_markup=get_rb_main_keyboard())

        elif call.data == "rb_saved_confirm_cancel":
            user_states[chat_id] = None
            bot.edit_message_text("❌ Token saving cancelled. No new tokens were saved.", chat_id, message_id, reply_markup=get_rb_main_keyboard())

        elif call.data == "rb_saved_main":
            saved = bot_settings.get("saved_bot_tokens", [])
            mk = InlineKeyboardMarkup(row_width=1)
            mk.add(InlineKeyboardButton("➕ Add Saved Bot", callback_data="rb_saved_add"))
            mk.add(InlineKeyboardButton("🗑️ Delete Saved Bot", callback_data="rb_saved_delete"))
            mk.add(InlineKeyboardButton("🔙 Back", callback_data="rb_main"))
            bot.edit_message_text(
                f"💾 **Saved Bot Tokens**\n━━━━━━━━━━━━━━━━━━━━━\nSaved tokens: **{len(saved)}**\n\nChoose Add Saved Bot to save tokens, or Delete Saved Bot to remove saved entries.",
                chat_id, message_id, parse_mode="Markdown", reply_markup=mk
            )

        elif call.data == "rb_saved_add":
            user_states[chat_id] = {"stage": "rb_saved_wait_count"}
            send_clean_prompt(chat_id, "🔢 **How many Telegram bot tokens do you want to save?**\n\nSend a number (e.g. 10). You will then send each token one by one.", parse_mode="Markdown")

        elif call.data == "rb_saved_delete":
            saved = bot_settings.get("saved_bot_tokens", [])
            if not saved:
                bot.answer_callback_query(call.id, "No saved bot tokens.", show_alert=True)
                return
            mk = InlineKeyboardMarkup(row_width=1)
            for i, item in enumerate(saved):
                bid = item.get("bot_id", "Unknown")
                mk.add(InlineKeyboardButton(f"🗑️ Delete Bot {bid}", callback_data=f"rb_saved_del_{i}"))
            mk.add(InlineKeyboardButton("🔙 Back", callback_data="rb_saved_main"))
            bot.edit_message_text("🗑️ **Choose a saved bot token to delete:**", chat_id, message_id, parse_mode="Markdown", reply_markup=mk)

        elif call.data.startswith("rb_saved_del_"):
            try: idx = int(call.data.rsplit("_", 1)[1])
            except: idx = -1
            saved = bot_settings.setdefault("saved_bot_tokens", [])
            if 0 <= idx < len(saved):
                removed = saved.pop(idx)
                sync_db()
                bot.answer_callback_query(call.id, f"Deleted saved bot {removed.get('bot_id', '')}")
            bot.edit_message_text(f"💾 **Saved Bot Tokens: {len(saved)}**", chat_id, message_id, parse_mode="Markdown", reply_markup=get_rb_main_keyboard())

        elif call.data == "rb_add":
            saved = bot_settings.get("saved_bot_tokens", [])
            mk = InlineKeyboardMarkup(row_width=1)
            mk.add(InlineKeyboardButton(f"💾 Use Saved Bot Tokens ({len(saved)})", callback_data="rb_use_saved"))
            mk.add(InlineKeyboardButton("✍️ Add Tokens Manually", callback_data="rb_add_manual"))
            mk.add(InlineKeyboardButton("🔙 Back", callback_data="rb_main"))
            bot.edit_message_text("🎭 **Add Reaction Bots**\n\nChoose saved bot tokens or enter new tokens manually.", chat_id, message_id, parse_mode="Markdown", reply_markup=mk)

        elif call.data == "rb_add_manual":
            user_states[chat_id] = {"stage": "rb_waiting_count"}
            send_clean_prompt(chat_id, "🔢 **How many bots do you want to add?**\n\nSend a number (e.g., `1`, `5`, `10`).", parse_mode="Markdown")

        elif call.data == "rb_use_saved":
            saved = bot_settings.get("saved_bot_tokens", [])
            if not saved:
                bot.answer_callback_query(call.id, "No saved tokens. Choose Add Tokens Manually or save tokens first.", show_alert=True)
                return
            # Select all saved bots by default so Done works immediately.
            # Users can tap any bot to deselect it before continuing.
            user_states[chat_id] = {
                "stage": "rb_select_saved",
                "selected_saved": list(range(len(saved)))
            }
            mk = InlineKeyboardMarkup(row_width=1)
            for i, item in enumerate(saved):
                bid = item.get("bot_id", "Unknown")
                mk.add(InlineKeyboardButton(f"✅ Selected Bot {bid}", callback_data=f"rb_saved_toggle_{i}"))
            mk.add(InlineKeyboardButton(f"✅ Done — Continue ({len(saved)} selected)", callback_data="rb_saved_done"))
            mk.add(InlineKeyboardButton("🔙 Back", callback_data="rb_add"))
            bot.edit_message_text(
                f"💾 **Select Saved Bots**\\nSaved tokens available: {len(saved)}\\n\\nAll saved bots are selected by default. Tap a bot to deselect it, then press Done.",
                chat_id, message_id, parse_mode="Markdown", reply_markup=mk
            )

        elif call.data.startswith("rb_saved_toggle_"):
            st = user_states.get(chat_id) or {}
            try: idx = int(call.data.rsplit("_", 1)[1])
            except: idx = -1
            saved = bot_settings.get("saved_bot_tokens", [])
            if st.get("stage") != "rb_select_saved" or not (0 <= idx < len(saved)):
                bot.answer_callback_query(call.id, "Selection expired. Open Add Bot again.", show_alert=True); return
            selected = st.setdefault("selected_saved", [])
            if idx in selected: selected.remove(idx)
            else: selected.append(idx)
            user_states[chat_id] = st
            mk = InlineKeyboardMarkup(row_width=1)
            for i, item in enumerate(saved):
                mark = "✅" if i in selected else "☑️"
                mk.add(InlineKeyboardButton(f"{mark} Bot {item.get('bot_id', 'Unknown')}", callback_data=f"rb_saved_toggle_{i}"))
            mk.add(InlineKeyboardButton(f"✅ Done ({len(selected)} selected)", callback_data="rb_saved_done"))
            mk.add(InlineKeyboardButton("🔙 Back", callback_data="rb_add"))
            bot.edit_message_reply_markup(chat_id, message_id, reply_markup=mk)
            bot.answer_callback_query(call.id, f"{len(selected)} selected")

        elif call.data == "rb_saved_done":
            st = user_states.get(chat_id) or {}
            saved = bot_settings.get("saved_bot_tokens", [])
            indices = st.get("selected_saved", [])
            chosen = [saved[i].copy() for i in indices if isinstance(i, int) and 0 <= i < len(saved)]
            if not chosen:
                bot.answer_callback_query(call.id, "Select at least one saved bot, or go Back.", show_alert=True)
                return
            user_states[chat_id] = {
                "stage": "rb_waiting_channel",
                "tokens_collected": chosen,
                "total_bots": len(chosen)
            }
            bot.answer_callback_query(call.id, f"{len(chosen)} saved bot(s) selected.")
            send_clean_prompt(
                chat_id,
                f"✅ **{len(chosen)} saved bot(s) selected.**\\n\\n📢 Send the channel ID or public channel username where these bots should react:",
                parse_mode="Markdown"
            )

        elif call.data == "rb_add_another_channel":
            st = user_states.get(chat_id) or {}
            reusable = st.get("tokens_collected", [])
            if not reusable:
                bot.answer_callback_query(call.id, "Bot selection expired. Please select saved tokens again.", show_alert=True)
                user_states[chat_id] = None
                return
            st["stage"] = "rb_waiting_channel"
            st["current_channel_id"] = None
            st["current_channel_title"] = None
            st["verified_bots"] = []
            st["current_bot_index"] = 0
            user_states[chat_id] = st
            bot.answer_callback_query(call.id, "Ready for another channel.")
            send_clean_prompt(
                chat_id,
                f"📢 **Add another channel**\\nThe same {len(reusable)} selected bot token(s) will be reused.\\n\\nSend the next channel ID or public channel username:",
                parse_mode="Markdown"
            )

        elif call.data == "rb_finish_multi_channel":
            user_states[chat_id] = None
            bot.answer_callback_query(call.id, "Setup finished.")
            try:
                bot.edit_message_text(
                    "✅ **Reaction Bot setup completed.**\\nUse Preview Bot to review configured channels and emojis.",
                    chat_id, message_id, parse_mode="Markdown", reply_markup=get_rb_main_keyboard()
                )
            except:
                bot.send_message(chat_id, "✅ **Reaction Bot setup completed.**", parse_mode="Markdown", reply_markup=get_rb_main_keyboard())

        elif call.data == "rb_preview":
            bots = bot_settings.get("reaction_bots", [])
            if not bots:
                bot.send_message(chat_id, "❌ No reaction bots added yet.")
                return
            
            msg = "👁️ **Reaction Bot Preview:**\n━━━━━━━━━━━━━━━━━━━━━\n"
            mk = InlineKeyboardMarkup(row_width=1)
            for i, b in enumerate(bots):
                token = b.get('token', '')
                masked_token = token[:10] + "..." + token[-5:] if len(token) > 15 else token
                
                ch_title = b.get('channel_title', 'Unknown Channel')
                bot_id = b.get('bot_id', 'Unknown')
                emoji = b.get('emoji', '❓')
                
                msg += f"\n{i+1}. 🤖 **Bot ID:** `{bot_id}`\n"
                msg += f"   📢 **Channel:** {ch_title}\n"
                msg += f"   🎭 **Emoji:** {emoji}\n"
                msg += f"   🔑 **Token:** `{masked_token}`\n"
                
                mk.add(InlineKeyboardButton(f"❌ Delete Bot {bot_id}", callback_data=f"rb_del_{i}"))
            
            mk.add(InlineKeyboardButton("🔙 Back", callback_data="rb_main"))
            try: bot.edit_message_text(msg, chat_id, message_id, parse_mode="Markdown", reply_markup=mk)
            except: bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=mk)

        elif call.data == "rb_remove":
            bots = bot_settings.get("reaction_bots", [])
            if not bots:
                bot.answer_callback_query(call.id, "❌ No bots to remove!", show_alert=True)
                return
            try: bot.edit_message_text("🗑️ **Select a bot to remove:**", chat_id, message_id, reply_markup=get_rb_remove_keyboard())
            except: bot.send_message(chat_id, "🗑️ **Select a bot to remove:**", reply_markup=get_rb_remove_keyboard())

        elif call.data.startswith("rb_del_"):
            idx = int(call.data.split("rb_del_")[-1])
            bots = bot_settings.get("reaction_bots", [])
            if 0 <= idx < len(bots):
                removed = bots.pop(idx)
                sync_db()
                bot.answer_callback_query(call.id, f"✅ Removed Bot {removed.get('bot_id')}!")
            
            if not bots:
                bot.edit_message_text("🗑️ All bots removed.", chat_id, message_id, reply_markup=get_rb_main_keyboard())
            else:
                msg = "👁️ **Reaction Bot Preview:**\n━━━━━━━━━━━━━━━━━━━━━\n"
                mk = InlineKeyboardMarkup(row_width=1)
                for i, b in enumerate(bots):
                    token = b.get('token', '')
                    masked_token = token[:10] + "..." + token[-5:] if len(token) > 15 else token
                    ch_title = b.get('channel_title', 'Unknown Channel')
                    bot_id = b.get('bot_id', 'Unknown')
                    emoji = b.get('emoji', '❓')
                    
                    msg += f"\n{i+1}. 🤖 **Bot ID:** `{bot_id}`\n"
                    msg += f"   📢 **Channel:** {ch_title}\n"
                    msg += f"   🎭 **Emoji:** {emoji}\n"
                    msg += f"   🔑 **Token:** `{masked_token}`\n"
                    mk.add(InlineKeyboardButton(f"❌ Delete Bot {bot_id}", callback_data=f"rb_del_{i}"))
                
                mk.add(InlineKeyboardButton("🔙 Back", callback_data="rb_main"))
                try: bot.edit_message_text(msg, chat_id, message_id, parse_mode="Markdown", reply_markup=mk)
                except: bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=mk)

        # EDIT REACTION CALLBACK
        elif call.data.startswith("rb_edit_"):
            idx = int(call.data.split("rb_edit_")[-1])
            bots = bot_settings.get("reaction_bots", [])
            if 0 <= idx < len(bots):
                user_states[chat_id] = {"stage": "rb_editing_emoji", "edit_idx": idx}
                send_clean_prompt(
                    chat_id,
                    f"✏️ **Editing Reaction for Bot:** `{bots[idx].get('bot_id')}`\n"
                    f"📢 **Channel:** {bots[idx].get('channel_title')}\n\n"
                    "🎭 Please send the **New Emoji** (Make sure this emoji is available in your channel):",
                    parse_mode="Markdown"
                )
            return

        # ============ USERBOT (MULTI-KEY AI) ============
        elif call.data == "ub_main":
            if not USERBOT_AVAILABLE:
                bot.send_message(chat_id, "❌ Error in userbot.py or missing dependencies!")
                return
            text = (
                "🤖 **AI Auto-Reply Management**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "Here you can add multiple Gemini API Keys. "
                "If one key reaches its limit, the bot will automatically use the next key."
            )
            try: bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown", reply_markup=get_ub_main_keyboard())
            except: bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=get_ub_main_keyboard())

        elif call.data == "ub_connect":
            user_states[chat_id] = {"stage": "ub_waiting_count"}
            send_clean_prompt(
                chat_id,
                "🔢 **How many API Keys do you want to add?**\n\n"
                "Send a number (e.g., `2`, `4`, `10`).",
                parse_mode="Markdown"
            )

        elif call.data == "ub_reset":
            data = ub_module.load_ub() if USERBOT_AVAILABLE else {}
            for p, v in data.items():
                try:
                    run_async(ub_module.stop_userbot(p))
                except:
                    pass
                
                session_file = v.get("session_file")
                if session_file:
                    for ext in ["", ".session", ".session-journal", ".session-wal", ".session-shm"]:
                        if os.path.exists(session_file + ext):
                            try:
                                os.remove(session_file + ext)
                            except:
                                pass

            if USERBOT_AVAILABLE:
                ub_module.ACTIVE_CLIENTS.clear()

            if os.path.exists("userbot_sessions.json"):
                try:
                    os.remove("userbot_sessions.json")
                except:
                    pass

            for file in os.listdir("."):
                if file.startswith("session_") and file.endswith(".session"):
                    try:
                        os.remove(file)
                    except:
                        pass
            for file in os.listdir("."):
                if file.startswith("session_") and any(file.endswith(ext) for ext in [".session-journal", ".session-wal", ".session-shm"]):
                    try:
                        os.remove(file)
                    except:
                        pass

            bot.answer_callback_query(call.id, "✅ All sessions reset!", show_alert=True)
            bot.send_message(chat_id, "✅ All old sessions have been deleted. Please connect again.")

        elif call.data == "ub_list":
            data = ub_module.load_ub() if USERBOT_AVAILABLE else {}
            active = [(p, v) for p, v in data.items() if v.get("logged_in")]
            if not active:
                bot.send_message(chat_id, "❌ No active sessions.")
                return
            msg = "📋 **Active Sessions:**\n━━━━━━━━━━━━━━━━━━━━━\n"
            mk = InlineKeyboardMarkup(row_width=1)
            for p, v in active:
                keys_count = len(v.get("api_keys", []))
                msg += f"\n📱 `{p}`\n🔑 Keys: {keys_count}\n⏰ {v.get('connected_at', '?')[:19]}\n"
                mk.add(InlineKeyboardButton(f"🔴 Stop {p}", callback_data=f"ub_stop_{p}"))
            mk.add(InlineKeyboardButton("🔙 Back", callback_data="ub_main"))
            bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=mk)

        elif call.data.startswith("ub_stop_"):
            phone = call.data.split("ub_stop_")[-1]
            try:
                if USERBOT_AVAILABLE:
                    run_async(ub_module.stop_userbot(phone))
                bot.send_message(chat_id, f"🔴 `{phone}` stopped.", parse_mode="Markdown")
            except Exception as e:
                bot.send_message(chat_id, f"❌ Error: {e}")

        # ============ WELCOME MESSAGE EDITOR ============
        elif call.data == "welcome_editor":
            current_welcome = bot_settings.get("welcome_message", f"✨ Welcome to {BOT_NAME} Premium Bot! ✨\n\n👋 Hello {{name}}!")
            text = (
                "👋 **Welcome Message Editor**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "**Current Welcome Message:**\n\n"
                f"{current_welcome}\n\n"
                "💡 Use `{name}` for user's first name.\n"
                "You can use HTML tags like <b>Bold</b>, <i>Italic</i>."
            )
            try:
                bot.edit_message_text(text, chat_id, message_id, parse_mode="HTML", reply_markup=get_welcome_editor_keyboard())
            except:
                bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=get_welcome_editor_keyboard())

        elif call.data == "welcome_edit_text":
            user_states[chat_id] = {"stage": "waiting_for_welcome_text"}
            send_clean_prompt(chat_id, "✏️ **Send the new Welcome Message:**\n\nYou can use `{name}` placeholder and HTML tags.")

        elif call.data == "welcome_preview":
            current_welcome = bot_settings.get("welcome_message", f"✨ Welcome to {BOT_NAME} Premium Bot! ✨\n\n👋 Hello {{name}}!")
            preview_text = current_welcome.replace("{name}", call.from_user.first_name).replace("{id}", str(user_id))
            try:
                bot.send_message(chat_id, f"👁️ **Welcome Preview:**\n\n{preview_text}", reply_markup=get_main_keyboard(), parse_mode="HTML")
            except:
                bot.send_message(chat_id, f"👁️ **Welcome Preview:**\n\n{preview_text}", reply_markup=get_main_keyboard())

        elif call.data == "welcome_reset":
            bot_settings["welcome_message"] = f"✨ Welcome to {BOT_NAME} Premium Bot! ✨\n\n👋 Hello {{name}}!"
            sync_db()
            current_welcome = bot_settings.get("welcome_message")
            text = (
                "👋 **Welcome Message Editor**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "**Current Welcome Message (Default):**\n\n"
                f"{current_welcome}\n\n"
                "💡 Use `{name}` for user's first name."
            )
            try:
                bot.edit_message_text(text, chat_id, message_id, parse_mode="HTML", reply_markup=get_welcome_editor_keyboard())
            except:
                pass

        # ============ CONNECT CHANNEL FEATURE ============
        elif call.data == "conn_main":
            text = (
                "🔗 **Connect Channel**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "Automatically copy posts from source channels to your destination channel.\n"
            )
            if bot_settings.get("conn_dest"):
                text += f"\n🟢 **Active Connection:**\n📥 Dest: `{bot_settings['conn_dest']}`\n📤 Sources: `{len(bot_settings.get('conn_sources', []))}`"
            else:
                text += "\n🔴 **No Active Connection**"
            
            try:
                bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown", reply_markup=get_conn_main_keyboard())
            except:
                bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=get_conn_main_keyboard())

        elif call.data == "conn_setup":
            user_states[chat_id] = {"stage": "conn_waiting_count"}
            send_clean_prompt(
                chat_id,
                "🔗 **Setup Connection**\n\n"
                "**Step 1:** How many **Source Channels** do you want to connect? (Where you will post files/content)\n\n"
                "Send a number (e.g., `1`, `2`, `10`).",
                parse_mode="Markdown"
            )

        elif call.data == "conn_view":
            dest = bot_settings.get("conn_dest", "")
            sources = bot_settings.get("conn_sources", [])
            if not dest:
                bot.send_message(chat_id, "❌ No active connection found.")
                return
            
            msg = "📊 **Active Connection:**\n━━━━━━━━━━━━━━━━━━━━━\n"
            msg += f"📥 **Destination Channel:**\n`{dest}`\n\n"
            msg += f"📤 **Source Channels ({len(sources)}):**\n"
            for idx, src in enumerate(sources, 1):
                msg += f"{idx}. `{src}`\n"
            
            bot.send_message(chat_id, msg, parse_mode="Markdown")

        elif call.data == "conn_settings":
            text = (
                "⚙️ **Copy Settings**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "Choose what type of content should be copied to the destination channel."
            )
            try:
                bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown", reply_markup=get_conn_settings_keyboard())
            except:
                bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=get_conn_settings_keyboard())

        elif call.data in ["conn_toggle_text", "conn_toggle_files", "conn_toggle_links"]:
            if "conn_settings" not in bot_settings:
                bot_settings["conn_settings"] = {"copy_text": True, "copy_files": True, "copy_links": True}
            
            if call.data == "conn_toggle_text":
                bot_settings["conn_settings"]["copy_text"] = not bot_settings["conn_settings"].get("copy_text", True)
            elif call.data == "conn_toggle_files":
                bot_settings["conn_settings"]["copy_files"] = not bot_settings["conn_settings"].get("copy_files", True)
            elif call.data == "conn_toggle_links":
                bot_settings["conn_settings"]["copy_links"] = not bot_settings["conn_settings"].get("copy_links", True)
                
            sync_db()
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=get_conn_settings_keyboard())
            except:
                pass

        elif call.data == "conn_remove":
            mk = InlineKeyboardMarkup(row_width=2)
            mk.add(
                InlineKeyboardButton("✅ Yes, Remove", callback_data="conn_remove_confirm"),
                InlineKeyboardButton("❌ Cancel", callback_data="conn_main")
            )
            text = (
                "⚠️ **Are you sure?**\n"
                "This will stop copying messages from sources to your destination channel."
            )
            try:
                bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown", reply_markup=mk)
            except:
                bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=mk)

        elif call.data == "conn_remove_confirm":
            bot_settings["conn_sources"] = []
            bot_settings["conn_dest"] = ""
            sync_db()
            send_clean_prompt(chat_id, "✅ Connection removed successfully!", reply_markup=get_conn_main_keyboard())

        # ============ DELETE MESSAGE FEATURE ============
        elif call.data == "del_main":
            user_states[chat_id] = {"stage": "waiting_for_del_channel_id"}
            send_clean_prompt(
                chat_id,
                "🗑️ **Delete Channel Message**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "**Step 1:** Send the Channel ID where the message is located.",
                parse_mode="Markdown"
            )

        elif call.data in ["del_cat_min", "del_cat_hour", "del_cat_day"]:
            st = user_states.get(chat_id)
            if not isinstance(st, dict) or st.get("stage") != "waiting_for_del_time":
                bot.answer_callback_query(call.id, "❌ Session expired!", show_alert=True)
                return
                
            unit = call.data.replace("del_cat_", "")
            st["time_unit"] = unit
            st["stage"] = "waiting_for_del_time_number"
            user_states[chat_id] = st

            if unit == "min":
                prompt = "⏱️ **How many MINUTES?**\n\nSend a number (e.g., `12`, `30`, `60`)"
            elif unit == "hour":
                prompt = "🕐 **How many HOURS?**\n\nSend a number (e.g., `2`, `6`, `24`)"
            else:
                prompt = "📅 **How many DAYS?**\n\nSend a number (e.g., `1`, `2`, `7`)"
                
            send_clean_prompt(chat_id, prompt, parse_mode="Markdown")

        elif call.data == "del_view":
            pending = [x for x in scheduled_deletions if not x.get("deleted")]
            if not pending:
                if chat_id in live_deletion_messages:
                    try: bot.delete_message(chat_id, live_deletion_messages[chat_id])
                    except: pass
                    del live_deletion_messages[chat_id]
                bot.send_message(chat_id, "❌ No pending scheduled deletions.")
                return
            
            msg, markup = generate_deletion_text(pending)
            try:
                bot.edit_message_text(msg, chat_id, message_id, parse_mode="Markdown", reply_markup=markup)
                live_deletion_messages[chat_id] = message_id
            except Exception as e:
                if "message is not modified" in str(e).lower():
                    live_deletion_messages[chat_id] = message_id
                else:
                    sent_msg = bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=markup)
                    live_deletion_messages[chat_id] = sent_msg.message_id

        elif call.data.startswith("del_cancel_"):
            cancel_id = call.data.split("del_cancel_")[-1]
            for i in range(len(scheduled_deletions)):
                if scheduled_deletions[i].get("id") == cancel_id:
                    scheduled_deletions.pop(i)
                    break
            sync_db()
            
            if chat_id in live_deletion_messages:
                pending = [x for x in scheduled_deletions if not x.get("deleted")]
                if not pending:
                    try:
                        bot.edit_message_text("❌ No pending scheduled deletions.", chat_id, live_deletion_messages[chat_id])
                    except: pass
                    del live_deletion_messages[chat_id]
                else:
                    msg, markup = generate_deletion_text(pending)
                    try:
                        bot.edit_message_text(msg, chat_id, live_deletion_messages[chat_id], parse_mode="Markdown", reply_markup=markup)
                    except: pass

        # ============ AUTO POST SCHEDULER ============
        elif call.data == "aps_main":
            if chat_id in live_schedule_messages:
                del live_schedule_messages[chat_id]  
            total_scheduled = len([x for x in scheduled_posts if not x.get("sent")])
            text = (
                "📤 **Auto Post Scheduler**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "Schedule posts to auto-send to your\n"
                "channels after a specific time.\n\n"
                f"📅 **Pending Scheduled:** `{total_scheduled}`\n\n"
                "**Choose Post Type:**"
            )
            try:
                bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown", reply_markup=get_aps_main_keyboard())
            except Exception as e:
                if "message is not modified" not in str(e).lower():
                    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=get_aps_main_keyboard())

        elif call.data == "aps_my_admin_channels":
            admin_chs = get_my_admin_channels()
            if not admin_chs:
                bot.send_message(
                    chat_id,
                    "❌ **No channels found!**\n\n"
                    "Add channels first from 📢 Channel Manager.",
                    parse_mode="Markdown"
                )
                return
            msg = "📋 **My Admin Channels:**\n━━━━━━━━━━━━━━━━━━━━━\n"
            for idx, ch in enumerate(admin_chs, 1):
                msg += f"\n{idx}. **{html.escape(ch['title'])}**\n"
                msg += f"   🆔 `{ch['chat_id']}`\n"
                if ch.get("username"):
                    msg += f"   🔗 @{ch['username']}\n"
                msg += f"   🤖 ✅ Bot is Admin\n"
            msg += "\n💡 Copy any Chat ID for scheduling."
            bot.send_message(chat_id, msg, parse_mode="Markdown")

        elif call.data in ["aps_type_file", "aps_type_photo", "aps_type_video"]:
            post_type = call.data.replace("aps_type_", "")
            user_states[chat_id] = {
                "stage": "aps_waiting_channel_count",
                "post_type": post_type
            }
            type_names = {"file": "📄 File Post", "photo": "🖼️ Photo Post", "video": "🎬 Video Post"}
            send_clean_prompt(
                chat_id,
                f"{type_names[post_type]}\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                "**Step 1/6: How many channels do you want to send to?**\n\n"
                "📢 Enter the number of channels (e.g., `1`, `2`, `5`)",
                parse_mode="Markdown"
            )
            
        # 🔥 NEW FEATURE: FORWARD POST START 🔥
        elif call.data == "aps_type_forward":
            user_states[chat_id] = {"stage": "aps_forward_waiting_channel_count"}
            send_clean_prompt(
                chat_id,
                "🔄 **Forward Post (Auto)**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                "**Step 1:** How many **Destination Channels** do you want to send the post to?\n\n"
                "Send a number (e.g., `1`, `2`, `5`).",
                parse_mode="Markdown"
            )
        # 🔥 NEW FEATURE: FORWARD POST END 🔥

        elif call.data == "aps_view_scheduled":
            pending = [x for x in scheduled_posts if not x.get("sent")]
            if not pending:
                if chat_id in live_schedule_messages:
                    try: bot.delete_message(chat_id, live_schedule_messages[chat_id])
                    except: pass
                    del live_schedule_messages[chat_id]
                bot.send_message(chat_id, "❌ No pending scheduled posts.")
                return
            
            msg, markup = generate_scheduled_text(pending)
            try:
                bot.edit_message_text(msg, chat_id, message_id, parse_mode="Markdown", reply_markup=markup)
                live_schedule_messages[chat_id] = message_id
            except Exception as e:
                if "message is not modified" in str(e).lower():
                    live_schedule_messages[chat_id] = message_id
                else:
                    sent_msg = bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=markup)
                    live_schedule_messages[chat_id] = sent_msg.message_id

        elif call.data.startswith("aps_cancel_"):
            cancel_id = call.data.split("aps_cancel_")[-1]
            for i in range(len(scheduled_posts)):
                if scheduled_posts[i].get("id") == cancel_id:
                    scheduled_posts.pop(i)
                    break
            sync_db()
            
            if chat_id in live_schedule_messages:
                pending = [x for x in scheduled_posts if not x.get("sent")]
                if not pending:
                    try:
                        bot.edit_message_text("❌ No pending scheduled posts.", chat_id, live_schedule_messages[chat_id])
                    except: pass
                    del live_schedule_messages[chat_id]
                else:
                    msg, markup = generate_scheduled_text(pending)
                    try:
                        bot.edit_message_text(msg, chat_id, live_schedule_messages[chat_id], parse_mode="Markdown", reply_markup=markup)
                    except: pass

        # 🔥 NEW: EDIT POST CALLBACK 🔥
        elif re.fullmatch(r"aps_edit_post_[0-9a-fA-F]+", call.data):
            post_id = call.data[len("aps_edit_"): ]
            target_item = None
            for item in scheduled_posts:
                if item.get("id") == post_id and not item.get("sent"):
                    target_item = item
                    break
            
            if not target_item:
                bot.answer_callback_query(call.id, "❌ Post not found or already sent!", show_alert=True)
                return
                
            user_states[chat_id] = {"stage": "aps_editing_post", "edit_post_id": post_id}
            
            # Build detailed summary
            files = target_item.get("files", [])
            total_files = len(files)
            
            # Caption and Buttons info
            cap_txt = "No Caption"
            btn_count = 0
            if total_files > 0:
                f0 = files[0]
                if f0.get("caption"): cap_txt = "✅ Has Caption"
                if f0.get("buttons"): btn_count = len(f0.get("buttons"))
            
            # Time info
            try:
                s_time = datetime.fromisoformat(target_item["scheduled_time"])
                t_str = s_time.strftime('%Y-%m-%d %H:%M')
            except:
                t_str = "Unknown"
                
            chs = target_item.get("channel_ids", [])
            ch_names = ", ".join([c.get("title", "Unknown") for c in chs])

            text = (
                f"✏️ **Editing Scheduled Post**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"📁 **Files:** `{total_files}`\n"
                f"📢 **Channels:** {html.escape(ch_names)}\n"
                f"📝 **Caption:** {cap_txt}\n"
                f"🔗 **Custom Buttons:** `{btn_count}`\n"
                f"⏰ **Scheduled For:** `{t_str}`\n\n"
                "What do you want to edit?"
            )
            
            mk = InlineKeyboardMarkup(row_width=1)
            mk.add(InlineKeyboardButton("✏️ Edit Caption (File 1)", callback_data="aps_edit_cap"))
            mk.add(InlineKeyboardButton("🔗 Edit Custom Buttons (File 1)", callback_data="aps_edit_btn"))
            mk.add(InlineKeyboardButton("⏰ Edit Time", callback_data="aps_edit_time"))
            mk.add(InlineKeyboardButton("🔙 Cancel Editing", callback_data="aps_view_scheduled"))
            
            try:
                bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown", reply_markup=mk)
            except Exception as e:
                if "message is not modified" not in str(e).lower():
                    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=mk)
            return
            
        elif call.data == "aps_edit_cap":
            st = user_states.get(chat_id)
            if not isinstance(st, dict) or not st.get("edit_post_id"):
                bot.answer_callback_query(call.id, "❌ Editing session expired. Open Edit Post again.", show_alert=True)
                return
            st["stage"] = "aps_edit_waiting_caption"
            user_states[chat_id] = st
            send_clean_prompt(chat_id, "✍️ **Send the new Caption for File 1:**\n\n(HTML formatting supported)", parse_mode="Markdown")
            return
            
        elif call.data == "aps_edit_btn":
            st = user_states.get(chat_id)
            if not isinstance(st, dict): return
            st["stage"] = "aps_edit_waiting_btn_count"
            user_states[chat_id] = st
            send_clean_prompt(chat_id, "🔢 **How many NEW custom buttons do you want to set?**\n\nSend a number (e.g., `1`, `2`, `3`)", parse_mode="Markdown")
            return
            
        elif call.data == "aps_edit_time":
            st = user_states.get(chat_id)
            if not isinstance(st, dict): return
            st["stage"] = "aps_edit_waiting_time"
            user_states[chat_id] = st
            
            mk = InlineKeyboardMarkup(row_width=3)
            mk.add(
                InlineKeyboardButton("⏱️ Mins", callback_data="aps_edit_time_min"),
                InlineKeyboardButton("🕐 Hours", callback_data="aps_edit_time_hour"),
                InlineKeyboardButton("📅 Days", callback_data="aps_edit_time_day")
            )
            mk.add(InlineKeyboardButton("🔙 Cancel", callback_data="aps_edit_cancel"))
            
            send_clean_prompt(chat_id, "⏰ **Select new Time Category:**", reply_markup=mk)
            return
            
        elif call.data.startswith("aps_edit_time_"):
            st = user_states.get(chat_id)
            if not isinstance(st, dict) or st.get("stage") != "aps_edit_waiting_time": return
            
            unit = call.data.replace("aps_edit_time_", "")
            st["edit_time_unit"] = unit
            st["stage"] = "aps_edit_waiting_time_number"
            user_states[chat_id] = st
            
            if unit == "min": prompt = "⏱️ How many MINUTES from now?"
            elif unit == "hour": prompt = "🕐 How many HOURS from now?"
            else: prompt = "📅 How many DAYS from now?"
            
            send_clean_prompt(chat_id, prompt)
            return
            
        elif call.data == "aps_edit_cancel":
            st = user_states.get(chat_id)
            if isinstance(st, dict):
                user_states[chat_id] = None
            bot.edit_message_text("❌ Editing Cancelled.", chat_id, message_id, reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 View Posts", callback_data="aps_view_scheduled")))
            return
        # 🔥 END EDIT POST CALLBACK 🔥

        elif call.data in ["aps_cat_min", "aps_cat_hour", "aps_cat_day"]:
            st = user_states.get(chat_id)
            if not isinstance(st, dict) or st.get("stage") != "aps_waiting_time":
                bot.answer_callback_query(call.id, "❌ Session expired!", show_alert=True)
                return
            unit = call.data.replace("aps_cat_", "")
            st["time_unit"] = unit
            user_states[chat_id] = st
            if unit == "min":
                prompt = "⏱️ **How many MINUTES?**\n\nSend a number (e.g., `12`, `30`, `60`)"
            elif unit == "hour":
                prompt = "🕐 **How many HOURS?**\n\nSend a number (e.g., `2`, `6`, `24`)"
            else:
                prompt = "📅 **How many DAYS?**\n\nSend a number (e.g., `1`, `2`, `7`)"
            send_clean_prompt(chat_id, prompt, parse_mode="Markdown")

        elif call.data == "aps_cap_text":
            st = user_states.get(chat_id)
            if not isinstance(st, dict):
                return
            st["stage"] = "aps_waiting_caption_text"
            user_states[chat_id] = st
            send_clean_prompt(
                chat_id,
                f"✍️ **Send the caption text for File {st['caption_index'] + 1}**\n\n"
                "You can use formatting, links, and emojis.",
                parse_mode="Markdown"
            )

        elif call.data == "aps_cap_reply":
            st = user_states.get(chat_id)
            if not isinstance(st, dict) or not st.get("files"):
                bot.answer_callback_query(call.id, "Session expired. Start the post again.", show_alert=True)
                return
            st["stage"] = "aps_waiting_reply_message"
            user_states[chat_id] = st
            send_clean_prompt(
                chat_id,
                "↩️ Forward the message you want to attach as a reply to this file. "
                "You can forward text, a photo, video, document, or voice message."
            )
            return

        elif call.data == "aps_cap_voice":
            st = user_states.get(chat_id)
            if not isinstance(st, dict):
                return
            st["stage"] = "aps_waiting_caption_voice"
            user_states[chat_id] = st
            send_clean_prompt(
                chat_id,
                f"🎤 **Send the voice message for File {st['caption_index'] + 1}**\n\n"
                "It will be sent to the channel along with the file.",
                parse_mode="Markdown"
            )

        elif call.data == "aps_cap_vtext":
            st = user_states.get(chat_id)
            if not isinstance(st, dict):
                return
            
            v_data = st["files"][st["caption_index"]].get("voice_data")
            if not v_data or not v_data.get("file_id"):
                bot.answer_callback_query(call.id, "❌ Please add a voice message first!", show_alert=True)
                return

            st["stage"] = "aps_waiting_voice_caption_text"
            user_states[chat_id] = st
            send_clean_prompt(
                chat_id,
                f"📝 **Send the text caption for the Voice message of File {st['caption_index'] + 1}**\n\n"
                "This will appear as the caption of the voice message.",
                parse_mode="Markdown"
            )

        # 🔥 NEW FEATURE: ADD CUSTOM BUTTONS FOR FILE & VOICE START 🔥
        elif call.data == "aps_cap_join_btn":
            st = user_states.get(chat_id)
            if not isinstance(st, dict) or not st.get("files"):
                bot.answer_callback_query(call.id, "No scheduled file is active.", show_alert=True)
                return
            st["stage"] = "aps_waiting_join_url"
            user_states[chat_id] = st
            send_clean_prompt(
                chat_id,
                "🔗 **Set Join Button Link**\n\nSend the exact channel/group invite URL for the Join button (https://t.me/... or https://t.me/+...).",
                parse_mode="Markdown"
            )

        elif call.data == "aps_cap_add_btn":
            st = user_states.get(chat_id)
            if not isinstance(st, dict):
                return
            st["stage"] = "aps_waiting_btn_count"
            st["target_btn_type"] = "file" # Targeting File Buttons
            user_states[chat_id] = st
            send_clean_prompt(
                chat_id,
                "🔢 **How many custom buttons do you want to add for the FILE?**\n\n"
                "Send a number (e.g., `1`, `2`, `5`).\n\n"
                "💡 For a Join button, use **Set Join Button Link** to save your exact invite URL.",
                parse_mode="Markdown"
            )

        elif call.data == "aps_cap_add_vbtn":
            st = user_states.get(chat_id)
            if not isinstance(st, dict):
                return
            st["stage"] = "aps_waiting_btn_count"
            st["target_btn_type"] = "voice" # Targeting Voice Buttons
            user_states[chat_id] = st
            send_clean_prompt(
                chat_id,
                "🔢 **How many custom buttons do you want to add for the VOICE?**\n\n"
                "Send a number (e.g., `1`, `2`, `5`).",
                parse_mode="Markdown"
            )
            
        elif call.data == "aps_btn_finish":
            st = user_states.get(chat_id)
            if not isinstance(st, dict):
                return
            
            # Return to caption menu based on current state
            st["stage"] = "aps_caption_menu"
            user_states[chat_id] = st
            
            if st.get("caption_added"):
                send_clean_prompt(
                    chat_id,
                    f"✅ **Buttons added for File {st['caption_index'] + 1}!**\n\n"
                    "Do you want to add File Text or proceed?",
                    reply_markup=get_aps_after_voice_keyboard()
                )
            else:
                send_clean_prompt(
                    chat_id,
                    f"✅ **Buttons added for File {st['caption_index'] + 1}!**\n\n"
                    "Add text or voice for this file?",
                    reply_markup=get_aps_caption_keyboard()
                )
        # 🔥 NEW FEATURE: ADD CUSTOM BUTTONS END 🔥

        elif call.data == "aps_cap_skip":
            st = user_states.get(chat_id)
            if not isinstance(st, dict):
                return
            
            st["caption_index"] += 1
            if st["caption_index"] < st["file_count"]:
                st["stage"] = "aps_waiting_caption_choice"
                user_states[chat_id] = st
                send_clean_prompt(
                    chat_id,
                    f"**Step 5/6: Caption for File {st['caption_index'] + 1}/{st['file_count']}**\n"
                    f"📁 `{html.escape(st['files'][st['caption_index']]['file_name'])}`\n\n"
                    "Add text, voice, or custom buttons for this file?",
                    parse_mode="Markdown",
                    reply_markup=get_aps_caption_keyboard()
                )
            else:
                st["stage"] = "aps_waiting_time"
                user_states[chat_id] = st
                send_clean_prompt(
                    chat_id,
                    "✅ **All files processed!**\n\n"
                    "**Step 6/6: Select time category:**\n"
                    "⏱️ Minutes | 🕐 Hours | 📅 Days",
                    parse_mode="Markdown",
                    reply_markup=get_aps_time_keyboard()
                )

        # ============ CHANNEL MANAGER ============
        elif call.data == "channel_manager":
            bot.edit_message_text(
                "📢 **Channel Manager**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "Manage your channels:",
                chat_id, message_id, parse_mode="Markdown",
                reply_markup=get_channel_manager_keyboard()
            )

        elif call.data in ["ch_add_1", "ch_add_2"]:
            slot = "1" if call.data == "ch_add_1" else "2"
            user_states[chat_id] = f"ch_waiting_link_{slot}"
            send_clean_prompt(
                chat_id,
                f"➕ **Add Channel {slot}**\n\n"
                "📎 Send the channel link or @username:\n\n"
                "✅ `https://t.me/yourchannel`\n"
                "✅ `@yourchannel`\n"
                "✅ `https://t.me/+InviteCode`\n"
                "✅ `-1001234567890`",
                parse_mode="Markdown"
            )

        elif call.data == "ch_add_more":
            user_states[chat_id] = "ch_more_waiting_name"
            send_clean_prompt(
                chat_id,
                "➕ **Add More Channel**\n\n"
                "📝 Enter a name for this channel:\n"
                "Example: `Channel 3`",
                parse_mode="Markdown"
            )

        elif call.data.startswith("chtype_public_"):
            slot = call.data.split("chtype_public_")[-1]
            stored = user_states.get(chat_id, {})
            link_input = stored.get("link", "") if isinstance(stored, dict) else ""
            username = extract_public_username(link_input)
            if not username:
                bot.answer_callback_query(call.id, "❌ Can't extract @username!", show_alert=True)
                return
            try:
                info = validate_channel(username)
                if not info:
                    send_clean_prompt(chat_id, f"❌ **Channel not found!**\n\n`{username}`", parse_mode="Markdown")
                    user_states[chat_id] = None
                    return
                is_admin = check_bot_admin(info["id"])
                if not is_admin:
                    send_clean_prompt(chat_id, f"❌ **Bot is NOT admin!**\n📢 {html.escape(info['title'])}\n🔗 {username}", parse_mode="Markdown")
                    user_states[chat_id] = None
                    return
                join_url = f"https://t.me/{username[1:]}"
                name = f"Channel {slot}" if slot in ["1", "2"] else slot
                add_channel(name, "public", join_url, username)
                send_clean_prompt(
                    chat_id,
                    f"✅ **SUCCESSFULLY VERIFIED!**\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📢 **{html.escape(info['title'])}**\n"
                    f"🔗 Join URL: `{join_url}`\n"
                    f"🆔 Chat ID: `{username}`\n"
                    f"📂 Type: 🌐 Public\n"
                    f"🤖 Bot: ✅ Admin",
                    parse_mode="Markdown", reply_markup=get_admin_panel_keyboard()
                )
                user_states[chat_id] = None
            except Exception as e:
                send_clean_prompt(chat_id, f"❌ Error: `{str(e)[:150]}`", parse_mode="Markdown")
                user_states[chat_id] = None
            return

        elif call.data.startswith("chtype_private_"):
            slot = call.data.split("chtype_private_")[-1]
            stored = user_states.get(chat_id, {})
            link_input = stored.get("link", "") if isinstance(stored, dict) else ""
            user_states[chat_id] = {"stage": "waiting_chat_id", "slot": slot, "link": link_input}
            send_clean_prompt(
                chat_id,
                "🔒 **Private Channel**\n\n"
                "📎 Send the **Chat ID** (`-100xxxxxxxxxx`)\n\n"
                "💡 Get it from `@userinfobot`",
                parse_mode="Markdown"
            )
            return

        elif call.data == "chtype_more_public":
            stored = user_states.get(chat_id, {})
            if not isinstance(stored, dict):
                return
            link_input = stored.get("link", "")
            name = stored.get("name", "Channel")
            username = extract_public_username(link_input)
            if not username:
                bot.answer_callback_query(call.id, "❌ Can't extract @username!", show_alert=True)
                return
            try:
                info = validate_channel(username)
                if not info:
                    send_clean_prompt(chat_id, f"❌ Channel not found: `{username}`", parse_mode="Markdown")
                    user_states[chat_id] = None
                    return
                is_admin = check_bot_admin(info["id"])
                if not is_admin:
                    send_clean_prompt(chat_id, f"❌ **Bot NOT admin!**\n📢 {html.escape(info['title'])}", parse_mode="Markdown")
                    user_states[chat_id] = None
                    return
                join_url = f"https://t.me/{username[1:]}"
                add_channel(name, "public", join_url, username)
                send_clean_prompt(
                    chat_id,
                    f"✅ **SUCCESSFULLY VERIFIED!**\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📢 **{html.escape(info['title'])}**\n"
                    f"🔗 Join URL: `{join_url}`\n"
                    f"🆔 Chat ID: `{username}`\n"
                    f"📂 Type: 🌐 Public\n"
                    f"🤖 Bot: ✅ Admin",
                    parse_mode="Markdown", reply_markup=get_channel_manager_keyboard()
                )
                user_states[chat_id] = None
            except Exception as e:
                send_clean_prompt(chat_id, f"❌ Error: `{str(e)[:150]}`", parse_mode="Markdown")
            return

        elif call.data == "chtype_more_private":
            stored = user_states.get(chat_id, {})
            if not isinstance(stored, dict):
                return
            user_states[chat_id] = {
                "stage": "waiting_chat_id",
                "slot": stored.get("name", "Channel"),
                "link": stored.get("link", "")
            }
            send_clean_prompt(chat_id, "🔒 **Private Channel**\n\n📎 Send the **Chat ID**", parse_mode="Markdown")
            return

        elif call.data == "ch_view_all":
            channels = get_all_channels()
            if not channels:
                bot.send_message(chat_id, "❌ No channels added yet.")
                return
            msg = "📢 **Your Channels:**\n━━━━━━━━━━━━━━━━━━━━━\n"
            for idx, ch in enumerate(channels, 1):
                ju = ch.get("join_url", "") or "❌"
                ci = ch.get("chat_id", "") or "❌"
                t = ch.get("type", "?")
                emoji = "🌐" if t == "public" else "🔒" if t == "private" else "❓"
                admin_status = "❓"
                try:
                    if ci and not ci.startswith("+"):
                        bi = bot.get_me()
                        m = bot.get_chat_member(ci, bi.id)
                        admin_status = "✅" if m.status in ['administrator', 'creator'] else "❌"
                except:
                    admin_status = "❌"
                msg += f"\n{idx}. {emoji} **{html.escape(ch['name'])}**\n   🔗 `{ju}`\n   🆔 `{ci}`\n   🤖 {admin_status}\n"
            bot.send_message(chat_id, msg, parse_mode="Markdown", disable_web_page_preview=True)

        elif call.data == "ch_delete_menu":
            channels = get_all_channels()
            if not channels:
                bot.send_message(chat_id, "❌ No channels.")
                return
            markup = InlineKeyboardMarkup(row_width=1)
            for ch in channels:
                t = ch.get("type", "?")
                emoji = "🌐" if t == "public" else "🔒" if t == "private" else "❓"
                markup.add(InlineKeyboardButton(
                    text=f"🗑️ {emoji} {ch['name']}",
                    callback_data=f"ch_del_{ch['id']}"
                ))
            markup.add(InlineKeyboardButton("🔙 Back", callback_data="channel_manager"))
            bot.send_message(chat_id, "🗑️ **Select channel to delete:**", reply_markup=markup, parse_mode="Markdown")

        elif call.data.startswith("ch_del_"):
            ch_id = call.data.split("ch_del_")[-1]
            remove_channel_by_id(ch_id)
            try:
                bot.delete_message(chat_id, message_id)
            except:
                pass
            bot.send_message(chat_id, "✅ Channel deleted!", reply_markup=get_channel_manager_keyboard())

        # ============ JOIN TEXT EDITOR ============
        elif call.data == "join_text_editor":
            current_title = bot_settings.get("force_join_title", "🔒 ACCESS RESTRICTED")
            current_msg = bot_settings.get("force_join_message", "📌 Join {count} channel(s) to continue")
            text = (
                "📝 **Join Text Editor**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "**📌 Current Title:**\n"
                f"`{html.escape(current_title)}`\n\n"
                "**📝 Current Message:**\n"
                f"`{html.escape(current_msg)}`\n\n"
                "💡 Use `{count}` to show channel count"
            )
            try:
                bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown",
                                      reply_markup=get_join_text_editor_keyboard())
            except Exception as e:
                if "message is not modified" not in str(e).lower():
                    bot.send_message(chat_id, text, parse_mode="Markdown",
                                     reply_markup=get_join_text_editor_keyboard())

        elif call.data == "jtext_edit_title":
            user_states[chat_id] = {"stage": "waiting_for_jtext_title"}
            send_clean_prompt(chat_id, "✏️ **Edit Title**\n\nSend new title text:", parse_mode="Markdown")

        elif call.data == "jtext_edit_msg":
            user_states[chat_id] = {"stage": "waiting_for_jtext_msg"}
            send_clean_prompt(chat_id, "✏️ **Edit Message**\n\nSend new message text:", parse_mode="Markdown")

        elif call.data == "jtext_edit_btns":
            channels = get_all_channels()
            if not channels:
                bot.send_message(chat_id, "❌ No channels added yet. Add channels from Channel Manager first.")
                return
            markup = InlineKeyboardMarkup(row_width=1)
            for ch in channels:
                markup.add(InlineKeyboardButton(f"📢 {ch['name']}", callback_data=f"jtext_btn_edit_{ch['id']}"))
            markup.add(InlineKeyboardButton("🔙 Back", callback_data="join_text_editor"))
            bot.send_message(chat_id, "Select a channel button to edit its name:", reply_markup=markup)

        elif call.data.startswith("jtext_btn_edit_"):
            ch_id = call.data.split("jtext_btn_edit_")[-1]
            user_states[chat_id] = {"stage": f"waiting_for_btn_name||{ch_id}"}
            send_clean_prompt(chat_id, "✏️ **Send the new name for this button:**", parse_mode="Markdown")

        elif call.data == "jtext_preview":
            real_chs = get_all_channels()
            if real_chs:
                preview_chs = real_chs
            else:
                preview_chs = [
                    {"name": "Channel 1", "join_url": "https://t.me/example1"},
                    {"name": "Channel 2", "join_url": "https://t.me/example2"}
                ]
            msg = get_join_message(preview_chs)
            markup = InlineKeyboardMarkup(row_width=2)
            btns = []
            for ch in preview_chs[:4]:
                name = ch.get("name", "Channel")
                btns.append(InlineKeyboardButton(f"📢 {name}", url="https://t.me/telegram"))
            for i in range(0, len(btns), 2):
                if i + 1 < len(btns):
                    markup.row(btns[i], btns[i + 1])
                else:
                    markup.row(btns[i])
            markup.row(InlineKeyboardButton("✅ Verify & Continue", callback_data="jtext_dummy"))
            markup.row(InlineKeyboardButton("🔙 Back to Editor", callback_data="join_text_editor"))
            bot.send_message(chat_id, msg, reply_markup=markup)

        elif call.data == "jtext_dummy":
            bot.answer_callback_query(call.id, "👁️ Preview only!", show_alert=True)

        elif call.data == "jtext_reset":
            bot_settings["force_join_title"] = "🔒 ACCESS RESTRICTED"
            bot_settings["force_join_message"] = "📌 Join {count} channel(s) to continue"
            sync_db()
            current_title = bot_settings["force_join_title"]
            current_msg = bot_settings["force_join_message"]
            text = (
                "📝 **Join Text Editor**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "**Reset Complete!** ✅\n\n"
                "**📌 Current Title:**\n"
                f"`{html.escape(current_title)}`\n\n"
                "**📝 Current Message:**\n"
                f"`{html.escape(current_msg)}`"
            )
            try:
                bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown",
                                      reply_markup=get_join_text_editor_keyboard())
            except Exception as e:
                if "message is not modified" not in str(e).lower():
                    pass

        # ============ OTHER ADMIN ============
        elif call.data == "admin_view_keys_count":
            keys = {k: v for k, v in file_database.items() if v.get("is_text_key", False)}
            if not keys:
                bot.send_message(chat_id, "🔑 No Secret Keys.")
                return
            bi = bot.get_me()
            bot.send_message(chat_id, f"🔑 **Total: `{len(keys)}`**", parse_mode="Markdown")
            for k, d in keys.items():
                link = f"https://t.me/{bi.username}?start={k}"
                mk = InlineKeyboardMarkup()
                mk.add(InlineKeyboardButton("📋 Copy Link", callback_data=f"copy_key|{k}"))
                mk.add(InlineKeyboardButton("🗑️ Delete", callback_data=f"inline_delete_{k}"))
                bot.send_message(chat_id, f"🔑 **{html.escape(d.get('panel_name', 'Unnamed'))}**\n🆔 `{k}`\n🔗 `{link}`", parse_mode="Markdown", reply_markup=mk)
            return

        elif call.data == "admin_giveaway":
            mk = InlineKeyboardMarkup(row_width=2)
            if giveaway.get("active"):
                mk.add(InlineKeyboardButton("🛑 End", callback_data="admin_end_giveaway"))
                st = f"🟢 Active\n🎁 {giveaway.get('prize')}\n👥 {len(giveaway.get('participants', []))}"
            else:
                mk.add(
                    InlineKeyboardButton("🎁 Start", callback_data="admin_start_giveaway"),
                    InlineKeyboardButton("📋 Winners", callback_data="admin_list_winners")
                )
                st = "🔴 Inactive"
            bot.edit_message_text(f"🎁 **Giveaway**\n\n{st}", chat_id, message_id, parse_mode="Markdown", reply_markup=mk)
        elif call.data == "admin_list_winners":
            w = giveaway.get("winners", [])
            if not w:
                bot.send_message(chat_id, "❌ No winners!")
                return
            m = "🏆 Winners:\n"
            for i, x in enumerate(w[-10:], 1):
                m += f"{i}. `{x.get('user_id')}` - {x.get('prize')}\n"
            bot.send_message(chat_id, m, parse_mode="Markdown")
        elif call.data == "admin_start_giveaway":
            user_states[chat_id] = {"stage": "waiting_for_giveaway_prize"}
            send_clean_prompt(chat_id, "🎁 Prize:")
        elif call.data == "admin_end_giveaway":
            if giveaway.get("active"):
                p = giveaway.get("participants", [])
                if p:
                    w = random.choice(p)
                    pr = giveaway.get("prize", "Prize")
                    if "winners" not in giveaway:
                        giveaway["winners"] = []
                    giveaway["winners"].append({"user_id": w, "prize": pr, "time": datetime.now().isoformat()})
                    bot.send_message(chat_id, f"🎉 Winner: `{w}` - {pr}", parse_mode="Markdown")
                giveaway["active"] = False
                giveaway["participants"] = []
                giveaway["end_time"] = None
                sync_db()

        elif call.data == "admin_auto_reply":
            mk = InlineKeyboardMarkup(row_width=1)
            mk.add(
                InlineKeyboardButton("➕ Add", callback_data="admin_add_auto_reply"),
                InlineKeyboardButton("📋 List", callback_data="admin_list_auto_reply"),
                InlineKeyboardButton("🔙 Back", callback_data="back_to_main")
            )
            bot.edit_message_text("📝 **Auto Reply**", chat_id, message_id, reply_markup=mk)
        elif call.data == "admin_add_auto_reply":
            user_states[chat_id] = {"stage": "waiting_for_auto_reply_keyword"}
            send_clean_prompt(chat_id, "📝 Keyword:")
        elif call.data == "admin_list_auto_reply":
            ar = bot_settings.get("auto_reply", {})
            if not ar:
                bot.send_message(chat_id, "❌ None.")
                return
            for k, r in ar.items():
                mk = InlineKeyboardMarkup()
                mk.add(InlineKeyboardButton("🗑️", callback_data=f"delete_auto_reply|{k}"))
                bot.send_message(chat_id, f"🔹 `{k}` → {r}", parse_mode="Markdown", reply_markup=mk)
        elif call.data.startswith("delete_auto_reply|"):
            k = call.data.split("delete_auto_reply|")[-1]
            if "auto_reply" in bot_settings and k in bot_settings["auto_reply"]:
                del bot_settings["auto_reply"][k]
                sync_db()
                bot.delete_message(chat_id, message_id)

        elif call.data == "admin_manage_admins":
            adm = bot_settings.get("sub_admins", [])
            al = "\n".join([f"• `{a}`" for a in adm]) if adm else "None"
            mk = InlineKeyboardMarkup(row_width=1)
            mk.add(
                InlineKeyboardButton("➕ Add", callback_data="admin_add_admin"),
                InlineKeyboardButton("🗑️ Remove", callback_data="admin_remove_admin"),
                InlineKeyboardButton("🔙 Back", callback_data="back_to_main")
            )
            bot.edit_message_text(f"👑 Admins:\n{al}", chat_id, message_id, parse_mode="Markdown", reply_markup=mk)
        elif call.data == "admin_add_admin":
            user_states[chat_id] = {"stage": "waiting_for_add_admin"}
            send_clean_prompt(chat_id, "👑 User ID:")
        elif call.data == "admin_remove_admin":
            user_states[chat_id] = {"stage": "waiting_for_remove_admin"}
            send_clean_prompt(chat_id, "👑 User ID:")

        elif call.data in ["admin_create_key", "admin_delete_file", "admin_broadcast",
                          "admin_ban_user", "admin_unban_user"]:
            mapping = {
                "admin_create_key": ("waiting_for_panel_name", "📝 Panel name:"),
                "admin_delete_file": ("waiting_for_delete_key", "🗑️ File ID:"),
                "admin_broadcast": ("waiting_for_broadcast", "📢 Message:"),
                "admin_ban_user": ("waiting_for_ban_user", "⛔ User ID:"),
                "admin_unban_user": ("waiting_for_unban_user", "✅ User ID:")
            }
            state, m = mapping[call.data]
            user_states[chat_id] = {"stage": state}
            send_clean_prompt(chat_id, m)

        elif call.data == "admin_view_users":
            us = list(registered_users)
            if not us:
                bot.send_message(chat_id, "❌ No users.")
                return
            m = f"👥 **Total: `{len(us)}`**\n\n"
            for i, uid in enumerate(us[:20], 1):
                try:
                    u = bot.get_chat(uid)
                    m += f"{i}. {html.escape(u.first_name or 'Unknown')} - `{uid}`\n"
                except:
                    m += f"{i}. `{uid}`\n"
            bot.send_message(chat_id, m, parse_mode="Markdown")

        elif call.data == "admin_view_files":
            if not file_database:
                bot.send_message(chat_id, "❌ No files uploaded yet.")
                return
            
            bi = bot.get_me()
            items = list(file_database.items())[-20:]
            
            for k, d in items:
                link = f"https://t.me/{bi.username}?start={k}"
                if d.get("is_text_key"):
                    t = (
                        f"🔑 <b>Panel:</b> {html.escape(d.get('panel_name', 'Unnamed'))}\n"
                        f"🆔 <b>ID:</b> <code>{k}</code>\n"
                        f"🔗 <b>Link:</b> {link}"
                    )
                else:
                    t = (
                        f"📁 <b>Name:</b> {html.escape(d.get('file_name', k[:8]))}\n"
                        f"🆔 <b>ID:</b> <code>{k}</code>\n"
                        f"🔗 <b>Link:</b> {link}"
                    )
                
                mk = InlineKeyboardMarkup(row_width=2)
                mk.add(InlineKeyboardButton("📋 Copy Link", callback_data=f"copy_key|{k}"))
                mk.add(InlineKeyboardButton("🗑️ Delete", callback_data=f"inline_delete_{k}"))
                
                bot.send_message(chat_id, t, parse_mode="HTML", reply_markup=mk, disable_web_page_preview=True)

        elif call.data.startswith("inline_delete_"):
            k = call.data.split("inline_delete_")[-1]
            if k in file_database:
                del file_database[k]
                sync_db()
                bot.delete_message(chat_id, message_id)

        elif call.data == "view_stats":
            kc = sum(1 for v in file_database.values() if v.get("is_text_key", False))
            pending = len([x for x in scheduled_posts if not x.get("sent")])
            pending_del = len([x for x in scheduled_deletions if not x.get("deleted")])
            bot.send_message(chat_id,
                f"📊 **Bot Statistics:**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"👥 Users: `{len(registered_users)}`\n"
                f"📁 Files: `{len(file_database)}`\n"
                f"🗂️ Projects: `{len(db.get('project_files', []))}`\n"
                f"🔑 Keys: `{kc}`\n"
                f"📢 Channels: `{len(get_all_channels())}`\n"
                f"🎭 Reaction Bots: `{len(bot_settings.get('reaction_bots', []))}`\n"
                f"⛔ Banned: `{len(banned_users)}`\n"
                f"📤 Pending Posts: `{pending}`\n"
                f"🗑️ Pending Deletions: `{pending_del}`\n"
                f"⭐ Points: `{sum(u.get('points', 0) for u in user_activity.values())}`",
                parse_mode="Markdown")

        elif call.data == "view_settings":
            chs = get_all_channels()
            t = (
                "📋 **Settings:**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔐 Force Join: {'✅ ON' if bot_settings['force_join'] else '❌ OFF'}\n"
                f"🛠️ Maintenance: {'ON' if bot_settings.get('maintenance_mode', False) else 'OFF'}\n\n"
                f"📢 **Channels ({len(chs)}):**"
            )
            for ch in chs:
                e = "🌐" if ch.get("type") == "public" else "🔒"
                t += f"\n{e} {html.escape(ch['name'])}: `{ch.get('join_url', '')}`"
            bot.send_message(chat_id, t, disable_web_page_preview=True)

        elif call.data == "back_to_main":
            if chat_id in live_schedule_messages:
                del live_schedule_messages[chat_id]
            if chat_id in live_deletion_messages:
                del live_deletion_messages[chat_id]
            try:
                bot.edit_message_text(f"👋 Welcome {BOT_NAME} Admin!\n🛠️ Bot Control Panel", chat_id, message_id, reply_markup=get_admin_panel_keyboard())
            except Exception as e:
                if "message is not modified" not in str(e).lower():
                    bot.send_message(chat_id, f"👋 Welcome {BOT_NAME} Admin!\n🛠️ Bot Control Panel", reply_markup=get_admin_panel_keyboard())
    except Exception as e:
        logger.error(f"Callback Handler Error: {e}")
        try:
            bot.answer_callback_query(call.id, f"❌ Error: {e}", show_alert=True)
        except:
            pass

# =====================================================
#           📁 MESSAGE COPIER (CONNECT CHANNEL) & REACTION
# =====================================================

def process_single_reaction(bot_data, message, delay=0):
    """Apply a configured reaction using the selected reaction-bot token."""
    if delay:
        time.sleep(delay)
    token = (bot_data.get("token") or "").strip()
    emoji = bot_data.get("emoji")
    bot_id = bot_data.get("bot_id", "Unknown")
    if not token or not emoji:
        logger.warning("Skipping reaction bot with missing token/emoji: %s", bot_id)
        return
    payload = {
        "chat_id": message.chat.id,
        "message_id": message.message_id,
        "reaction": [{"type": "emoji", "emoji": emoji}],
        "is_big": False
    }
    try:
        res = requests.post(f"https://api.telegram.org/bot{token}/setMessageReaction", json=payload, timeout=12)
        data = {}
        try:
            data = res.json()
        except Exception:
            pass
        if not res.ok or not data.get("ok", False):
            desc = data.get("description", res.text[:300] if res.text else "Unknown Telegram API error")
            logger.error("Reaction failed (%s) on chat %s message %s: %s", bot_id, message.chat.id, message.message_id, desc)
    except Exception as exc:
        logger.exception("Reaction request error (%s): %s", bot_id, exc)


def _reaction_channel_matches(configured_channel_id, message):
    """Match the configured channel itself and its linked discussion group."""
    if str(configured_channel_id) == str(message.chat.id):
        return True
    # A channel's replies live in its linked discussion supergroup. Resolve that
    # link so replies/forwarded posts in the discussion group can also react.
    try:
        cached = _reaction_link_cache.get(str(configured_channel_id))
        now = time.time()
        if not cached or now - cached[0] > 600:
            info = bot.get_chat(configured_channel_id)
            linked_id = getattr(info, "linked_chat_id", None)
            _reaction_link_cache[str(configured_channel_id)] = (now, linked_id)
        else:
            linked_id = cached[1]
        return linked_id is not None and str(linked_id) == str(message.chat.id)
    except Exception as exc:
        logger.debug("Could not resolve linked discussion group for %s: %s", configured_channel_id, exc)
        return False


_reaction_link_cache = {}


def schedule_reactions_for_message(message):
    """Schedule all reaction bots configured for this channel or linked discussion."""
    if not message or getattr(message.chat, "type", None) == "private":
        return
    try:
        for reaction_bot in list(bot_settings.get("reaction_bots", [])):
            channel_id = reaction_bot.get("channel_id")
            if channel_id is None or not _reaction_channel_matches(channel_id, message):
                continue
            delay = random.uniform(1.0, 2.5)
            threading.Thread(
                target=process_single_reaction,
                args=(reaction_bot, message, delay),
                daemon=True
            ).start()
    except Exception as exc:
        logger.exception("Reaction trigger error: %s", exc)


@bot.channel_post_handler(content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation', 'video_note', 'contact', 'location', 'venue', 'poll', 'dice'])
def auto_copy_source_messages(message):
    # React to manually published/forwarded posts in configured channels.
    schedule_reactions_for_message(message)

    # Copy source posts to the configured destination. Bot API does not send an
    # update back for the bot's own copied post, so trigger destination reactions
    # explicitly using the returned message ID.
    dest = bot_settings.get("conn_dest")
    if dest:
        try:
            bi = bot.get_me()
            if message.author_signature == bi.first_name or (message.from_user and message.from_user.id == bi.id):
                return
            if str(message.chat.id) == str(dest):
                return

            sources = bot_settings.get("conn_sources", [])
            if sources and str(message.chat.id) not in {str(x) for x in sources}:
                return

            settings = bot_settings.get("conn_settings", {"copy_text": True, "copy_files": True, "copy_links": True})
            is_text = bool(message.text)
            is_media = bool(message.photo or message.video or message.document or message.audio or message.voice or message.sticker or message.animation or getattr(message, "video_note", None))
            check_text = message.text or message.caption or ""
            has_link = bool(re.search(r"https?://|t\.me/", check_text, re.I))

            if is_text and not is_media:
                if not settings.get("copy_text", True):
                    return
                if has_link and not settings.get("copy_links", True):
                    return
            elif is_media:
                if not settings.get("copy_files", True):
                    return
                if has_link and not settings.get("copy_links", True):
                    return

            copied = bot.copy_message(dest, message.chat.id, message.message_id)
            copied_id = getattr(copied, "message_id", None)
            if copied_id:
                copied_message = SimpleNamespace(
                    chat=SimpleNamespace(id=int(dest), title="Connected destination", type="channel"),
                    message_id=copied_id
                )
                schedule_reactions_for_message(copied_message)
        except Exception as exc:
            logger.error("Auto copy failed from %s to %s: %s", message.chat.id, dest, exc)


@bot.message_handler(func=lambda m: getattr(m.chat, "type", None) in ("group", "supergroup"), content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation', 'video_note', 'contact', 'location', 'venue', 'poll', 'dice'])
def react_to_discussion_messages(message):
    # Includes ordinary group posts, forwarded files, and replies in a linked
    # channel discussion group. This handler intentionally does not copy them.
    schedule_reactions_for_message(message)

# =====================================================
#           📁 FILE UPLOAD & FORWARD HANDLER
# =====================================================

@bot.message_handler(content_types=['document', 'photo', 'video', 'audio', 'voice', 'sticker', 'animation', 'video_note'])
def handle_admin_files(message):
    try:
        if message.chat.type != 'private':
            return
            
        uid = message.from_user.id
        chat_id = message.chat.id
        st = user_states.get(chat_id)

        if uid == ADMIN_ID and is_admin_logged_in(uid) and isinstance(st, dict) and st.get("stage") == "project_waiting_file":
            fid, ftype, fname = _project_file_kind(message)
            if not fid:
                send_clean_prompt(chat_id, "❌ Unsupported file type. Please upload a document, APK, ZIP, photo, video, audio, or another supported Telegram file.")
                return
            st["pending_project"] = {
                "id": uuid.uuid4().hex[:10],
                "name": st.get("project_name", "Unnamed project"),
                "file_id": fid,
                "file_type": ftype,
                "file_name": fname,
                "uploaded_at": datetime.now().isoformat()
            }
            st["stage"] = "project_confirm"
            user_states[chat_id] = st
            send_clean_prompt(
                chat_id,
                f"👁️ **Project Preview**\n━━━━━━━━━━━━━━━━━━━━━\n📦 Name: **{html.escape(st['pending_project']['name'])}**\n📎 File: `{html.escape(fname)}`\n\nSave this project or close without saving?",
                parse_mode="Markdown",
                reply_markup=get_project_confirm_keyboard()
            )
            return

        if isinstance(st, dict) and "last_bot_msg" in st:
            clean_msg(chat_id, st["last_bot_msg"])
            st["last_bot_msg"] = None

        if uid == ADMIN_ID and is_admin_logged_in(uid):
            if isinstance(st, dict) and st.get("stage") == "aps_forward_waiting_source_message":
                origin = getattr(message, "forward_from_chat", None)
                origin_message_id = getattr(message, "forward_from_message_id", None)
                if not origin or not origin_message_id:
                    send_clean_prompt(
                        chat_id,
                        "❌ This message does not include a forwardable channel source. "
                        "Please use Telegram's Forward option on a post from a channel and send it here."
                    )
                    return
                st["post_type"] = "forward"
                st["files"] = [{
                    "file_id": origin_message_id,
                    "file_type": "forward",
                    "from_chat_id": origin.id,
                    "file_name": "Forwarded Telegram Post",
                    "caption": "",
                    "buttons": [],
                    "voice_data": None,
                    "voice_buttons": []
                }]
                st["stage"] = "aps_waiting_time"
                user_states[chat_id] = st
                time_markup = InlineKeyboardMarkup(row_width=3)
                time_markup.add(
                    InlineKeyboardButton("⏱️ Minutes", callback_data="aps_cat_min"),
                    InlineKeyboardButton("🕐 Hours", callback_data="aps_cat_hour"),
                    InlineKeyboardButton("📅 Days", callback_data="aps_cat_day")
                )
                time_markup.add(InlineKeyboardButton("🔙 Cancel", callback_data="aps_main"))
                send_clean_prompt(
                    chat_id,
                    "✅ Source post received!\n\nStep 4: Select when to forward it.",
                    reply_markup=time_markup
                )
                return

            if isinstance(st, dict) and st.get("stage") == "aps_waiting_reply_message":
                origin = getattr(message, "forward_from_chat", None)
                origin_message_id = getattr(message, "forward_from_message_id", None)
                if not origin or not origin_message_id:
                    send_clean_prompt(chat_id, "❌ Please forward a message directly from the target channel. The file will reply to that original channel post.")
                    return
                st["files"][st["caption_index"]]["reply_data"] = {
                    "target_chat_id": origin.id,
                    "target_message_id": origin_message_id
                }
                st["stage"] = "aps_caption_menu"
                user_states[chat_id] = st
                send_clean_prompt(
                    chat_id,
                    f"✅ Reply target saved for File {st['caption_index'] + 1}. When scheduled, the file itself will reply to that original channel post (no extra copied text).",
                    reply_markup=get_aps_caption_keyboard()
                )
                return
            if isinstance(st, dict) and st.get("stage") == "waiting_for_del_message":
                try:
                    bot.delete_message(chat_id, message.message_id)
                except:
                    pass

                msg_id = None
                msg_date = None
                
                if message.forward_from_chat and message.forward_from_message_id:
                    msg_id = message.forward_from_message_id
                    fwd_chat_id = str(message.forward_from_chat.id)
                    msg_date = message.forward_date
                    
                    user_states[chat_id] = {
                        "stage": "waiting_for_del_time",
                        "channel_id": fwd_chat_id,
                        "channel_title": message.forward_from_chat.title,
                        "message_id": msg_id,
                        "message_date": msg_date
                    }
                    
                    if msg_date and (time.time() - msg_date > 48 * 3600):
                        send_clean_prompt(
                            chat_id,
                            f"✅ **Message found!**\n"
                            f"🆔 ID: `{msg_id}`\n\n"
                            "❌ **Telegram API Limit:**\n"
                            "Bots cannot delete messages that are older than 48 hours (2 days). The message you forwarded is older than 48 hours, so it cannot be deleted by the bot.",
                            parse_mode="Markdown"
                        )
                        user_states[chat_id] = None
                        return
                    
                    send_clean_prompt(
                        chat_id,
                        f"✅ **Message found!**\n"
                        f"🆔 ID: `{msg_id}`\n\n"
                        "**Step 3: Select time category for deletion:**",
                        parse_mode="Markdown",
                        reply_markup=get_del_time_keyboard()
                    )
                else:
                    send_clean_prompt(chat_id, "❌ Please forward a message directly from the channel.")
                return

            if isinstance(st, dict) and st.get("stage") == "aps_waiting_files":
                try:
                    bot.delete_message(chat_id, message.message_id)
                except:
                    pass

                post_type = st.get("post_type", "file")
                fid, ftype, fname = None, None, None

                if message.document:
                    fid, ftype, fname = message.document.file_id, 'document', message.document.file_name or f"doc_{uuid.uuid4().hex[:6]}"
                elif message.photo:
                    fid, ftype, fname = message.photo[-1].file_id, 'photo', f"img_{uuid.uuid4().hex[:6]}.jpg"
                elif message.video:
                    fid, ftype, fname = message.video.file_id, 'video', message.video.file_name or f"vid_{uuid.uuid4().hex[:6]}.mp4"
                elif message.audio:
                    fid, ftype, fname = message.audio.file_id, 'audio', message.audio.file_name or f"aud_{uuid.uuid4().hex[:6]}.mp3"
                elif message.sticker:
                    fid, ftype, fname = message.sticker.file_id, 'sticker', f"sticker_{uuid.uuid4().hex[:6]}.webp"
                elif message.animation:
                    fid, ftype, fname = message.animation.file_id, 'animation', message.animation.file_name or f"gif_{uuid.uuid4().hex[:6]}.mp4"

                if fid:
                    st["files"].append({
                        "file_id": fid, 
                        "file_type": ftype, 
                        "from_chat_id": message.chat.id,
                        "file_name": fname,
                        "caption": "",
                        "buttons": [], # 🔥 File Buttons 🔥
                        "voice_data": None,
                        "voice_buttons": [] # 🔥 Voice Buttons 🔥
                    })
                    st["current_file_index"] += 1
                    
                    if st["current_file_index"] < st["file_count"]:
                        send_clean_prompt(
                            chat_id,
                            f"✅ **File added!** ({st['current_file_index']}/{st['file_count']})\n\n"
                            f"**Step 4/6: Send file {st['current_file_index'] + 1}/{st['file_count']}**",
                            parse_mode="Markdown"
                        )
                    else:
                        st["stage"] = "aps_waiting_caption_choice"
                        st["caption_index"] = 0
                        send_clean_prompt(
                            chat_id,
                            f"✅ **All {st['file_count']} files received!**\n\n"
                            f"**Step 5/6: Caption for File 1/{st['file_count']}**\n"
                            f"📁 `{html.escape(st['files'][0]['file_name'])}`\n\n"
                            "Add text, voice, or custom buttons to send with this file?\n"
                            "Or skip to continue.",
                            parse_mode="Markdown",
                            reply_markup=get_aps_caption_keyboard()
                        )
                    user_states[chat_id] = st
                else:
                    send_clean_prompt(chat_id, "❌ Please send the correct file type.")
                return
                
            if isinstance(st, dict) and st.get("stage") == "aps_waiting_caption_voice":
                try:
                    bot.delete_message(chat_id, message.message_id)
                except:
                    pass

                if message.voice:
                    fid = message.voice.file_id
                    st["files"][st["caption_index"]]["voice_data"] = {"file_id": fid, "caption": ""}
                    st["stage"] = "aps_caption_menu"
                    user_states[chat_id] = st
                    
                    send_clean_prompt(
                        chat_id,
                        f"✅ **Voice added for File {st['caption_index'] + 1}!**\n\n"
                        "Do you want to add File Text or Voice Text?",
                        reply_markup=get_aps_after_voice_keyboard()
                    )
                else:
                    send_clean_prompt(chat_id, "❌ Please send a voice message.")
                return

        if uid != ADMIN_ID:
            if message.chat.type == 'private':
                bot.reply_to(message, "❌ Not authorized!")
            return
        if not is_admin_logged_in(uid):
            send_clean_prompt(chat_id, "🔐 Login first!", reply_markup=get_login_keyboard())
            return

        fid, ftype, fname = None, None, None
        if message.document:
            fid, ftype, fname = message.document.file_id, 'document', message.document.file_name or f"doc_{uuid.uuid4().hex[:6]}"
        elif message.photo:
            fid, ftype, fname = message.photo[-1].file_id, 'photo', f"img_{uuid.uuid4().hex[:6]}.jpg"
        elif message.video:
            fid, ftype, fname = message.video.file_id, 'video', message.video.file_name or f"vid_{uuid.uuid4().hex[:6]}.mp4"
        elif message.audio:
            fid, ftype, fname = message.audio.file_id, 'audio', message.audio.file_name or f"aud_{uuid.uuid4().hex[:6]}.mp3"
        elif message.sticker:
            fid, ftype, fname = message.sticker.file_id, 'sticker', f"sticker_{uuid.uuid4().hex[:6]}.webp"
        elif message.animation:
            fid, ftype, fname = message.animation.file_id, 'animation', message.animation.file_name or f"gif_{uuid.uuid4().hex[:6]}.mp4"
        elif getattr(message, "video_note", None):
            fid, ftype, fname = message.video_note.file_id, 'video_note', f"video_note_{uuid.uuid4().hex[:6]}.mp4"

        if fid:
            key = "file_" + str(uuid.uuid4().hex[:8])
            file_database[key] = {
                "file_id": fid, "file_type": ftype, "file_name": fname,
                "is_text_key": False, "uploaded_at": datetime.now().isoformat()
            }
            sync_db()
            bi = bot.get_me()
            link = f"https://t.me/{bi.username}?start={key}"
            
            mk = InlineKeyboardMarkup()
            mk.add(InlineKeyboardButton("📋 Copy Link", callback_data=f"copy_key|{key}"))
            
            safe_fname = html.escape(fname)
            
            bot.send_message(chat_id,
                f"✅ <b>File Uploaded & Link Generated!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"📁 <b>Name:</b> <code>{safe_fname}</code>\n"
                f"🆔 <b>ID:</b> <code>{key}</code>\n"
                f"🔗 <b>Shareable Link:</b>\n{link}\n\n"
                "ℹ️ <b>Note:</b> When a user clicks this link, they will be asked to join your Force-Join channels first (if enabled). After verifying, they will receive this specific file.",
                parse_mode="HTML", reply_markup=mk, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"File Handler Error: {e}")
        try:
            bot.reply_to(message, f"❌ Error processing file: {e}")
        except:
            pass

# =====================================================
#           📝 TEXT HANDLER
# =====================================================

@bot.message_handler(func=lambda m: True)
def handle_messages(message):
    try:
        if message.chat.type != 'private':
            return
            
        chat_id = message.chat.id
        user_id = message.from_user.id
        text = message.text

        if is_user_banned(user_id):
            bot.send_message(chat_id, "⛔ Banned!")
            return
        if user_id != ADMIN_ID and bot_settings.get("maintenance_mode", False):
            bot.send_message(chat_id, "🔧 Maintenance.")
            return

        if user_id not in registered_users:
            registered_users.add(user_id)
            log_user_activity(user_id, "registered")
            sync_db()

        if text:
            ar = bot_settings.get("auto_reply", {})
            for k, r in ar.items():
                if k.lower() in text.lower():
                    bot.send_message(chat_id, r)
                    return

        st = user_states.get(chat_id)

        if isinstance(st, dict) and st.get("stage") == "project_waiting_name":
            project_name = (text or "").strip()
            if not project_name:
                send_clean_prompt(chat_id, "❌ Project name cannot be empty. Send the project name:")
                return
            st["project_name"] = project_name[:100]
            st["stage"] = "project_waiting_file"
            user_states[chat_id] = st
            send_clean_prompt(chat_id, f"📁 Project name: **{html.escape(st['project_name'])}**\n\nNow upload the project file (APK, ZIP, Python, document, photo, video, etc.).", parse_mode="Markdown")
            return

        if isinstance(st, dict) and st.get("stage") == "aps_forward_waiting_source_message":
            origin = getattr(message, "forward_from_chat", None)
            origin_message_id = getattr(message, "forward_from_message_id", None)
            if not origin or not origin_message_id:
                send_clean_prompt(chat_id, "Please forward a post directly from its source channel.")
                return
            st["post_type"] = "forward"
            st["files"] = [{
                "file_id": origin_message_id,
                "file_type": "forward",
                "from_chat_id": origin.id,
                "file_name": "Forwarded Telegram Post",
                "caption": "",
                "buttons": [],
                "voice_data": None,
                "voice_buttons": []
            }]
            st["stage"] = "aps_waiting_time"
            user_states[chat_id] = st
            time_markup = InlineKeyboardMarkup(row_width=3)
            time_markup.add(
                InlineKeyboardButton("⏱️ Minutes", callback_data="aps_cat_min"),
                InlineKeyboardButton("🕐 Hours", callback_data="aps_cat_hour"),
                InlineKeyboardButton("📅 Days", callback_data="aps_cat_day")
            )
            time_markup.add(InlineKeyboardButton("🔙 Cancel", callback_data="aps_main"))
            send_clean_prompt(chat_id, "✅ Source post received!\n\nStep 4: Select when to forward it.", reply_markup=time_markup)
            return

        if isinstance(st, dict) and st.get("stage") == "aps_waiting_reply_message":
            origin = getattr(message, "forward_from_chat", None)
            origin_message_id = getattr(message, "forward_from_message_id", None)
            if not origin or not origin_message_id:
                send_clean_prompt(chat_id, "Please forward the original post directly from the target channel. The scheduled file itself will reply to that post.")
                return
            st["files"][st["caption_index"]]["reply_data"] = {
                "target_chat_id": origin.id,
                "target_message_id": origin_message_id
            }
            st["stage"] = "aps_caption_menu"
            user_states[chat_id] = st
            send_clean_prompt(
                chat_id,
                f"✅ Reply target saved for File {st['caption_index'] + 1}. The file itself will be sent as a reply; the forwarded text will not be copied separately.",
                reply_markup=get_aps_caption_keyboard()
            )
            return

        if isinstance(st, dict) and st.get("stage") in [
            "waiting_for_del_channel_id", "waiting_for_del_time_number",
            "aps_waiting_channel_count", "aps_waiting_channel_id", "aps_waiting_file_count",
            "aps_waiting_caption_text", "aps_waiting_voice_caption_text", "aps_waiting_time",
            "waiting_for_jtext_title", "waiting_for_jtext_msg", "waiting_for_welcome_text",
            "waiting_ch_admin_link", "waiting_chat_id", "waiting_for_btn_name",
            "conn_waiting_count", "conn_waiting_source", "conn_waiting_dest",
            "aps_waiting_files", "waiting_for_del_message", "ub_waiting_count", 
            "ub_waiting_keys", "ub_waiting_phone", "ub_waiting_code", "ub_waiting_2fa",
            "rb_waiting_count", "rb_waiting_token", "rb_waiting_channel", "rb_waiting_emoji", "rb_repeat_channel_choice",
            "rb_editing_emoji", "rb_saved_wait_count", "rb_saved_wait_token", "rb_saved_confirm",
            # 🔥 NEW STATES FOR CUSTOM BUTTONS & EDITING & FORWARD 🔥
            "aps_waiting_btn_count", "aps_waiting_btn_name", "aps_waiting_btn_url",
            "aps_edit_waiting_caption", "aps_edit_waiting_btn_count", "aps_edit_waiting_btn_name", 
            "aps_edit_waiting_btn_url", "aps_edit_waiting_time_number",
            "aps_forward_waiting_channel_count", "aps_forward_waiting_channel_id", 
            "aps_forward_waiting_source_channel", "aps_forward_waiting_time"
        ] or (isinstance(st, str) and (st.startswith("ch_waiting_link_") or st.startswith("waiting_for_btn_name||") or st.startswith("waiting_for_auto_reply_response||") or st.startswith("waiting_for_secret_value||"))):
            try:
                bot.delete_message(chat_id, message.message_id)
            except:
                pass
            if isinstance(st, dict) and "last_bot_msg" in st:
                clean_msg(chat_id, st["last_bot_msg"])
                st["last_bot_msg"] = None

        if user_id == ADMIN_ID:
            # ===== SAVED REACTION BOT TOKEN VAULT =====
            if isinstance(st, dict) and st.get("stage") == "rb_saved_wait_count":
                try:
                    count = int(text.strip())
                    if count <= 0 or count > 50:
                        send_clean_prompt(chat_id, "❌ Enter a number between 1 and 50."); return
                    st.update({"total_saved": count, "saved_collected": [], "stage": "rb_saved_wait_token"})
                    user_states[chat_id] = st
                    send_clean_prompt(chat_id, f"🔑 **Send Bot Token 1/{count}:**", parse_mode="Markdown")
                except ValueError:
                    send_clean_prompt(chat_id, "❌ Enter numbers only.")
                return

            if isinstance(st, dict) and st.get("stage") == "rb_saved_wait_token":
                token = text.strip()
                if ":" not in token or len(token) < 20:
                    send_clean_prompt(chat_id, "❌ Token format looks invalid. Send the Telegram BotFather token again."); return
                bot_id = token.split(":", 1)[0]
                if any(x.get("token") == token for x in bot_settings.get("saved_bot_tokens", [])) or any(x.get("token") == token for x in st.get("saved_collected", [])):
                    send_clean_prompt(chat_id, "⚠️ This token is already saved or entered in this batch. Send a different token."); return
                st.setdefault("saved_collected", []).append({"token": token, "bot_id": bot_id})
                current = len(st["saved_collected"]); total = st["total_saved"]
                if current < total:
                    user_states[chat_id] = st
                    send_clean_prompt(chat_id, f"✅ Token {current}/{total} received.\n\n🔑 **Send Bot Token {current+1}/{total}:**", parse_mode="Markdown")
                else:
                    st["stage"] = "rb_saved_confirm"
                    user_states[chat_id] = st
                    mk = InlineKeyboardMarkup(row_width=2)
                    mk.add(InlineKeyboardButton("💾 Save Tokens", callback_data="rb_saved_confirm_save"), InlineKeyboardButton("❌ Cancel", callback_data="rb_saved_confirm_cancel"))
                    send_clean_prompt(chat_id, f"✅ All {total} token(s) received. Press Save Tokens to store them securely in the bot database.", reply_markup=mk)
                return

            # ===== REACTION BOT FLOW (UPDATED AS REQUESTED) =====
            if isinstance(st, dict) and st.get("stage") == "rb_waiting_count":
                try:
                    count = int(text.strip())
                    if count <= 0 or count > 20:
                        send_clean_prompt(chat_id, "❌ Enter a number between 1 and 20.")
                        return
                    st["total_bots"] = count
                    st["current_index"] = 0
                    st["tokens_collected"] = []  # Store tokens first
                    st["stage"] = "rb_waiting_token"
                    user_states[chat_id] = st
                    send_clean_prompt(chat_id, f"✅ **Need to add {count} Bots.**\n\n🔑 **Send Bot Token 1/{count}:**", parse_mode="Markdown")
                except:
                    send_clean_prompt(chat_id, "❌ Enter numbers only.")
                return

            if isinstance(st, dict) and st.get("stage") == "rb_waiting_token":
                token = text.strip()
                if ":" not in token or len(token) < 20:
                    send_clean_prompt(chat_id, "❌ Invalid Bot Token! Send again (Format: 123456:ABC-DEF1234ghIkl-zyx).")
                    return
                
                bot_id = token.split(":")[0]
                st["tokens_collected"].append({
                    "token": token,
                    "bot_id": bot_id,
                    "emoji": None # Placeholder for later
                })
                
                curr = len(st["tokens_collected"])
                target = st["total_bots"]
                
                if curr < target:
                    st["stage"] = "rb_waiting_token"
                    user_states[chat_id] = st
                    send_clean_prompt(chat_id, f"✅ **Token {curr}/{target} added!**\n\n🔑 **Send Bot Token {curr+1}/{target}:**", parse_mode="Markdown")
                else:
                    st["stage"] = "rb_waiting_channel"
                    user_states[chat_id] = st
                    send_clean_prompt(chat_id, f"✅ **All {target} Tokens added successfully!**\n\n📢 **Now send the Channel ID where you want to add these bots:**", parse_mode="Markdown")
                return

            if isinstance(st, dict) and st.get("stage") == "rb_waiting_channel":
                ch_input = text.strip()
                cid = extract_chat_id(ch_input)
                
                if not cid:
                    info = validate_channel(ch_input)
                    if not info:
                        send_clean_prompt(chat_id, "❌ Invalid Channel ID or Channel not found! Send again:")
                        return
                    cid = str(info["id"])
                else:
                    info = validate_channel(cid)
                    if not info:
                        send_clean_prompt(chat_id, "❌ Channel not found! Send again:")
                        return

                # Verify each selected bot using that bot's own token.
                # This confirms the actual selected bot is an administrator.
                verified_bots = []
                not_admin_bots = []
                verification_errors = []

                for b_data in st["tokens_collected"]:
                    try:
                        token_value = b_data.get("token", "")
                        token_bot = telebot.TeleBot(token_value, threaded=False)
                        me = token_bot.get_me()
                        b_data["bot_id"] = str(me.id)
                        bot_member = token_bot.get_chat_member(cid, me.id)
                        is_admin = bot_member.status in ["administrator", "creator"]
                        if is_admin:
                            verified_bots.append(b_data)
                        else:
                            not_admin_bots.append(b_data)
                    except Exception as e:
                        not_admin_bots.append(b_data)
                        verification_errors.append(
                            f"Bot {b_data.get('bot_id', 'Unknown')}: {str(e)[:120]}"
                        )

                # Prepare status message
                status_msg = ""
                if not not_admin_bots:
                    status_msg = f"✅ **Verified Admin in Channel**\n🎉 **All {len(verified_bots)} bots are admin in {html.escape(info['title'])}!**\n"
                else:
                    status_msg = f"❌ **Not Verified Admin in Channel**\n⚠️ {len(not_admin_bots)} bots are NOT admin in {html.escape(info['title'])}!\n\n"
                    for nb in not_admin_bots:
                        status_msg += f"  • Bot ID: `{nb['bot_id']}` (Not Admin)\n"
                    status_msg += "\nPlease promote the bots to admin and enter the channel ID again."

                if not verified_bots:
                    user_states[chat_id] = st
                    send_clean_prompt(
                        chat_id,
                        status_msg + "\n\n❌ No selected bot could be verified as an administrator. Add the selected bots as channel admins with permission to post/reactions, then send the channel ID again.",
                        parse_mode="Markdown"
                    )
                    return

                st["current_channel_id"] = cid
                st["current_channel_title"] = info["title"]
                st["verified_bots"] = verified_bots
                st["current_bot_index"] = 0 # Start asking emoji for first bot
                st["stage"] = "rb_waiting_emoji"
                user_states[chat_id] = st
                
                # Now ask for emoji for the first bot
                first_bot = verified_bots[0]
                send_clean_prompt(
                    chat_id, 
                    f"{status_msg}\n\n"
                    f"🎭 Now, send the emoji you want **Bot {first_bot['bot_id']}** to react with (e.g., 👍, ❤️, 🔥):", 
                    parse_mode="Markdown"
                )
                return

            if isinstance(st, dict) and st.get("stage") == "rb_waiting_emoji":
                emoji = text.strip()
                if not emoji:
                    send_clean_prompt(chat_id, "❌ Emoji cannot be empty!")
                    return
                
                # Save emoji for current bot
                curr_idx = st["current_bot_index"]
                st["verified_bots"][curr_idx]["emoji"] = emoji
                
                curr_idx += 1
                target_count = len(st["verified_bots"])
                
                if curr_idx < target_count:
                    # Ask for next bot's emoji
                    st["current_bot_index"] = curr_idx
                    user_states[chat_id] = st
                    next_bot = st["verified_bots"][curr_idx]
                    send_clean_prompt(
                        chat_id, 
                        f"✅ **Emoji set for Bot {st['verified_bots'][curr_idx-1]['bot_id']}!**\n\n"
                        f"🎭 Now, send the emoji you want **Bot {next_bot['bot_id']}** to react with (e.g., 👍, ❤️, 🔥):", 
                        parse_mode="Markdown"
                    )
                else:
                    # All emojis set, save to DB
                    if "reaction_bots" not in bot_settings:
                        bot_settings["reaction_bots"] = []
                    
                    for b_data in st["verified_bots"]:
                        new_bot = {
                            "token": b_data["token"],
                            "bot_id": b_data["bot_id"],
                            "channel_id": st["current_channel_id"],
                            "channel_title": st["current_channel_title"],
                            "emoji": b_data["emoji"]
                        }
                        bot_settings["reaction_bots"].append(new_bot)
                    
                    sync_db()

                    # Retain the selected tokens so the same bots can be configured
                    # for more than one channel in the same setup session.
                    st["stage"] = "rb_repeat_channel_choice"
                    st["last_saved_channel_id"] = st["current_channel_id"]
                    st["last_saved_channel_title"] = st["current_channel_title"]
                    st["verified_bots"] = []
                    st["current_bot_index"] = 0
                    user_states[chat_id] = st

                    next_markup = InlineKeyboardMarkup(row_width=1)
                    next_markup.add(
                        InlineKeyboardButton("➕ Add Another Channel", callback_data="rb_add_another_channel"),
                        InlineKeyboardButton("✅ Finish Setup", callback_data="rb_finish_multi_channel")
                    )
                    configured_channels = {
                        str(item.get("channel_id")): item.get("channel_title", "Unknown")
                        for item in bot_settings.get("reaction_bots", [])
                        if item.get("channel_id")
                    }
                    channel_summary = "\\n".join(
                        f"• {html.escape(title)} (`{html.escape(cid)}`)"
                        for cid, title in configured_channels.items()
                    ) or "• No channels configured"

                    send_clean_prompt(
                        chat_id,
                        f"✅ **All {target_count} Reaction Bots added for this channel!** 🎉\\n\\n"
                        f"📢 **Current channel:** {html.escape(st['current_channel_title'])}\\n"
                        f"🎭 Each selected bot's emoji has been saved separately.\\n\\n"
                        f"📚 **Configured channels ({len(configured_channels)}):**\\n{channel_summary}\\n\\n"
                        "You can add another channel using the same selected tokens, or finish setup.",
                        parse_mode="HTML",
                        reply_markup=next_markup
                    )
                return

            # EDIT REACTION EMOJI FLOW
            if isinstance(st, dict) and st.get("stage") == "rb_editing_emoji":
                emoji = text.strip()
                if not emoji:
                    send_clean_prompt(chat_id, "❌ Emoji cannot be empty!")
                    return
                
                idx = st.get("edit_idx")
                bots = bot_settings.get("reaction_bots", [])
                
                if 0 <= idx < len(bots):
                    old_emoji = bots[idx].get("emoji")
                    bots[idx]["emoji"] = emoji
                    sync_db()
                    
                    user_states[chat_id] = None
                    send_clean_prompt(
                        chat_id,
                        f"✅ **Emoji updated successfully!**\n\n"
                        f"🤖 **Bot:** `{bots[idx].get('bot_id')}`\n"
                        f"📢 **Channel:** {bots[idx].get('channel_title')}\n"
                        f"🎭 **Old Emoji:** {old_emoji}\n"
                        f"✨ **New Emoji:** {emoji}\n\n"
                        "This bot will now react using the new emoji.",
                        parse_mode="Markdown",
                        reply_markup=get_admin_panel_keyboard()
                    )
                else:
                    send_clean_prompt(chat_id, "❌ Bot not found.", reply_markup=get_admin_panel_keyboard())
                    user_states[chat_id] = None
                return

            # ==================================

            # ===== MULTI-KEY USERBOT FLOW =====
            if isinstance(st, dict) and st.get("stage") == "ub_waiting_count":
                try:
                    count = int(text.strip())
                    if count <= 0 or count > 20:
                        send_clean_prompt(chat_id, "❌ Enter a number between 1 and 20.")
                        return
                    st["total_keys"] = count
                    st["collected_keys"] = []
                    st["stage"] = "ub_waiting_keys"
                    user_states[chat_id] = st
                    send_clean_prompt(chat_id, f"✅ **Need to add {count} Keys.**\n\n🔑 **Send the first API Key:**", parse_mode="Markdown")
                except:
                    send_clean_prompt(chat_id, "❌ Enter numbers only.")
                return

            if isinstance(st, dict) and st.get("stage") == "ub_waiting_keys":
                api_key = text.strip()
                if len(api_key) < 20:
                    send_clean_prompt(chat_id, "❌ Invalid Key! Send again.")
                    return
                st["collected_keys"].append(api_key)
                curr = len(st["collected_keys"])
                target = st["total_keys"]
                if curr < target:
                    user_states[chat_id] = st
                    send_clean_prompt(chat_id, f"✅ Key {curr}/{target} added.\n\n🔑 **Send the next API Key:**", parse_mode="Markdown")
                else:
                    st["stage"] = "ub_waiting_phone"
                    user_states[chat_id] = st
                    send_clean_prompt(chat_id, f"✅ **All {target} Keys added successfully!**\n\n📱 **Now send your Telegram Number (e.g., +8801...):**", parse_mode="Markdown")
                return

            if isinstance(st, dict) and st.get("stage") == "ub_waiting_phone":
                phone = text.strip().replace(" ", "")
                if not phone.startswith("+") or len(phone) < 10:
                    send_clean_prompt(chat_id, "❌ Invalid number. Use `+880...` format.")
                    return

                sm = send_clean_prompt(chat_id, "⏳ Sending OTP...")
                try:
                    if not USERBOT_AVAILABLE:
                        send_clean_prompt(chat_id, "❌ userbot.py not found on server!")
                        user_states[chat_id] = None
                        return
                    res = run_async(ub_module.start_userbot(phone, st["collected_keys"], user_id))
                except Exception as e:
                    send_clean_prompt(chat_id, f"❌ Error: {e}")
                    user_states[chat_id] = None
                    return

                if not res.get("ok"):
                    send_clean_prompt(chat_id, f"❌ {res.get('msg')}")
                    user_states[chat_id] = None
                    return

                st["phone"] = phone
                st["stage"] = "ub_waiting_code"
                user_states[chat_id] = st
                send_clean_prompt(chat_id, f"📨 **Enter OTP Code**\n\nCode sent to `{phone}`.", parse_mode="Markdown")
                return

            if isinstance(st, dict) and st.get("stage") == "ub_waiting_code":
                code = text.strip().replace(" ", "")
                phone = st.get("phone")
                try:
                    res = run_async(ub_module.verify_code(phone, code))
                except Exception as e:
                    send_clean_prompt(chat_id, f"❌ Error: {e}")
                    return

                if not res.get("ok"):
                    if res.get("msg") == "2FA_PASSWORD_REQUIRED":
                        st["stage"] = "ub_waiting_2fa"
                        user_states[chat_id] = st
                        send_clean_prompt(chat_id, "🔐 **Enter 2FA Password:**", parse_mode="Markdown")
                        return
                    send_clean_prompt(chat_id, f"❌ {res.get('msg')}\nEnter code again:")
                    return

                user_states[chat_id] = None
                send_clean_prompt(
                    chat_id,
                    f"✅ **AI Activated Successfully!** 🎉\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📱 Phone: `{phone}`\n"
                    f"🔑 Keys: `{len(st['collected_keys'])}`\n"
                    "🤖 Mode: Auto-Fallback (Multi-Key)\n\n"
                    "If one Key reaches its limit, the bot will use the next Key automatically!",
                    parse_mode="Markdown", reply_markup=get_admin_panel_keyboard()
                )
                return

            if isinstance(st, dict) and st.get("stage") == "ub_waiting_2fa":
                pwd = text.strip()
                phone = st.get("phone")
                try:
                    info = ub_module.ACTIVE_CLIENTS.get(phone)
                    if not info:
                        send_clean_prompt(chat_id, "❌ Session not found.")
                        user_states[chat_id] = None
                        return
                    client = info["client"]
                    async def _do_2fa():
                        await client.sign_in(password=pwd)
                        return True
                    run_async(_do_2fa())
                    info["logged_in"] = True
                    keys = info["api_keys"]
                    
                    from telethon import events
                    @client.on(events.NewMessage())
                    async def auto_reply(event, ph=phone):
                        try:
                            if not event.is_private:
                                return
                            ut = event.message.text or ""
                            if not ut.strip() or ut.startswith("🤖 AI:"):
                                return
                            k = ub_module.ACTIVE_CLIENTS[ph]["api_keys"]
                            reply = await ub_module.process_and_reply(k, ut)
                            if reply:
                                await asyncio.sleep(random.randint(1, 3))
                                await event.reply(reply)
                        except Exception as e:
                            logger.error(f"2FA reply err: {e}")

                    import asyncio as _aio
                    _aio.create_task(client.run_until_disconnected())

                    d = ub_module.load_ub()
                    d[phone] = {"user_id": user_id, "api_keys": keys, "logged_in": True, "connected_at": datetime.now().isoformat()}
                    ub_module.save_ub(d)

                    user_states[chat_id] = None
                    send_clean_prompt(
                        chat_id,
                        f"✅ **AI Activated (2FA)!** 🎉\n📱 `{phone}`\n🔑 Keys: `{len(keys)}`",
                        parse_mode="Markdown",
                        reply_markup=get_admin_panel_keyboard()
                    )
                except Exception as e:
                    send_clean_prompt(chat_id, f"❌ 2FA Error: {e}")
                    user_states[chat_id] = None
                return

            # ===== HANDLE DELETE MESSAGE (FORWARDED TEXT) =====
            if isinstance(st, dict) and st.get("stage") == "waiting_for_del_message":
                msg_id = None
                msg_date = None
                
                if message.forward_from_chat and message.forward_from_message_id:
                    msg_id = message.forward_from_message_id
                    fwd_chat_id = str(message.forward_from_chat.id)
                    msg_date = message.forward_date
                    
                    user_states[chat_id] = {
                        "stage": "waiting_for_del_time",
                        "channel_id": fwd_chat_id,
                        "channel_title": message.forward_from_chat.title,
                        "message_id": msg_id,
                        "message_date": msg_date
                    }
                    
                    if msg_date and (time.time() - msg_date > 48 * 3600):
                        send_clean_prompt(
                            chat_id,
                            f"✅ **Message found!**\n"
                            f"🆔 ID: `{msg_id}`\n\n"
                            "❌ **Telegram API Limit:**\n"
                            "Bots cannot delete messages that are older than 48 hours (2 days). The message you forwarded is older than 48 hours, so it cannot be deleted by the bot.",
                            parse_mode="Markdown"
                        )
                        user_states[chat_id] = None
                        return
                    
                    send_clean_prompt(
                        chat_id,
                        f"✅ **Message found!**\n"
                        f"🆔 ID: `{msg_id}`\n\n"
                        "**Step 3: Select time category for deletion:**",
                        parse_mode="Markdown",
                        reply_markup=get_del_time_keyboard()
                    )
                else:
                    send_clean_prompt(chat_id, "❌ Please forward a message directly from the channel.")
                return

            if isinstance(st, dict) and st.get("stage") == "waiting_for_welcome_text":
                new_welcome = message.text
                bot_settings["welcome_message"] = new_welcome
                sync_db()
                user_states[chat_id] = None
                
                text_editor = (
                    "👋 **Welcome Message Editor**\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    "✅ **Updated Successfully!**\n\n"
                    "**Current Welcome Message:**\n\n"
                    f"{new_welcome}\n\n"
                    "💡 Use `{name}` for user's first name."
                )
                send_clean_prompt(chat_id, text_editor, parse_mode="HTML", reply_markup=get_welcome_editor_keyboard())
                return

            if isinstance(st, dict) and st.get("stage") == "aps_waiting_files":
                text_content = message.html_text if message.html_text else message.text
                st["files"].append({
                    "file_id": message.message_id,
                    "file_type": "text",
                    "from_chat_id": message.chat.id,
                    "file_name": "Text/Link Post",
                    "caption": text_content, 
                    "buttons": [], # 🔥 File Buttons 🔥
                    "voice_data": None,
                    "voice_buttons": [] # 🔥 Voice Buttons 🔥
                })
                st["current_file_index"] += 1
                
                if st["current_file_index"] < st["file_count"]:
                    send_clean_prompt(
                        chat_id,
                        f"✅ **Content added!** ({st['current_file_index']}/{st['file_count']})\n\n"
                        f"**Step 4/6: Send content {st['current_file_index'] + 1}/{st['file_count']}**",
                        parse_mode="Markdown"
                    )
                else:
                    st["stage"] = "aps_waiting_caption_choice"
                    st["caption_index"] = 0
                    send_clean_prompt(
                        chat_id,
                        f"✅ **All {st['file_count']} contents received!**\n\n"
                        f"**Step 5/6: Caption for File 1/{st['file_count']}**\n"
                        f"📁 `{html.escape(st['files'][0]['file_name'])}`\n\n"
                        "Add text, voice, or custom buttons to send with this file?\n"
                        "Or skip to continue.",
                        parse_mode="Markdown",
                        reply_markup=get_aps_caption_keyboard()
                    )
                user_states[chat_id] = st
                return

            # Dedicated scheduler Join button URL input.
            if isinstance(st, dict) and st.get("stage") == "aps_waiting_join_url":
                join_url = text.strip()
                if not (join_url.startswith("https://") or join_url.startswith("http://")):
                    send_clean_prompt(chat_id, "❌ Invalid URL. Send a link beginning with https:// or http://")
                    return
                try:
                    c_idx = st["caption_index"]
                    if "buttons" not in st["files"][c_idx]:
                        st["files"][c_idx]["buttons"] = []
                    # Replace an existing Join button rather than adding duplicates.
                    st["files"][c_idx]["buttons"] = [b for b in st["files"][c_idx]["buttons"] if b.get("name", "").strip().lower() != "join"]
                    st["files"][c_idx]["buttons"].append({"name": "🔗 Join", "url": join_url})
                    st["caption_added"] = True
                    st["stage"] = "aps_caption_menu"
                    user_states[chat_id] = st
                    send_clean_prompt(
                        chat_id,
                        "✅ **Join button link saved for this scheduled post.**\n\nYou can continue adding caption, buttons, or skip to the next step.",
                        parse_mode="Markdown",
                        reply_markup=get_aps_caption_keyboard()
                    )
                except Exception as e:
                    logger.error(f"Join button URL save failed: {e}")
                    send_clean_prompt(chat_id, "❌ Could not save the Join link. Please try again.")
                return

            # 🔥 NEW FEATURE: ADD CUSTOM BUTTONS INPUT FLOW 🔥
            if isinstance(st, dict) and st.get("stage") == "aps_waiting_btn_count":
                try:
                    count = int(text.strip())
                    if count <= 0 or count > 10:
                        send_clean_prompt(chat_id, "❌ Please enter a number between 1 and 10.")
                        return
                    st["temp_btn_count"] = count
                    st["temp_buttons"] = []
                    st["temp_btn_index"] = 0
                    st["stage"] = "aps_waiting_btn_name"
                    user_states[chat_id] = st
                    send_clean_prompt(chat_id, f"✅ **{count} buttons selected.**\n\n📝 **Enter Name for Button 1/{count}:**")
                except:
                    send_clean_prompt(chat_id, "❌ Enter numbers only.")
                return

            if isinstance(st, dict) and st.get("stage") == "aps_waiting_btn_name":
                btn_name = text.strip()
                if not btn_name:
                    send_clean_prompt(chat_id, "❌ Name cannot be empty.")
                    return
                st["temp_buttons"].append({"name": btn_name, "url": ""})
                st["stage"] = "aps_waiting_btn_url"
                user_states[chat_id] = st
                send_clean_prompt(chat_id, f"✅ Name: **{html.escape(btn_name)}**\n\n🔗 **Now send the Link (URL) for Button {st['temp_btn_index']+1}:**", parse_mode="Markdown")
                return

            if isinstance(st, dict) and st.get("stage") == "aps_waiting_btn_url":
                btn_url = text.strip()
                if not (btn_url.startswith("http://") or btn_url.startswith("https://") or btn_url.startswith("tg://")):
                    send_clean_prompt(chat_id, "❌ Invalid Link! Make sure it starts with `http://` or `https://`.")
                    return
                
                st["temp_buttons"][st["temp_btn_index"]]["url"] = btn_url
                st["temp_btn_index"] += 1
                curr = st["temp_btn_index"]
                target = st["temp_btn_count"]
                
                if curr < target:
                    st["stage"] = "aps_waiting_btn_name"
                    user_states[chat_id] = st
                    send_clean_prompt(chat_id, f"✅ **Link added!**\n\n📝 **Enter Name for Button {curr+1}/{target}:**")
                else:
                    # Save these buttons to the current file or voice based on target_btn_type
                    c_idx = st["caption_index"]
                    target_type = st.get("target_btn_type", "file")
                    
                    if target_type == "voice":
                        if "voice_buttons" not in st["files"][c_idx]:
                            st["files"][c_idx]["voice_buttons"] = []
                        st["files"][c_idx]["voice_buttons"].extend(st["temp_buttons"])
                    else:
                        if "buttons" not in st["files"][c_idx]:
                            st["files"][c_idx]["buttons"] = []
                        st["files"][c_idx]["buttons"].extend(st["temp_buttons"])
                    
                    st["caption_added"] = True
                    st["stage"] = "aps_caption_menu"
                    user_states[chat_id] = st
                    
                    # Show finish options
                    finish_mk = InlineKeyboardMarkup()
                    finish_mk.add(InlineKeyboardButton("➕ Add More Buttons", callback_data="aps_cap_add_btn"))
                    finish_mk.add(InlineKeyboardButton("✅ Finish & Return", callback_data="aps_btn_finish"))
                    
                    send_clean_prompt(
                        chat_id,
                        f"✅ **All {target} buttons successfully added!**\n\n"
                        "Do you want to add more buttons or finish?",
                        reply_markup=finish_mk
                    )
                return
            # 🔥 NEW FEATURE END 🔥

            # ============ EDIT POST FLOW ============
            if isinstance(st, dict) and st.get("stage") == "aps_edit_waiting_caption":
                post_id = st.get("edit_post_id")
                caption = message.html_text if message.html_text else text.strip()
                
                for item in scheduled_posts:
                    if item.get("id") == post_id:
                        if item.get("files") and len(item["files"]) > 0:
                            item["files"][0]["caption"] = caption
                        break
                sync_db()
                
                user_states[chat_id] = None
                send_clean_prompt(chat_id, "✅ **Caption Updated Successfully!**", reply_markup=get_admin_panel_keyboard())
                # Refresh the schedule view
                pending = [x for x in scheduled_posts if not x.get("sent")]
                msg, markup = generate_scheduled_text(pending)
                bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=markup)
                return
                
            if isinstance(st, dict) and st.get("stage") == "aps_edit_waiting_btn_count":
                try:
                    count = int(text.strip())
                    if count <= 0 or count > 10:
                        send_clean_prompt(chat_id, "❌ Please enter a number between 1 and 10.")
                        return
                    st["temp_btn_count"] = count
                    st["temp_buttons"] = []
                    st["temp_btn_index"] = 0
                    st["stage"] = "aps_edit_waiting_btn_name"
                    user_states[chat_id] = st
                    send_clean_prompt(chat_id, f"✅ **{count} buttons selected.**\n\n📝 **Enter Name for Button 1/{count}:**")
                except:
                    send_clean_prompt(chat_id, "❌ Enter numbers only.")
                return
                
            if isinstance(st, dict) and st.get("stage") == "aps_edit_waiting_btn_name":
                btn_name = text.strip()
                if not btn_name:
                    send_clean_prompt(chat_id, "❌ Name cannot be empty.")
                    return
                st["temp_buttons"].append({"name": btn_name, "url": ""})
                st["stage"] = "aps_edit_waiting_btn_url"
                user_states[chat_id] = st
                send_clean_prompt(chat_id, f"✅ Name: **{html.escape(btn_name)}**\n\n🔗 **Now send the Link (URL) for Button {st['temp_btn_index']+1}:**", parse_mode="Markdown")
                return
                
            if isinstance(st, dict) and st.get("stage") == "aps_edit_waiting_btn_url":
                btn_url = text.strip()
                if not (btn_url.startswith("http://") or btn_url.startswith("https://") or btn_url.startswith("tg://")):
                    send_clean_prompt(chat_id, "❌ Invalid Link! Make sure it starts with `http://` or `https://`.")
                    return
                
                st["temp_buttons"][st["temp_btn_index"]]["url"] = btn_url
                st["temp_btn_index"] += 1
                curr = st["temp_btn_index"]
                target = st["temp_btn_count"]
                
                if curr < target:
                    st["stage"] = "aps_edit_waiting_btn_name"
                    user_states[chat_id] = st
                    send_clean_prompt(chat_id, f"✅ **Link added!**\n\n📝 **Enter Name for Button {curr+1}/{target}:**")
                else:
                    post_id = st.get("edit_post_id")
                    for item in scheduled_posts:
                        if item.get("id") == post_id:
                            if item.get("files") and len(item["files"]) > 0:
                                item["files"][0]["buttons"] = st["temp_buttons"]
                            break
                    sync_db()
                    
                    user_states[chat_id] = None
                    send_clean_prompt(chat_id, "✅ **Custom Buttons Updated Successfully!**", reply_markup=get_admin_panel_keyboard())
                    # Refresh the schedule view
                    pending = [x for x in scheduled_posts if not x.get("sent")]
                    msg, markup = generate_scheduled_text(pending)
                    bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=markup)
                return
                
            if isinstance(st, dict) and st.get("stage") == "aps_edit_waiting_time_number":
                try:
                    num = int(text.strip())
                    if num <= 0:
                        send_clean_prompt(chat_id, "❌ Number must be > 0")
                        return
                except:
                    send_clean_prompt(chat_id, "❌ Send a valid number")
                    return
                    
                unit = st.get("edit_time_unit")
                if unit == "min": seconds = num * 60
                elif unit == "hour": seconds = num * 3600
                else: seconds = num * 86400
                
                new_time = (datetime.now() + timedelta(seconds=seconds)).isoformat()
                post_id = st.get("edit_post_id")
                
                for item in scheduled_posts:
                    if item.get("id") == post_id:
                        item["scheduled_time"] = new_time
                        break
                sync_db()
                
                user_states[chat_id] = None
                send_clean_prompt(chat_id, f"✅ **Schedule Time Updated Successfully!**\n\nNew Time: `{datetime.fromisoformat(new_time).strftime('%Y-%m-%d %H:%M')}`", reply_markup=get_admin_panel_keyboard())
                # Refresh the schedule view
                pending = [x for x in scheduled_posts if not x.get("sent")]
                msg, markup = generate_scheduled_text(pending)
                bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=markup)
                return
            # ============ EDIT POST FLOW END ============

            # ============ FORWARD POST FLOW START ============
            if isinstance(st, dict) and st.get("stage") == "aps_forward_waiting_channel_count":
                try:
                    count = int(text.strip())
                    if count <= 0 or count > 50:
                        send_clean_prompt(chat_id, "❌ Please enter a number between 1 and 50.")
                        return
                    st["channel_count"] = count
                    st["channel_ids"] = []
                    st["stage"] = "aps_forward_waiting_channel_id"
                    user_states[chat_id] = st
                    send_clean_prompt(chat_id, f"✅ **{count} channels selected.**\n\n📢 **Step 2: Send Destination Channel ID 1/{count}:**")
                except ValueError:
                    send_clean_prompt(chat_id, "❌ Please enter numbers only (e.g., 2).")
                return

            if isinstance(st, dict) and st.get("stage") == "aps_forward_waiting_channel_id":
                ch_id_input = text.strip()
                info = validate_channel(ch_id_input)
                if not info:
                    send_clean_prompt(chat_id, f"❌ **Channel not found!**\n\n`{ch_id_input}`\nPlease enter the correct ID again:")
                    return
                is_admin = check_bot_admin(info["id"])
                if not is_admin:
                    send_clean_prompt(chat_id, f"❌ **Bot is NOT admin in this channel!**\n📢 {html.escape(info['title'])}\nPlease enter the correct ID again:")
                    return

                st["channel_ids"].append({
                    "id": str(info["id"]),
                    "title": info["title"]
                })
                current_count = len(st["channel_ids"])
                target_count = st["channel_count"]

                if current_count < target_count:
                    st["stage"] = "aps_forward_waiting_channel_id"
                    user_states[chat_id] = st
                    send_clean_prompt(chat_id, f"✅ **Channel added successfully!** ({current_count}/{target_count})\n\n📢 **Send Destination Channel ID {current_count + 1}/{target_count}:**")
                else:
                    st["stage"] = "aps_forward_waiting_source_message"
                    user_states[chat_id] = st
                    send_clean_prompt(
                        chat_id,
                        f"✅ **All {target_count} destination channels verified!**\n\n"
                        "**Step 3: Forward the exact post you want to send to this bot.**\n"
                        "Open the source channel, tap Forward, and send that post here.",
                        parse_mode="Markdown"
                    )
                return

            if isinstance(st, dict) and st.get("stage") == "aps_forward_waiting_source_channel":
                ch_id_input = text.strip()
                info = validate_channel(ch_id_input)
                if not info:
                    send_clean_prompt(chat_id, f"❌ **Channel not found!**\n\n`{ch_id_input}`\nPlease enter the correct ID again:")
                    return
                is_admin = check_bot_admin(info["id"])
                if not is_admin:
                    send_clean_prompt(chat_id, f"❌ **Bot is NOT admin in this channel!**\n📢 {html.escape(info['title'])}\nPlease enter the correct ID again:")
                    return

                st["source_channel_id"] = str(info["id"])
                st["source_channel_title"] = info["title"]
                st["stage"] = "aps_forward_waiting_time"
                user_states[chat_id] = st
                
                mk = InlineKeyboardMarkup(row_width=3)
                mk.add(
                    InlineKeyboardButton("⏱️ Minutes", callback_data="aps_forward_time_min"),
                    InlineKeyboardButton("🕐 Hours", callback_data="aps_forward_time_hour"),
                    InlineKeyboardButton("📅 Days", callback_data="aps_forward_time_day")
                )
                mk.add(InlineKeyboardButton("🔙 Cancel", callback_data="aps_main"))
                
                send_clean_prompt(
                    chat_id,
                    f"✅ **Source Channel Verified!**\n📢 {html.escape(info['title'])}\n\n"
                    "**Step 4: Select Time Category to Auto-Forward:**",
                    parse_mode="Markdown",
                    reply_markup=mk
                )
                return
            # ============ FORWARD POST FLOW END ============

            # ============ CONNECT CHANNEL FLOW ============
            if isinstance(st, dict) and st.get("stage") == "conn_waiting_count":
                try:
                    count = int(text.strip())
                    if count <= 0 or count > 50:
                        send_clean_prompt(chat_id, "❌ Please enter a valid number (1-50).")
                        return
                    st["conn_count"] = count
                    st["conn_sources"] = []
                    st["stage"] = "conn_waiting_source"
                    user_states[chat_id] = st
                    send_clean_prompt(chat_id, f"✅ **{count} sources selected.**\n\n📢 **Source ID 1/{count}:**")
                except ValueError:
                    send_clean_prompt(chat_id, "❌ Numbers only.")
                return

            if isinstance(st, dict) and st.get("stage") == "conn_waiting_source":
                cid = extract_chat_id(text.strip())
                if not cid:
                    send_clean_prompt(chat_id, "❌ Invalid Chat ID!")
                    return
                info = validate_channel(cid)
                if not info:
                    send_clean_prompt(chat_id, "❌ Channel not found!")
                    return
                if not check_bot_admin(info["id"]):
                    send_clean_prompt(chat_id, f"❌ Bot is NOT admin in `{info['title']}`! Please promote bot.")
                    return

                st["conn_sources"].append(str(info["id"]))
                curr = len(st["conn_sources"])
                target = st["conn_count"]
                
                if curr < target:
                    st["stage"] = "conn_waiting_source"
                    user_states[chat_id] = st
                    send_clean_prompt(chat_id, f"✅ **Source added!** ({curr}/{target})\n\n📢 **Source ID {curr + 1}/{target}:**")
                else:
                    st["stage"] = "conn_waiting_dest"
                    user_states[chat_id] = st
                    send_clean_prompt(
                        chat_id,
                        f"✅ **All {target} source channels verified!**\n\n"
                        "Now, send your **Destination Channel ID** (Where messages will be copied).",
                        parse_mode="Markdown"
                    )
                return

            if isinstance(st, dict) and st.get("stage") == "conn_waiting_dest":
                cid = extract_chat_id(text.strip())
                if not cid:
                    send_clean_prompt(chat_id, "❌ Invalid Chat ID!")
                    return
                info = validate_channel(cid)
                if not info:
                    send_clean_prompt(chat_id, "❌ Channel not found!")
                    return
                if not check_bot_admin(info["id"]):
                    send_clean_prompt(chat_id, f"❌ Bot is NOT admin in `{info['title']}`! Please promote bot.")
                    return

                bot_settings["conn_sources"] = st["conn_sources"]
                bot_settings["conn_dest"] = str(info["id"])
                sync_db()
                user_states[chat_id] = None

                send_clean_prompt(
                    chat_id,
                    f"✅ **CONNECTION SUCCESSFUL!** 🎉\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📥 **Destination:** `{info['title']}`\n"
                    f"📤 **Sources:** `{len(st['conn_sources'])}` channels\n\n"
                    "Whenever you post anything in the source channels, it will automatically be copied to your destination channel.",
                    parse_mode="Markdown",
                    reply_markup=get_conn_main_keyboard()
                )
                return

            if isinstance(st, dict) and st.get("stage") == "waiting_for_del_channel_id":
                cid = extract_chat_id(text.strip())
                if not cid:
                    send_clean_prompt(chat_id, "❌ Invalid Chat ID! Please send correctly.")
                    return
                try:
                    info = validate_channel(cid)
                    if not info:
                        send_clean_prompt(chat_id, "❌ Channel not found! Please check the ID.")
                        return
                    if not check_bot_admin(info["id"]):
                        send_clean_prompt(chat_id, "❌ Bot is NOT admin in this channel! Please give admin rights.")
                        return
                    
                    user_states[chat_id] = {
                        "stage": "waiting_for_del_message",
                        "channel_id": str(info["id"]),
                        "channel_title": info["title"]
                    }
                    send_clean_prompt(
                        chat_id,
                        f"✅ **Verified Admin!**\n"
                        f"📢 **{html.escape(info['title'])}**\n\n"
                        "**Step 2:** Now forward the message (Text, Video, Voice, Link, File) you want to delete from this channel.",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Del channel verify error: {e}")
                    send_clean_prompt(chat_id, f"❌ Error verifying channel: {e}")
                return

            if isinstance(st, dict) and st.get("stage") == "waiting_for_del_time_number" and st.get("time_unit"):
                try:
                    num = int(text.strip())
                    if num <= 0:
                        send_clean_prompt(chat_id, "❌ Number must be > 0")
                        return
                except:
                    send_clean_prompt(chat_id, "❌ Send a valid number")
                    return

                unit = st["time_unit"]
                if unit == "min":
                    seconds = num * 60
                    unit_str = f"{num} minute(s)"
                elif unit == "hour":
                    seconds = num * 3600
                    unit_str = f"{num} hour(s)"
                else:
                    seconds = num * 86400
                    unit_str = f"{num} day(s)"

                if st.get("message_date") and (time.time() - st["message_date"] > 48 * 3600):
                    send_clean_prompt(chat_id, "❌ **Telegram API Limit:** Bots cannot delete messages older than 48 hours. Deletion aborted.")
                    user_states[chat_id] = None
                    return

                if not check_bot_delete_permission(st["channel_id"]):
                    send_clean_prompt(chat_id, "❌ Bot does NOT have 'Delete Messages' permission in this channel!")
                    user_states[chat_id] = None
                    return

                item_id = "del_" + uuid.uuid4().hex[:8]
                delete_at = (datetime.now() + timedelta(seconds=seconds)).isoformat()
                
                item = {
                    "id": item_id,
                    "channel_id": st["channel_id"],
                    "channel_title": st["channel_title"],
                    "message_id": st["message_id"],
                    "delete_at": delete_at,
                    "deleted": False,
                    "created_at": datetime.now().isoformat()
                }
                scheduled_deletions.append(item)
                sync_db()
                user_states[chat_id] = None

                send_clean_prompt(chat_id, f"✅ **Message deletion scheduled for {unit_str} from now!**")
                
                pending = [x for x in scheduled_deletions if not x.get("deleted")]
                msg, markup = generate_deletion_text(pending)
                sent_msg = bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=markup)
                live_deletion_messages[chat_id] = sent_msg.message_id
                return

            if isinstance(st, dict) and st.get("stage") == "aps_waiting_channel_count":
                try:
                    count = int(text.strip())
                    if count <= 0 or count > 50:
                        send_clean_prompt(chat_id, "❌ Please enter a number between 1 and 50.")
                        return
                    st["channel_count"] = count
                    st["channel_ids"] = []
                    st["stage"] = "aps_waiting_channel_id"
                    user_states[chat_id] = st
                    send_clean_prompt(chat_id, f"✅ **{count} channels selected.**\n\n📢 **Step 2/6: Send Channel ID 1/{count}:**")
                except ValueError:
                    send_clean_prompt(chat_id, "❌ Please enter numbers only (e.g., 2).")
                return

            if isinstance(st, dict) and st.get("stage") == "aps_waiting_channel_id":
                ch_id_input = text.strip()
                info = validate_channel(ch_id_input)
                if not info:
                    send_clean_prompt(chat_id, f"❌ **Channel not found!**\n\n`{ch_id_input}`\nPlease enter the correct ID again:")
                    return
                is_admin = check_bot_admin(info["id"])
                if not is_admin:
                    send_clean_prompt(chat_id, f"❌ **Bot is NOT admin in this channel!**\n📢 {html.escape(info['title'])}\nPlease enter the correct ID again:")
                    return

                st["channel_ids"].append({
                    "id": str(info["id"]),
                    "title": info["title"]
                })
                current_count = len(st["channel_ids"])
                target_count = st["channel_count"]

                if current_count < target_count:
                    st["stage"] = "aps_waiting_channel_id"
                    user_states[chat_id] = st
                    send_clean_prompt(chat_id, f"✅ **Channel added successfully!** ({current_count}/{target_count})\n\n📢 **Send Channel ID {current_count + 1}/{target_count}:**")
                else:
                    st["stage"] = "aps_waiting_file_count"
                    user_states[chat_id] = st
                    send_clean_prompt(
                        chat_id,
                        f"✅ **All {target_count} channels verified!**\n\n"
                        "**Step 3/6: How many files do you want to upload?**\n\n"
                        "📁 Enter the number of files (e.g., `1`, `2`, `10`)",
                        parse_mode="Markdown"
                    )
                return

            if isinstance(st, dict) and st.get("stage") == "aps_waiting_file_count":
                try:
                    count = int(text.strip())
                    if count <= 0 or count > 50:
                        send_clean_prompt(chat_id, "❌ Please enter a number between 1 and 50.")
                        return
                    st["file_count"] = count
                    st["files"] = []
                    st["current_file_index"] = 0
                    st["stage"] = "aps_waiting_files"
                    user_states[chat_id] = st
                    
                    type_names = {"file": "📄 File", "photo": "🖼️ Photo", "video": "🎬 Video"}
                    send_clean_prompt(
                        chat_id,
                        f"✅ **{count} files selected.**\n\n"
                        f"**Step 4/6: Send {type_names.get(st.get('post_type'))} 1/{count}**\n\n"
                        "📤 Send the first file now.",
                        parse_mode="Markdown"
                    )
                except ValueError:
                    send_clean_prompt(chat_id, "❌ Please enter numbers only (e.g., 2).")
                return

            if isinstance(st, dict) and st.get("stage") == "aps_waiting_caption_text":
                caption = message.html_text if message.html_text else text.strip()
                if not caption:
                    send_clean_prompt(chat_id, "❌ Empty!")
                    return
                st["files"][st["caption_index"]]["caption"] = caption
                st["stage"] = "aps_caption_menu"
                user_states[chat_id] = st
                
                send_clean_prompt(
                    chat_id,
                    f"✅ **File Text added for File {st['caption_index'] + 1}!**\n\n"
                    "Do you want to add Voice message or Voice Text?",
                    reply_markup=get_aps_after_text_keyboard()
                )
                return

            if isinstance(st, dict) and st.get("stage") == "aps_waiting_voice_caption_text":
                caption = message.html_text if message.html_text else text.strip()
                if not caption:
                    send_clean_prompt(chat_id, "❌ Empty!")
                    return
                
                if "voice_data" not in st["files"][st["caption_index"]] or not st["files"][st["caption_index"]]["voice_data"]:
                    st["files"][st["caption_index"]]["voice_data"] = {}
                
                st["files"][st["caption_index"]]["voice_data"]["caption"] = caption
                st["stage"] = "aps_caption_menu"
                user_states[chat_id] = st
                
                send_clean_prompt(
                    chat_id,
                    f"✅ **Voice Text added for File {st['caption_index'] + 1}!**\n\n"
                    "Do you want to add File Text or proceed?",
                    reply_markup=get_aps_after_voice_keyboard()
                )
                return

            if isinstance(st, dict) and st.get("stage") == "aps_waiting_time" and st.get("time_unit"):
                try:
                    num = int(text.strip())
                    if num <= 0:
                        send_clean_prompt(chat_id, "❌ Number must be > 0")
                        return
                except:
                    send_clean_prompt(chat_id, "❌ Send a valid number")
                    return

                unit = st["time_unit"]
                if unit == "min":
                    seconds = num * 60
                    unit_str = f"{num} minute(s)"
                elif unit == "hour":
                    seconds = num * 3600
                    unit_str = f"{num} hour(s)"
                else:
                    seconds = num * 86400
                    unit_str = f"{num} day(s)"

                channel_ids = st.get("channel_ids", [])
                files = st.get("files", [])
                post_type = st.get("post_type", "file")

                item_id = "post_" + uuid.uuid4().hex[:8]
                scheduled_time = (datetime.now() + timedelta(seconds=seconds)).isoformat()
                item = {
                    "id": item_id,
                    "post_type": post_type,
                    "files": files,
                    "channel_ids": channel_ids, 
                    "scheduled_time": scheduled_time,
                    "sent": False,
                    "created_at": datetime.now().isoformat()
                }
                scheduled_posts.append(item)
                sync_db()
                user_states[chat_id] = None

                type_emoji = {"file": "📄", "photo": "🖼️", "video": "🎬"}.get(post_type, "📄")
                ch_list_text = "\n".join([f"  • {html.escape(ch['title'])} (`{ch['id']}`)" for ch in channel_ids])
                
                mk = InlineKeyboardMarkup(row_width=1)
                mk.add(InlineKeyboardButton("📅 View Live Preview", callback_data="aps_view_scheduled"))
                mk.add(InlineKeyboardButton("🔙 Main Menu", callback_data="aps_main"))

                send_clean_prompt(
                    chat_id,
                    f"✅ **Post Scheduled Successfully!**\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{type_emoji} Type: **{post_type.title()}**\n"
                    f"📁 Files: `{len(files)}`\n"
                    f"📢 Channels ({len(channel_ids)}):\n{ch_list_text}\n"
                    f"⏰ In: **{unit_str}**\n"
                    f"📅 At: `{datetime.fromisoformat(scheduled_time).strftime('%Y-%m-%d %H:%M')}`\n\n"
                    "Tap below to see the live countdown!",
                    parse_mode="Markdown",
                    reply_markup=mk
                )
                return

            if isinstance(st, dict) and st.get("stage") == "waiting_for_jtext_title":
                new_title = text.strip()
                if not new_title:
                    send_clean_prompt(chat_id, "❌ Empty!")
                    return
                bot_settings["force_join_title"] = new_title
                sync_db()
                user_states[chat_id] = None
                send_clean_prompt(chat_id, f"✅ **Title Updated!**\n\n`{html.escape(new_title)}`", parse_mode="Markdown",
                                 reply_markup=get_join_text_editor_keyboard())
                return

            if isinstance(st, dict) and st.get("stage") == "waiting_for_jtext_msg":
                new_msg = text.strip()
                if not new_msg:
                    send_clean_prompt(chat_id, "❌ Empty!")
                    return
                bot_settings["force_join_message"] = new_msg
                sync_db()
                user_states[chat_id] = None
                send_clean_prompt(chat_id, f"✅ **Message Updated!**\n\n`{html.escape(new_msg)}`", parse_mode="Markdown",
                                 reply_markup=get_join_text_editor_keyboard())
                return

            if isinstance(st, dict) and "stage" in st and st["stage"].startswith("waiting_for_btn_name||"):
                ch_id = st["stage"].split("waiting_for_btn_name||")[-1]
                new_name = text.strip()
                if not new_name:
                    send_clean_prompt(chat_id, "❌ Empty!")
                    return
                
                found = False
                for ch in bot_settings.get("channels", []):
                    if ch.get("id") == ch_id:
                        ch["name"] = new_name
                        found = True
                        break
                
                if found:
                    sync_db()
                    user_states[chat_id] = None
                    send_clean_prompt(chat_id, f"✅ **Button Name Updated!**\n\nNew Name: `{new_name}`", parse_mode="Markdown", reply_markup=get_join_text_editor_keyboard())
                else:
                    send_clean_prompt(chat_id, "❌ Channel not found.")
                    user_states[chat_id] = None
                return

            if isinstance(st, str) and st.startswith("ch_waiting_link_"):
                slot = st.split("ch_waiting_link_")[-1]
                link_input = text.strip()
                user_states[chat_id] = {"stage": "choose_type", "slot": slot, "link": link_input}
                send_clean_prompt(chat_id, f"📎 **Link received**\n\n🔽 Choose type:",
                                 parse_mode="Markdown", reply_markup=get_channel_type_keyboard(slot))
                return

            if st == "ch_more_waiting_name":
                name = text.strip()
                user_states[chat_id] = {"stage": "more_waiting_link", "name": name}
                send_clean_prompt(chat_id, f"✅ Name: **{html.escape(name)}**\n\n📎 Send the link:", parse_mode="Markdown")
                return

            if isinstance(st, dict) and st.get("stage") == "more_waiting_link":
                name = st.get("name", "Channel")
                link_input = text.strip()
                user_states[chat_id] = {"stage": "more_choose_type", "name": name, "link": link_input}
                send_clean_prompt(chat_id, "📎 **Link received**\n\n🔽 Choose type:",
                                 parse_mode="Markdown", reply_markup=get_channel_type_keyboard_for_more(name))
                return

            if isinstance(st, dict) and st.get("stage") == "waiting_chat_id":
                slot = st.get("slot", "1")
                link_input = st.get("link", "")
                chat_id_input = text.strip()
                cid = extract_chat_id(chat_id_input)
                if not cid:
                    send_clean_prompt(chat_id, "❌ Invalid Chat ID!")
                    return
                try:
                    info = validate_channel(cid)
                    if not info:
                        send_clean_prompt(chat_id, f"❌ Channel not found: `{cid}`", parse_mode="Markdown")
                        user_states[chat_id] = None
                        return
                    is_admin = check_bot_admin(info["id"])
                    if not is_admin:
                        send_clean_prompt(chat_id, f"❌ **Bot NOT admin!**\n📢 {html.escape(info['title'])}", parse_mode="Markdown")
                        user_states[chat_id] = None
                        return
                    name = f"Channel {slot}" if slot in ["1", "2"] else slot
                    join_url = extract_join_url(link_input)
                    if not join_url:
                        if info.get("username"):
                            join_url = f"https://t.me/{info['username']}"
                        else:
                            join_url = link_input
                    add_channel(name, "private", join_url, str(info["id"]))
                    send_clean_prompt(
                        chat_id,
                        f"✅ **VERIFIED!**\n"
                        "━━━━━━━━━━━━━━━━━━━━━\n"
                        f"📢 **{html.escape(info['title'])}**\n"
                        f"🆔 `{info['id']}`\n"
                        f"📂 🔒 Private\n"
                        f"🤖 ✅ Admin",
                        parse_mode="Markdown", reply_markup=get_admin_panel_keyboard()
                    )
                    user_states[chat_id] = None
                except Exception as e:
                    send_clean_prompt(chat_id, f"❌ Error: `{str(e)[:150]}`", parse_mode="Markdown")
                    user_states[chat_id] = None
                return

            if isinstance(st, dict) and st.get("stage") == "waiting_for_admin_password":
                if login_admin(user_id, text.strip(), remember=True):
                    user_states[chat_id] = None
                    send_clean_prompt(chat_id, "✅ Login Successful!", reply_markup=get_admin_panel_keyboard())
                else:
                    send_clean_prompt(chat_id, "❌ Wrong password!")
                return

            if isinstance(st, dict) and st.get("stage") == "waiting_for_admin_password_save":
                if login_admin(user_id, text.strip(), remember=True):
                    user_states[chat_id] = None
                    send_clean_prompt(chat_id, "✅ Admin session saved in database. You will stay logged in until Logout.", reply_markup=get_admin_panel_keyboard())
                else:
                    send_clean_prompt(chat_id, "❌ Wrong password!")
                return

            if isinstance(st, dict) and st.get("stage") == "waiting_for_giveaway_prize":
                giveaway["prize"] = text.strip()
                giveaway["active"] = True
                giveaway["participants"] = []
                giveaway["end_time"] = (datetime.now() + timedelta(hours=24)).isoformat()
                sync_db()
                user_states[chat_id] = None
                send_clean_prompt(chat_id, f"🎁 Started!")
                return

            if isinstance(st, dict) and st.get("stage") == "waiting_for_add_admin":
                try:
                    aid = int(text.strip())
                    if "sub_admins" not in bot_settings:
                        bot_settings["sub_admins"] = []
                    if aid not in bot_settings["sub_admins"] and aid != ADMIN_ID:
                        bot_settings["sub_admins"].append(aid)
                        sync_db()
                        send_clean_prompt(chat_id, "✅ Added!")
                    user_states[chat_id] = None
                except:
                    send_clean_prompt(chat_id, "❌ Invalid!")
                return

            if isinstance(st, dict) and st.get("stage") == "waiting_for_remove_admin":
                try:
                    aid = int(text.strip())
                    if "sub_admins" in bot_settings and aid in bot_settings["sub_admins"]:
                        bot_settings["sub_admins"].remove(aid)
                        sync_db()
                        send_clean_prompt(chat_id, "✅ Removed!")
                    user_states[chat_id] = None
                except:
                    send_clean_prompt(chat_id, "❌ Invalid!")
                return

            if isinstance(st, dict) and st.get("stage") == "waiting_for_auto_reply_keyword":
                user_states[chat_id] = {"stage": f"waiting_for_auto_reply_response||{text.strip()}"}
                send_clean_prompt(chat_id, f"✏️ Reply:")
                return

            if isinstance(st, dict) and st.get("stage", "").startswith("waiting_for_auto_reply_response||"):
                k = st["stage"].split("waiting_for_auto_reply_response||")[-1]
                if "auto_reply" not in bot_settings:
                    bot_settings["auto_reply"] = {}
                bot_settings["auto_reply"][k] = text.strip()
                sync_db()
                user_states[chat_id] = None
                send_clean_prompt(chat_id, "✅ Added!")
                return

            if isinstance(st, dict) and st.get("stage") == "waiting_for_ban_user":
                try:
                    banned_users.add(int(text.strip()))
                    sync_db()
                    send_clean_prompt(chat_id, "✅ Banned!")
                except:
                    send_clean_prompt(chat_id, "❌ Invalid!")
                user_states[chat_id] = None
                return

            if isinstance(st, dict) and st.get("stage") == "waiting_for_unban_user":
                try:
                    t = int(text.strip())
                    if t in banned_users:
                        banned_users.remove(t)
                        sync_db()
                        send_clean_prompt(chat_id, "✅ Unbanned!")
                except:
                    pass
                user_states[chat_id] = None
                return

            if isinstance(st, dict) and st.get("stage") == "waiting_for_panel_name":
                user_states[chat_id] = {"stage": f"waiting_for_secret_value||{text.strip()}"}
                send_clean_prompt(chat_id, "🔑 Secret Key value:")
                return

            if isinstance(st, dict) and st.get("stage", "").startswith("waiting_for_secret_value||"):
                panel = st["stage"].split("waiting_for_secret_value||")[-1]
                val = text.strip()
                user_states[chat_id] = None
                key = "key_" + str(uuid.uuid4().hex[:8])
                file_database[key] = {
                    "is_text_key": True, "panel_name": panel,
                    "secret_value": val, "uploaded_at": datetime.now().isoformat()
                }
                sync_db()
                bi = bot.get_me()
                link = f"https://t.me/{bi.username}?start={key}"
                mk = InlineKeyboardMarkup()
                mk.add(InlineKeyboardButton("📋 Copy Link", callback_data=f"copy_key|{key}"))
                send_clean_prompt(chat_id, f"✅ Key Created!\n🆔 `{key}`\n🔗 `{link}`", parse_mode="Markdown", reply_markup=mk)
                return

            if isinstance(st, dict) and st.get("stage") == "waiting_for_delete_key":
                k = text.strip()
                if k in file_database:
                    del file_database[k]
                    sync_db()
                    send_clean_prompt(chat_id, "✅ Deleted!")
                else:
                    send_clean_prompt(chat_id, "❌ Not found!")
                user_states[chat_id] = None
                return

            if isinstance(st, dict) and st.get("stage") == "waiting_for_broadcast":
                user_states[chat_id] = None
                sc = 0
                sm = send_clean_prompt(chat_id, "📢 Sending...")
                for u in list(registered_users):
                    if u == ADMIN_ID:
                        continue
                    try:
                        bot.send_message(u, f"📢 **Broadcast:**\n\n{text}", parse_mode="Markdown")
                        sc += 1
                        time.sleep(0.05)
                    except:
                        pass
                bot.edit_message_text(f"✅ Sent to `{sc}`", chat_id, sm.message_id, parse_mode="Markdown")
                return

        if user_id != ADMIN_ID:
            unjoined = get_unjoined_channels(user_id)
            if unjoined:
                msg = get_join_message(unjoined)
                bot.send_message(chat_id, msg, reply_markup=get_join_keyboard(None, unjoined))
                return

        if text and text.startswith("/"):
            c = text[1:].strip().lower()
            cmds = bot_settings.get("custom_commands", {})
            if c in cmds:
                bot.send_message(chat_id, cmds[c])
                return

        if text == "🎙️ Voice" or text == "/voice":
            if not GTTS_AVAILABLE:
                bot.send_message(chat_id, "❌ Not available!")
                return
            user_states[chat_id] = {"stage": "waiting_for_voice_text"}
            bot.send_message(chat_id, "🎤 Send text:", reply_markup=telebot.types.ReplyKeyboardRemove())
        elif text == "📊 Stats" or text == "/stats":
            if user_id in user_activity:
                s = user_activity[user_id]
                bot.send_message(chat_id, f"📊 **Stats:**\n🔄 {s['total_actions']}\n⭐ {s.get('points', 0)}\n🏅 {s.get('rank', 'Member')}")
        elif text == "🎁 Daily Reward" or text == "/daily":
            today = datetime.now().date().isoformat()
            if user_activity.get(user_id, {}).get("last_daily") == today:
                bot.send_message(chat_id, "❌ Already claimed!")
                return
            if user_id not in user_activity:
                user_activity[user_id] = {"points": 0}
            user_activity[user_id]["points"] = user_activity[user_id].get("points", 0) + bot_settings.get("daily_reward", 10)
            user_activity[user_id]["last_daily"] = today
            sync_db()
            bot.send_message(chat_id, f"🎁 +{bot_settings.get('daily_reward', 10)} points!")
        elif text == "🏆 Leaderboard" or text == "/leaderboard":
            if not user_activity:
                bot.send_message(chat_id, "❌ No users!")
                return
            su = sorted(user_activity.items(), key=lambda x: x[1].get("points", 0), reverse=True)[:10]
            m = "🏆 **Top 10:**\n"
            for i, (uid, d) in enumerate(su, 1):
                try:
                    u = bot.get_chat(int(uid))
                    n = u.first_name or "Unknown"
                except:
                    n = "Unknown"
                m += f"{i}. {n} - `{d.get('points', 0)}`\n"
            bot.send_message(chat_id, m, parse_mode="Markdown")
        elif text == "ℹ️ Help" or text == "/help":
            bot.send_message(chat_id, f"✨ **{BOT_NAME} Bot**\n\n🎙️ Voice\n📊 Stats\n🎁 Daily\n🏆 Leaderboard\n👤 Profile", reply_markup=get_main_keyboard())
        elif text == "👤 Profile" or text == "/profile":
            u = message.from_user
            p = user_activity.get(user_id, {}).get("points", 0)
            r = user_activity.get(user_id, {}).get("rank", "Member")
            bot.send_message(chat_id, f"👤 **Profile:**\n📛 {html.escape(u.first_name)}\n🆔 `{u.id}`\n⭐ `{p}`\n🏅 `{r}`", parse_mode="Markdown")
        elif isinstance(user_states.get(chat_id), dict) and user_states.get(chat_id).get("stage") == "waiting_for_voice_text":
            if not GTTS_AVAILABLE:
                bot.send_message(chat_id, "❌ Not available!")
                user_states[chat_id] = None
                return
            user_states[chat_id] = None
            sm = bot.send_message(chat_id, "🎵 Generating...")
            fp = f"voice_{chat_id}_{int(time.time())}.mp3"
            try:
                tts = gTTS(text=text, lang='bn', slow=False)
                tts.save(fp)
                with open(fp, 'rb') as a:
                    bot.send_audio(chat_id, a, caption="🎵 Voice!", reply_markup=get_main_keyboard())
                bot.delete_message(chat_id, sm.message_id)
            except:
                bot.send_message(chat_id, "❌ Failed!", reply_markup=get_main_keyboard())
            finally:
                if os.path.exists(fp):
                    os.remove(fp)
        else:
            bot.send_message(chat_id, "❌ Unknown. Use /help", reply_markup=get_main_keyboard())
    except Exception as e:
        logger.error(f"Message Handler Error: {e}")

# =====================================================
#           🔄 BACKGROUND THREADS
# =====================================================

def check_scheduled_messages():
    while True:
        try:
            now = datetime.now()
            for m in scheduled_messages:
                if not m.get("sent"):
                    mt = datetime.fromisoformat(m["time"])
                    if now >= mt:
                        for u in list(registered_users):
                            try:
                                bot.send_message(u, f"📅 {m['message']}")
                            except:
                                pass
                        m["sent"] = True
                        sync_db()
            time.sleep(60)
        except:
            time.sleep(60)

def check_scheduled_posts():
    while True:
        try:
            now = datetime.now()
            items_copy = list(scheduled_posts)
            for item in items_copy:
                if item.get("sent"):
                    continue
                try:
                    sched_time = datetime.fromisoformat(item["scheduled_time"])
                    if now >= sched_time:
                        files = item.get("files", [])
                        channel_ids = item.get("channel_ids", [])

                        if not channel_ids or not files:
                            item["sent"] = True
                            continue

                        total_sent = 0
                        total_failed = 0

                        for ch in channel_ids:
                            ch_id = ch["id"] if isinstance(ch, dict) else ch
                            for file_item in files:
                                fid = file_item["file_id"]
                                ftype = file_item["file_type"]
                                caption = file_item.get("caption", "")
                                voice_data = file_item.get("voice_data")
                                voice_buttons = file_item.get("voice_buttons", []) # 🔥 Voice Buttons 🔥
                                custom_buttons = file_item.get("buttons", []) # 🔥 File Buttons 🔥
                                from_chat = file_item.get("from_chat_id", ch_id)
                                reply_data = file_item.get("reply_data") or {}
                                reply_to_id = None
                                try:
                                    if str(reply_data.get("target_chat_id")) == str(ch_id):
                                        reply_to_id = int(reply_data.get("target_message_id"))
                                    elif reply_data.get("target_chat_id"):
                                        logger.warning(
                                            "Reply target channel %s differs from destination %s; sending file without reply.",
                                            reply_data.get("target_chat_id"), ch_id
                                        )
                                except (TypeError, ValueError):
                                    reply_to_id = None
                                reply_kwargs = {"reply_to_message_id": reply_to_id} if reply_to_id else {}

                                # 🔥 Build Inline Keyboard for Custom Buttons 🔥
                                reply_markup = None
                                if custom_buttons:
                                    # Arrange URL buttons in two columns: 2 per row.
                                    # An odd final button naturally occupies the left column.
                                    reply_markup = InlineKeyboardMarkup(row_width=2)
                                    custom_inline_buttons = [
                                        InlineKeyboardButton(text=btn["name"], url=btn["url"])
                                        for btn in custom_buttons
                                        if btn.get("name") and btn.get("url")
                                    ]
                                    for button_index in range(0, len(custom_inline_buttons), 2):
                                        reply_markup.row(*custom_inline_buttons[button_index:button_index + 2])
                                # 🔥 END 🔥

                                # 🔥 Build Inline Keyboard for Voice Buttons 🔥
                                voice_reply_markup = None
                                if voice_buttons:
                                    voice_reply_markup = InlineKeyboardMarkup(row_width=1)
                                    for btn in voice_buttons:
                                        voice_reply_markup.add(InlineKeyboardButton(text=btn["name"], url=btn["url"]))
                                # 🔥 END 🔥

                                sent_file_msg = None
                                try:
                                    if ftype == 'forward':
                                        sent_file_msg = bot.forward_message(
                                            ch_id, from_chat, fid
                                        )
                                    elif ftype == 'document':
                                        sent_file_msg = bot.send_document(ch_id, fid, caption=caption if caption else None, parse_mode="HTML", reply_markup=reply_markup, **reply_kwargs)
                                    elif ftype == 'photo':
                                        sent_file_msg = bot.send_photo(ch_id, fid, caption=caption if caption else None, parse_mode="HTML", reply_markup=reply_markup, **reply_kwargs)
                                    elif ftype == 'video':
                                        sent_file_msg = bot.send_video(ch_id, fid, caption=caption if caption else None, parse_mode="HTML", reply_markup=reply_markup, **reply_kwargs)
                                    elif ftype == 'audio':
                                        sent_file_msg = bot.send_audio(ch_id, fid, caption=caption if caption else None, parse_mode="HTML", reply_markup=reply_markup, **reply_kwargs)
                                    elif ftype == 'animation':
                                        sent_file_msg = bot.send_animation(ch_id, fid, caption=caption if caption else None, parse_mode="HTML", reply_markup=reply_markup, **reply_kwargs)
                                    elif ftype == 'sticker':
                                        sent_file_msg = bot.send_sticker(ch_id, fid, **reply_kwargs)
                                        if caption or reply_markup:
                                            bot.send_message(ch_id, caption if caption else "🎭 Sticker", parse_mode="HTML", reply_markup=reply_markup)
                                    elif ftype == 'text':
                                        if caption:
                                            try:
                                                sent_file_msg = bot.send_message(ch_id, caption, parse_mode="HTML", disable_web_page_preview=False, reply_markup=reply_markup, **reply_kwargs)
                                            except Exception:
                                                sent_file_msg = bot.send_message(ch_id, caption, disable_web_page_preview=False, reply_markup=reply_markup, **reply_kwargs)
                                        else:
                                            sent_file_msg = bot.copy_message(ch_id, from_chat, fid, reply_markup=reply_markup, **reply_kwargs)

                                    if voice_data and voice_data.get("file_id"):
                                        time.sleep(1)
                                        v_cap = voice_data.get("caption", "")
                                        
                                        if sent_file_msg:
                                            # 🔥 Send Voice as Reply to the File 🔥
                                            bot.send_voice(
                                                ch_id, 
                                                voice_data["file_id"], 
                                                caption=v_cap if v_cap else None, 
                                                parse_mode="HTML", 
                                                reply_markup=voice_reply_markup,
                                                reply_to_message_id=sent_file_msg.message_id # Auto Reply Feature
                                            )
                                        else:
                                            # Fallback if no file msg (shouldn't happen)
                                            bot.send_voice(ch_id, voice_data["file_id"], caption=v_cap if v_cap else None, parse_mode="HTML", reply_markup=voice_reply_markup)
                                    
                                    # React to scheduler-published posts using the saved reaction bots
                                    # configured for this destination channel. This is explicit because
                                    # Telegram does not reliably send our own channel posts back as updates.
                                    if sent_file_msg:
                                        try:
                                            target_channel_id = str(sent_file_msg.chat.id)
                                            for reaction_bot_data in bot_settings.get("reaction_bots", []):
                                                if str(reaction_bot_data.get("channel_id")) == target_channel_id:
                                                    reaction_delay = random.uniform(2.0, 4.0)
                                                    threading.Thread(
                                                        target=process_single_reaction,
                                                        args=(reaction_bot_data, sent_file_msg, reaction_delay),
                                                        daemon=True
                                                    ).start()
                                        except Exception as reaction_exc:
                                            logger.error(f"Scheduled-post reaction trigger failed: {reaction_exc}")

                                    total_sent += 1
                                    time.sleep(0.5) 
                                except Exception as e:
                                    total_failed += 1
                                    logger.error(f"Post failed to {ch_id} for file {fid}: {e}")

                        item["sent"] = True
                        item["sent_at"] = datetime.now().isoformat()
                        
                        if ADMIN_ID in live_schedule_messages:
                            pending_after = [x for x in scheduled_posts if not x.get("sent")]
                            msg_id = live_schedule_messages[ADMIN_ID]
                            if not pending_after:
                                try:
                                    bot.edit_message_text("❌ No pending scheduled posts.", ADMIN_ID, msg_id)
                                except: pass
                                del live_schedule_messages[ADMIN_ID]
                            else:
                                msg_new, markup_new = generate_scheduled_text(pending_after)
                                try:
                                    bot.edit_message_text(msg_new, ADMIN_ID, msg_id, parse_mode="Markdown", reply_markup=markup_new)
                                except: pass

                        try:
                            bot.send_message(
                                ADMIN_ID,
                                f"✅ **Auto Post Process Finished!**\n\n"
                                f"📁 Total Files: `{len(files)}`\n"
                                f"📢 Sent to: `{len(channel_ids)}` channels\n"
                                f"✅ Success: `{total_sent}` | ❌ Failed: `{total_failed}`\n"
                                f"⏰ Time: {now.strftime('%Y-%m-%d %H:%M')}",
                                parse_mode="Markdown"
                            )
                        except:
                            pass
                        sync_db()
                except Exception as e:
                    logger.error(f"Post check error: {e}")
            time.sleep(30)
        except:
            time.sleep(30)

def check_scheduled_deletions():
    while True:
        try:
            now = datetime.now()
            items_copy = list(scheduled_deletions)
            changed = False
            for item in items_copy:
                if item.get("deleted"):
                    continue
                try:
                    del_time = datetime.fromisoformat(item["delete_at"])
                    if now >= del_time:
                        ch_id = item["channel_id"]
                        msg_id = item["message_id"]
                        
                        try:
                            bot.delete_message(ch_id, msg_id)
                            item["deleted"] = True
                            item["status"] = "success"
                            logger.info(f"Deleted message {msg_id} from {ch_id}")
                        except Exception as e:
                            logger.error(f"Failed to delete msg {msg_id} from {ch_id}: {e}")
                            item["deleted"] = True
                            item["status"] = "failed"
                            item["error"] = str(e)
                        
                        changed = True
                        
                        try:
                            bot.send_message(
                                ADMIN_ID,
                                f"🗑️ **Message Deletion {'Success' if item['status'] == 'success' else 'Failed'}!**\n\n"
                                f"📢 Channel: `{item.get('channel_title')}`\n"
                                f"🆔 Msg ID: `{msg_id}`\n"
                                f"⏰ Time: {now.strftime('%Y-%m-%d %H:%M')}\n\n"
                                f"⚠️ **Note:** If failed, it's likely because the message is older than 48 hours (Telegram Limit) or bot lacks permission.",
                                parse_mode="Markdown"
                            )
                        except:
                            pass

                except Exception as e:
                    logger.error(f"Deletion check error: {e}")
            
            if changed:
                sync_db()
                if ADMIN_ID in live_deletion_messages:
                    pending_after = [x for x in scheduled_deletions if not x.get("deleted")]
                    msg_id = live_deletion_messages[ADMIN_ID]
                    if not pending_after:
                        try:
                            bot.edit_message_text("❌ No pending scheduled deletions.", ADMIN_ID, msg_id)
                        except: pass
                        del live_deletion_messages[ADMIN_ID]
                    else:
                        msg_new, markup_new = generate_deletion_text(pending_after)
                        try:
                            bot.edit_message_text(msg_new, ADMIN_ID, msg_id, parse_mode="Markdown", reply_markup=markup_new)
                        except: pass

            time.sleep(10) 
        except:
            time.sleep(10)

def check_giveaway_loop():
    while True:
        try:
            if giveaway.get("active") and giveaway.get("end_time"):
                et = datetime.fromisoformat(giveaway["end_time"])
                if datetime.now() >= et:
                    p = giveaway.get("participants", [])
                    if p:
                        w = random.choice(p)
                        pr = giveaway.get("prize", "Prize")
                        if "winners" not in giveaway:
                            giveaway["winners"] = []
                        giveaway["winners"].append({"user_id": w, "prize": pr})
                        bot.send_message(ADMIN_ID, f"🎉 Winner: `{w}`")
                    giveaway["active"] = False
                    giveaway["participants"] = []
                    giveaway["end_time"] = None
                    sync_db()
            time.sleep(60)
        except:
            time.sleep(60)

# =====================================================
#           🚀 MAIN
# =====================================================

if __name__ == "__main__":
    try:
        from flask import Flask
        af = Flask(__name__)

        @af.route('/')
        def home():
            return "Bot service is running. Check Telegram for bot responses."

        @af.route('/health')
        def health():
            return "OK"

        _polling_started = threading.Event()
        _background_started = threading.Event()

        def run_bot():
            if _polling_started.is_set():
                logger.warning("Polling runner already started in this process; skipping duplicate start.")
                return
            _polling_started.set()
            print_banner()
            
            def _restore():
                time.sleep(5)
                try:
                    if USERBOT_AVAILABLE:
                        run_async(ub_module.restore_sessions())
                        logger.info("✅ Userbot sessions restored")
                except Exception as e:
                    logger.error(f"Restore err: {e}")
            threading.Thread(target=_restore, daemon=True).start()

            if not _background_started.is_set():
                _background_started.set()
                threading.Thread(target=auto_backup, daemon=True).start()
                threading.Thread(target=check_scheduled_messages, daemon=True).start()
                threading.Thread(target=check_scheduled_posts, daemon=True).start()
                threading.Thread(target=check_scheduled_deletions, daemon=True).start()
                threading.Thread(target=check_giveaway_loop, daemon=True).start()
                threading.Thread(target=live_updater, daemon=True).start()
            logger.info(f"✅ {BOT_NAME} Bot Running...")
            while True:
                try:
                    bot.infinity_polling(timeout=30, long_polling_timeout=20)
                except Exception as e:
                    error_text = str(e)
                    if "409" in error_text or "Conflict" in error_text or "terminated by other getUpdates" in error_text:
                        logger.error("Telegram polling conflict (409). Another process is using this bot token. Stop the other instance before this service can receive updates.")
                        time.sleep(30)
                    else:
                        logger.exception("Telegram polling stopped; retrying in 5 seconds: %s", e)
                        time.sleep(5)
                    try:
                        sync_db()
                    except Exception:
                        logger.exception("Database sync failed during recovery")

        threading.Thread(target=run_bot, daemon=True).start()
        port = int(os.environ.get("PORT", 5000))
        af.run(host="0.0.0.0", port=port, use_reloader=False, threaded=True)

    except ImportError:
        print_banner()
        
        def _restore2():
            time.sleep(5)
            try:
                if USERBOT_AVAILABLE:
                    run_async(ub_module.restore_sessions())
            except Exception:
                pass
        threading.Thread(target=_restore2, daemon=True).start()

        threading.Thread(target=auto_backup, daemon=True).start()
        threading.Thread(target=check_scheduled_messages, daemon=True).start()
        threading.Thread(target=check_scheduled_posts, daemon=True).start()
        threading.Thread(target=check_scheduled_deletions, daemon=True).start()
        threading.Thread(target=check_giveaway_loop, daemon=True).start()
        threading.Thread(target=live_updater, daemon=True).start()
        logger.info(f"✅ {BOT_NAME} Bot Running...")
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=20)
        except Exception as e:
            logger.error(f"Crash: {e}")
            sync_db()
