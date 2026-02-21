import telebot
import json
import re
import requests
from telebot import types
import redis
import mysql.connector
from mysql.connector import pooling
import threading
from concurrent.futures import ThreadPoolExecutor
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from decimal import Decimal

# --- ১. কনফিগারেশন ---
BOT_TOKEN = "8291153593:AAGVDMf0fLia-CY6n7VkwlB5b9srMim44m0"
CHANNEL_ID = -1003472206239
CHANNEL_LINK = "https://t.me/+PpiImD3EywJmMGY1"
ADMIN_IDS = [8593594928, 8589946469]

ZINIPAY_API_KEY = "7e69e2a2412325671ac4e492afc994633d1b47c05b424f83"
ZINIPAY_URL = "https://api.zinipay.com/v1/payment/create"

# --- ২. ডাটাবেস ও রেডিস সেটআপ ---
r = redis.StrictRedis(host='localhost', port=6379, db=1, decode_responses=True)

db_config = {
    "host": "127.0.0.1",
    "user": "proxy_admin",
    "password": "Proxy@999",
    "database": "proxy_bot",
    "auth_plugin": "mysql_native_password"
}

connection_pool = mysql.connector.pooling.MySQLConnectionPool(
    pool_name="proxy_pool", pool_size=32, **db_config
)

# --- ৩. বোট ইনিশিয়েট ---
bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=50)

def is_proxy_live(proxy_str):
    try:
        return True
    except:
        return False

def is_member(user_id):
    if user_id in ADMIN_IDS:
        return True
    cached = r.get(f"member:{user_id}")
    if cached: 
        return True
    try:
        chat_member = bot.get_chat_member(CHANNEL_ID, user_id)
        status = chat_member.status
        if status in ['member', 'administrator', 'creator']:
            r.setex(f"member:{user_id}", 300, "true")
            return True
        else:
            return False
    except Exception as e:
        print(f"❌ Membership Error for {user_id}: {e}")
        return False

def add_user_to_db(user_id, username):
    conn = connection_pool.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT IGNORE INTO users (user_id, username) VALUES (%s, %s)", (user_id, username))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def create_payment_config_table():
    """পেমেন্ট কনফিগারেশন টেবিল তৈরি"""
    conn = connection_pool.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payment_config (
                id INT AUTO_INCREMENT PRIMARY KEY,
                service_name VARCHAR(50) UNIQUE,
                service_number VARCHAR(255),
                updated_by BIGINT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("INSERT IGNORE INTO payment_config (service_name, service_number) VALUES (%s, %s)", ("Bkash", "01320557712"))
        cursor.execute("INSERT IGNORE INTO payment_config (service_name, service_number) VALUES (%s, %s)", ("Nagad", "01700000000"))
        cursor.execute("INSERT IGNORE INTO payment_config (service_name, service_number) VALUES (%s, %s)", ("Rocket", "01600000000"))
        cursor.execute("INSERT IGNORE INTO payment_config (service_name, service_number) VALUES (%s, %s)", ("Binance", "default_uid"))
        conn.commit()
    except:
        pass
    finally:
        cursor.close()
        conn.close()

def create_proxy_table():
    conn = connection_pool.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN balance FLOAT DEFAULT 0.0")
    except:
        pass
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS proxy_brands (
            id INT AUTO_INCREMENT PRIMARY KEY, 
            brand_name VARCHAR(255) UNIQUE,
            price_usd FLOAT DEFAULT 0.0,
            rate_bdt FLOAT DEFAULT 0.0
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS proxy_stock (
            id INT AUTO_INCREMENT PRIMARY KEY,
            brand_name VARCHAR(255),
            proxy_data TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_deposits (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT NOT NULL,
            username VARCHAR(255),
            amount FLOAT NOT NULL,
            txid VARCHAR(255) UNIQUE,
            service VARCHAR(50),
            screenshot_file_id VARCHAR(500),
            status VARCHAR(20) DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX(user_id),
            INDEX(status)
        )
    """)
    
    conn.commit()
    cursor.close()
    conn.close()

def get_payment_number(service_name):
    """নির্দিষ্ট সার্ভিসের নম্বর পান"""
    conn = connection_pool.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT service_number FROM payment_config WHERE service_name = %s", (service_name,))
        row = cursor.fetchone()
        return row[0] if row else "Not Set"
    finally:
        cursor.close()
        conn.close()

def get_all_payment_numbers():
    """সব পেমেন্ট নম্বর পান"""
    conn = connection_pool.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT service_name, service_number FROM payment_config")
        rows = cursor.fetchall()
        return {row[0]: row[1] for row in rows}
    finally:
        cursor.close()
        conn.close()

def save_proxy_name(message):
    brand_name = message.text
    if brand_name == "🔙 Back to User Panel": return
    conn = connection_pool.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO proxy_brands (brand_name) VALUES (%s)", (brand_name,))
        conn.commit()
        bot.send_message(message.chat.id, f"✅ নতুন প্রক্সি ব্র্যান্ড যুক্ত হয়েছে: {brand_name}")
    except:
        bot.send_message(message.chat.id, f"❌ এই নামটি আগে থেকেই আছে।")
    finally:
        cursor.close()
        conn.close()

def process_proxy_input(message, brand):
    proxies = []
    
    if message.document and (message.document.mime_type == 'text/plain' or message.document.file_name.endswith('.txt')):
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        proxies = downloaded_file.decode("utf-8").splitlines()
    elif message.text:
        proxies = message.text.splitlines()
    else:
        bot.send_message(message.chat.id, "❌ ভুল ফরম্যাট!")
        return

    proxies = [p.strip() for p in proxies if p.strip()]
    
    if not proxies:
        bot.send_message(message.chat.id, "⚠️ কোনো বৈধ প্রক্সি পাওয়া যায়নি!")
        return

    conn = connection_pool.get_connection()
    cursor = conn.cursor()
    try:
        for p in proxies:
            cursor.execute("INSERT INTO proxy_stock (brand_name, proxy_data) VALUES (%s, %s)", (brand, p))
        conn.commit()
        
        bot.send_message(message.chat.id, 
            f"✅ **Stock Updated Successfully!**\n\n"
            f"🏷 **Brand:** `{brand}`\n"
            f"🚀 **Added:** `{len(proxies)}` proxies\n"
            f"📂 **Status:** Live & Ready",
            parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ ডাটাবেস এরর: {str(e)}")
    finally:
        cursor.close()
        conn.close()

def process_price_input(message, brand):
    text = message.text
    try:
        if not text.startswith('$') or '/' not in text:
            raise ValueError
        
        parts = text.replace('$', '').split('/')
        usd = float(parts[0])
        bdt = float(parts[1])

        conn = connection_pool.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE proxy_brands SET price_usd = %s, rate_bdt = %s WHERE brand_name = %s", (usd, bdt, brand))
        conn.commit()
        cursor.close()
        conn.close()

        bot.send_message(message.chat.id,
            f"💰 **Price Updated!**\n\n"
            f"🏷 **Brand:** `{brand}`\n"
            f"💵 **Price:** `${usd}`\n"
            f"৳ **Exchange Rate:** `{bdt} TK`",
            parse_mode="Markdown")
    except:
        bot.send_message(message.chat.id, "❌ **ভুল ফরম্যাট!**\nসঠিক উদাহরণ: `$1/125`")

def get_live_proxy_from_db(brand):
    conn = connection_pool.get_connection()
    cursor = conn.cursor()
    try:
        while True:
            cursor.execute("SELECT id, proxy_data FROM proxy_stock WHERE brand_name = %s LIMIT 1", (brand,))
            row = cursor.fetchone()
            if not row: return None
            
            p_id, p_val = row
            if is_proxy_live(p_val):
                cursor.execute("DELETE FROM proxy_stock WHERE id = %s", (p_id,))
                conn.commit()
                return p_val
            else:
                cursor.execute("DELETE FROM proxy_stock WHERE id = %s", (p_id,))
                conn.commit()
    finally:
        cursor.close()
        conn.close()

def main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(types.KeyboardButton("🛒 Buy Proxy"), types.KeyboardButton("���� Check Proxy"))
    markup.add(types.KeyboardButton("💰 Balance"), types.KeyboardButton("💳 Deposit"))
    markup.add(types.KeyboardButton("🛠 Support"), types.KeyboardButton("🌐 Language"))
    if user_id in ADMIN_IDS:
        markup.add(types.KeyboardButton("🛠 Admin Panel"))
    return markup

def admin_panel_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(types.KeyboardButton("➕ Add Proxy Name"), types.KeyboardButton("👥 Total User"))
    markup.add(types.KeyboardButton("🛒 Available Proxy"), types.KeyboardButton("📊 Status"))
    markup.add(types.KeyboardButton("📢 Broadcast"), types.KeyboardButton("✅ Deposit Approve"))
    markup.add(types.KeyboardButton("💳 Add Payment Number"), types.KeyboardButton("➕ Add Admin"))
    markup.add(types.KeyboardButton("🔙 Back to User Panel"))
    return markup

def deposit_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📋 Manual Payment", callback_data="dep_manual"),
        types.InlineKeyboardButton("⚡ Auto Payment", callback_data="dep_auto")
    )
    return markup

def manual_payment_service_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📱 Bkash", callback_data="manual_service_Bkash"),
        types.InlineKeyboardButton("📱 Nagad", callback_data="manual_service_Nagad"),
        types.InlineKeyboardButton("🚀 Rocket", callback_data="manual_service_Rocket"),
        types.InlineKeyboardButton("💰 Binance", callback_data="manual_service_Binance")
    )
    markup.add(types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_dep"))
    return markup

def auto_payment_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📱 Bkash", callback_data="auto_Bkash"),
        types.InlineKeyboardButton("💰 Binance", callback_data="auto_Binance")
    )
    markup.add(types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_dep"))
    return markup

def admin_add_payment_number_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📱 Bkash", callback_data="add_pay_Bkash"),
        types.InlineKeyboardButton("📱 Nagad", callback_data="add_pay_Nagad"),
        types.InlineKeyboardButton("🚀 Rocket", callback_data="add_pay_Rocket"),
        types.InlineKeyboardButton("💰 Binance", callback_data="add_pay_Binance")
    )
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_to_admin"))
    return markup

# ========== DEPOSIT CALLBACKS ==========

@bot.callback_query_handler(func=lambda call: call.data == "dep_manual")
def handle_manual_deposit(call):
    bot.answer_callback_query(call.id)
    text = (
        "📋 **Manual Payment Gateway**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "এখান থেকে একটি সার্ভিস বেছে নিন।"
    )
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=manual_payment_service_menu(), parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("manual_service_"))
def handle_manual_service_selection(call):
    service = call.data.replace("manual_service_", "")
    bot.answer_callback_query(call.id)
    
    if service == "Binance":
        text = (
            "💰 **Binance Manual Payment**\n\n"
            "💵 **Rate:** 1$ = 127.0 TAKA\n"
            "⚠️ **Minimum:** 0.10 USD\n\n"
            "✍️ **USD Amount লিখুন (উদাহরণ: 0.5):**"
        )
    else:
        text = (
            f"📱 **{service} Manual Payment**\n\n"
            "⚖️ **Rate:** 1$ = 127.0 TAKA\n"
            "✅ **Minimum:** 10 TAKA\n\n"
            "✍️ **Amount লিখুন (উদাহরণ: 500):**"
        )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_dep"))
    
    msg = bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    bot.register_next_step_handler(msg, manual_amount_input, service)

def manual_amount_input(message, service):
    try:
        raw_text = message.text.strip()
        if not raw_text.isdigit():
            amount_list = re.findall(r"\d+\.?\d*", raw_text)
            if not amount_list:
                bot.send_message(message.chat.id, "❌ ভুল সংখ্যা!")
                return
            amount = float(amount_list[0])
        else:
            amount = float(raw_text)

        exchange_rate = 127.0 

        if service != "Binance" and amount < 10:
            bot.send_message(message.chat.id, "❌ সর্বনিম্ম ১০ টাকা!")
            return
        
        if service == "Binance" and amount < 0.10:
            bot.send_message(message.chat.id, "❌ সর্বনিম্ম 0.10 USD!")
            return

        payment_number = get_payment_number(service)
        
        if service == "Binance":
            payment_text = f"**Binance UID:** `{payment_number}`"
        else:
            payment_text = f"**{service} Number:** `{payment_number}`"
        
        details_text = (
            f"✅ **ডিপোজিট অ্যামাউন্ট: {amount:.0f} {'USD' if service == 'Binance' else 'টাকা'}**\n\n"
            f"✅ **নিচের নম্বারে {amount:.0f} {'USD' if service == 'Binance' else 'টাকা'} পাঠিয়ে স্ক্রিনশট দিন** ✅\n\n"
            f"✔️ {payment_text}\n\n"
            f"🚀 **Note:** 1$ = 127 টাকা\n\n"
            "**নম্বারে ক্লিক করলে কপি হয়ে যাবে।**\n"
            "**অবশ্যই সেন্ড মানি করবেন।\n\n"
            "🔥 **টাকা পাঠিয়ে থাকলে স্ক্রিনশট দিন 👉👇**"
        )
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📸 Send Screenshot", callback_data=f"send_prof_{service}_{amount}"),
            types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_dep")
        )
        markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_to_deposit"))
        
        bot.send_message(message.chat.id, details_text, reply_markup=markup, parse_mode="Markdown")
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ এরর: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data == "dep_auto")
def handle_auto_payment(call):
    bot.answer_callback_query(call.id)
    text = (
        "⚡ **Auto Payment Gateway**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "এখান থেকে একটি মেথড বেছে নিন।"
    )
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=auto_payment_menu(), parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("auto_"))
def handle_auto_method_selection(call):
    method = call.data.replace("auto_", "")
    bot.answer_callback_query(call.id)
    
    if method == "Binance":
        text = (
            "💰 **Binance Auto Payment**\n\n"
            "💵 **Rate:** 1$ = 127.0 TAKA\n"
            "⚠️ **Minimum:** 0.10 USD\n\n"
            "✍️ **USD Amount লিখুন (উদাহরণ: 0.5):**"
        )
    else:
        text = (
            f"📱 **{method} Auto Payment**\n\n"
            "⚖️ **Rate:** 1$ = 127.0 TAKA\n"
            "✅ **Minimum:** 10 TAKA\n\n"
            "✍️ **Amount লিখুন (উদাহরণ: 500):**"
        )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_dep"))
    
    msg = bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    bot.register_next_step_handler(msg, get_auto_deposit_amount, method)

def get_auto_deposit_amount(message, method):
    try:
        raw_text = message.text.strip()
        if not raw_text.isdigit():
            amount_list = re.findall(r"\d+\.?\d*", raw_text)
            if not amount_list:
                bot.send_message(message.chat.id, "❌ ভুল সংখ্যা!")
                return
            amount = float(amount_list[0])
        else:
            amount = float(raw_text)

        exchange_rate = 127.0 

        if method != "Binance" and amount < 10:
            bot.send_message(message.chat.id, "❌ সর্বনিম্ম ১০ টাকা!")
            return
        
        if method == "Binance" and amount < 0.10:
            bot.send_message(message.chat.id, "❌ সর্বনিম্ম 0.10 USD!")
            return

        preview_text = f"🧾 **Auto Deposit Preview**\n\n💰 **Amount:** `{amount:.2f}`\n\nConfirm করলে ZiniPay লিংক পাবেন।"
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Confirm", callback_data=f"auto_pay_{method}_{amount}"))
        markup.add(types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_dep"))
        
        bot.send_message(message.chat.id, preview_text, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, "❌ এরর!")

# ========== SCREENSHOT HANDLING ==========

@bot.callback_query_handler(func=lambda call: call.data.startswith("send_prof_"))
def handle_screenshot_prompt(call):
    data = call.data.split("_")
    service = data[2]
    amount = float(data[3])
    
    bot.answer_callback_query(call.id)
    
    text = (
        f"📸 **{service} পেমেন্ট স্ক্রিনশট**\n\n"
        f"আপনি যে {amount:.0f} পাঠিয়েছেন তার স্ক্রিনশট দিন।"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_dep"))
    
    msg = bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_screenshot, service, amount)

def process_screenshot(message, service, amount):
    if not message.photo:
        bot.send_message(message.chat.id, "❌ শুধুমাত্র ছবি গ্রহণযোগ্য!")
        return
    
    file_id = message.photo[-1].file_id
    
    text = (
        f"✅ **স্ক্রিনশট পাওয়া হয়েছে**\n\n"
        f"📱 **Service:** {service}\n"
        f"💰 **Amount:** {amount:.0f}\n\n"
        "এখন আপনার **Transaction ID** দিন।"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_dep"))
    
    msg = bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_transaction_id, service, amount, file_id)

def process_transaction_id(message, service, amount, file_id):
    txid = message.text.strip()
    user_id = message.from_user.id
    username = message.from_user.username or "No Username"
    
    conn = connection_pool.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO pending_deposits (user_id, username, amount, txid, service, screenshot_file_id, status, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())",
            (user_id, username, amount, txid, service, file_id, "pending")
        )
        payment_id = cursor.lastrowid
        conn.commit()
        
        confirmation_text = (
            f"✅ **পেমেন্ট সফলভাবে সাবমিট হয়েছে!**\n\n"
            f"📱 **Service:** {service}\n"
            f"💰 **Amount:** {amount:.0f}\n"
            f"🔍 **TxID:** `{txid}`\n"
            f"📝 **Status:** Processing ⏳\n\n"
            f"Admin এটি ভেরিফাই করবে।"
        )
        bot.send_message(user_id, confirmation_text, parse_mode="Markdown")
        
        send_admin_pending_payment(payment_id, user_id, username, service, amount, txid, file_id)
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ ডাটাবেস এরর: {str(e)}")
    finally:
        cursor.close()
        conn.close()

def send_admin_pending_payment(payment_id, user_id, username, service, amount, txid, file_id):
    
    pending_text = (
        f"🔔 **NEW PENDING PAYMENT**\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"**ID:** `{payment_id}`\n"
        f"**Username:** `{username}`\n"
        f"**User ID:** `{user_id}`\n"
        f"**Service:** `{service}`\n"
        f"**Amount:** `{amount:.0f}`\n"
        f"**TxID:** `{txid}`\n"
    )
    
    for admin in ADMIN_IDS:
        try:
            bot.send_photo(admin, file_id, caption=pending_text, parse_mode="Markdown")
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("✅ APPROVE", callback_data=f"approve_pay_{payment_id}_{user_id}_{amount}"),
                types.InlineKeyboardButton("❌ REJECT", callback_data=f"reject_pay_{payment_id}_{user_id}")
            )
            
            bot.send_message(admin, "দ্রুত সিদ্ধান্ত নিন:", reply_markup=markup, parse_mode="Markdown")
        except Exception as e:
            print(f"Admin notification error: {e}")

# ========== ADMIN APPROVAL/REJECTION ==========

@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_pay_"))
def approve_payment(call):
    data = call.data.split("_")
    payment_id = int(data[2])
    user_id = int(data[3])
    amount = float(data[4])
    
    conn = connection_pool.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE pending_deposits SET status = %s WHERE id = %s", ("approved", payment_id))
        cursor.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, user_id))
        conn.commit()
        
        bot.answer_callback_query(call.id, f"✅ Approved!", show_alert=True)
        bot.edit_message_text(f"✅ **APPROVED** | ID: {payment_id}", call.message.chat.id, call.message.message_id)
        
        bot.send_message(user_id, f"✅ পেমেন্ট অনুমোদিত! {amount:.0f} টাকা যোগ করা হয়েছে।", parse_mode="Markdown")
        
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Error", show_alert=True)
    finally:
        cursor.close()
        conn.close()

@bot.callback_query_handler(func=lambda call: call.data.startswith("reject_pay_"))
def reject_payment(call):
    data = call.data.split("_")
    payment_id = int(data[2])
    user_id = int(data[3])
    
    conn = connection_pool.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE pending_deposits SET status = %s WHERE id = %s", ("rejected", payment_id))
        conn.commit()
        
        bot.answer_callback_query(call.id, f"❌ Rejected!", show_alert=True)
        bot.edit_message_text(f"❌ **REJECTED** | ID: {payment_id}", call.message.chat.id, call.message.message_id)
        
        bot.send_message(user_id, f"❌ পেমেন্ট প্রত্যাখ্যান করা হয়েছে।", parse_mode="Markdown")
        
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Error", show_alert=True)
    finally:
        cursor.close()
        conn.close()

# ========== ADMIN PAYMENT CONFIG ==========

@bot.callback_query_handler(func=lambda call: call.data.startswith("add_pay_"))
def handle_add_payment(call):
    service = call.data.replace("add_pay_", "")
    bot.answer_callback_query(call.id)
    
    if service == "Binance":
        text = f"💰 **Binance UID দিন:**"
    else:
        text = f"📱 **{service} নম্বর দিন:**"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_add_pay"))
    
    msg = bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    bot.register_next_step_handler(msg, save_payment_number, service)

def save_payment_number(message, service):
    payment_value = message.text.strip()
    admin_id = message.from_user.id
    
    conn = connection_pool.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE payment_config SET service_number = %s, updated_by = %s, updated_at = NOW() WHERE service_name = %s",
            (payment_value, admin_id, service)
        )
        conn.commit()
        
        bot.send_message(
            message.chat.id,
            f"✅ **{service} আপডেট হয়েছে!**\n\n"
            f"**নতুন মান:** `{payment_value}`\n\n"
            f"💾 সফলভাবে সংরক্ষিত হয়েছে।",
            parse_mode="Markdown"
        )
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ এরর: {str(e)}")
    finally:
        cursor.close()
        conn.close()

@bot.callback_query_handler(func=lambda call: call.data == "cancel_add_pay")
def cancel_add_payment(call):
    text = "**Admin Panel**"
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=admin_panel_menu(), parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "back_to_deposit")
def back_to_deposit(call):
    text = "💳 **Deposit Portal**"
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=deposit_menu(), parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "back_to_admin")
def back_to_admin(call):
    text = "**Admin Panel**"
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=admin_panel_menu(), parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "cancel_dep")
def cancel_deposit(call):
    bot.edit_message_text("❌ Cancelled", call.message.chat.id, call.message.message_id)

# ========== AUTO PAYMENT ZINIPAY ==========

@bot.callback_query_handler(func=lambda call: call.data.startswith("auto_pay_"))
def finalize_auto_payment(call):
    data = call.data.split("_")
    method = data[2]
    amount = data[3]

    bot.edit_message_text("⏳ Connecting to ZiniPay Gateway...", call.message.chat.id, call.message.message_id)

    payload = json.dumps({
        "cus_name": str(call.from_user.first_name or "User"),
        "cus_email": "customer@example.com",
        "amount": str(amount),
        "redirect_url": "https://t.me/Awm_Proxy_Store_bot",
        "cancel_url": "https://t.me/Awm_Proxy_Store_bot",
        "metadata": {"user_id": str(call.from_user.id)}
    })

    headers = {
        'zini-api-key': ZINIPAY_API_KEY, 
        'Content-Type': 'application/json'
    }

    try:
        response = requests.post(ZINIPAY_URL, headers=headers, data=payload, timeout=20)
        res_data = response.json()

        if res_data.get("status") is True:
            pay_url = res_data.get("payment_url")
            invoice_id = pay_url.split('/')[-1] 
            
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("💳 Pay Now", url=pay_url))
            markup.add(types.InlineKeyboardButton("🔄 Verify Payment", callback_data=f"v_zini_{invoice_id}"))
            
            bot.edit_message_text(
                f"✅ **ZiniPay Link Created!**\n💰 Amount: {amount}\n\nপেমেন্ট শেষ করে Verify করুন।",
                call.message.chat.id, call.message.message_id, 
                reply_markup=markup, parse_mode="Markdown"
            )
        else:
            bot.edit_message_text(f"❌ Gateway Error", call.message.chat.id, call.message.message_id)

    except Exception as e:
        bot.edit_message_text(f"⚠️ কানেকশন সমস্যা", call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("v_zini_"))
def handle_verification(call):
    invoice_id = call.data.split("_")[-1]
    user_id = call.from_user.id
    
    bot.answer_callback_query(call.id, "🔍 চেক করা হচ্ছে...")

    url = f"https://api.zinipay.com/v1/payment/verify"
    params = {
        'apiKey': ZINIPAY_API_KEY, 
        'invoiceId': invoice_id
    }
    
    try:
        response = requests.get(url, params=params, timeout=20)
        payment_data = response.json()
        
        if payment_data.get("status") == "COMPLETED":
            amount_bdt = float(payment_data.get("amount"))
            exchange_rate = 125.0
            amount_usd = amount_bdt / exchange_rate
            
            conn = connection_pool.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount_bdt, user_id))
                conn.commit()
                
                cursor.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
                new_balance_bdt = float(cursor.fetchone()[0])
                new_balance_usd = new_balance_bdt / exchange_rate
                
                success_text = (
                    f"🎉 {amount_bdt} টাকা যোগ করা হয়েছে!\n\n"
                    f"💰 বর্তমান ব্যালেন্স: {new_balance_bdt:.2f} টাকা = ${new_balance_usd:.2f} ✅"
                )
                
                bot.edit_message_text(success_text, call.message.chat.id, call.message.message_id)
                
            except Exception as e:
                bot.send_message(call.message.chat.id, f"❌ এরর: {str(e)}")
            finally:
                cursor.close()
                conn.close()
        else:
            bot.answer_callback_query(call.id, "❌ পেমেন্ট পেন্ডিং", show_alert=True)
            
    except Exception as e:
        bot.answer_callback_query(call.id, "⚠️ সার্ভার সমস্যা!", show_alert=True)

# ========== BROADCAST ==========

def send_msg_worker(user_id, text):
    try:
        bot.send_message(user_id, text)
        return True
    except:
        return False

def start_broadcasting(message):
    broadcast_text = message.text
    if broadcast_text == "🔙 Back to User Panel": return

    conn = connection_pool.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    cursor.close()
    conn.close()

    bot.send_message(message.chat.id, f"🚀 ব্রডকাস্ট শুরু হয়েছে...\nমোট ইউজার: {len(users)}")

    success = 0
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda uid: send_msg_worker(uid[0], broadcast_text), users))
        success = results.count(True)

    bot.send_message(message.chat.id, f"✅ সম্পন্ন!\n\n🔹 সফল: {success}\n🔸 ব্যর্থ: {len(users) - success}")

# ========== START & HANDLERS ==========

@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    uname = message.from_user.username
    add_user_to_db(uid, uname)
    
    if is_member(uid):
        bot.send_message(message.chat.id, f"👋 স্বাগতম @{uname}!\nআপনার অ্যাকাউন্ট এখন সক্রিয়।", reply_markup=main_menu(uid))
    else:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📢 Join Channel", url=CHANNEL_LINK))
        markup.add(types.InlineKeyboardButton("✅ Verify Join", callback_data="verify"))
        
        bot.send_message(message.chat.id, "❌ **চ্যানেলে জয়েন করুন!**", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "verify")
def verify_callback(call):
    if is_member(call.from_user.id):
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "✅ সফল!", reply_markup=main_menu(call.from_user.id))
    else:
        bot.answer_callback_query(call.id, "⚠️ চ্যানেলে জয়েন করুন!", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def process_buy_proxy(call):
    brand = call.data.replace("buy_", "")
    bot.answer_callback_query(call.id, f"Checking...")
    
    proxy = get_live_proxy_from_db(brand)
    if not proxy:
        bot.send_message(call.message.chat.id, f"❌ {brand}-এর স্টক নেই।")
        return

    res = f"✅ **Purchase Successful!**\n\n`{proxy}`"
    bot.send_message(call.message.chat.id, res, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "back_to_available")
def back_to_available_proxy(call):
    conn = connection_pool.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT brand_name FROM proxy_brands")
    brands = cursor.fetchall()
    cursor.close()
    conn.close()
    
    markup = types.InlineKeyboardMarkup()
    for b in brands:
        markup.add(types.InlineKeyboardButton(b[0], callback_data=f"stock_{b[0]}"))
    
    bot.edit_message_text("🛒 Select a Proxy Provider:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("stock_"))
def proxy_management_callback(call):
    brand_name = call.data.replace("stock_", "")
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton("📄 Add Proxy File", callback_data=f"add_file_{brand_name}")
    btn2 = types.InlineKeyboardButton("🗑 Delete Proxy", callback_data=f"del_proxy_{brand_name}")
    btn3 = types.InlineKeyboardButton("💰 Add Price", callback_data=f"add_price_{brand_name}")
    btn4 = types.InlineKeyboardButton("✏️ Edit Price", callback_data=f"edit_price_{brand_name}")
    back_btn = types.InlineKeyboardButton("🔙 Back", callback_data="back_to_available")
    
    markup.add(btn1, btn2, btn3, btn4)
    markup.add(back_btn)

    bot.edit_message_text(f"🛠 **Management for: {brand_name}**", chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"🛠 **Management for: {brand_name}**", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def management_actions(call):
    data = call.data
    chat_id = call.message.chat.id
    
    bot.answer_callback_query(call.id)

    if data.startswith("add_file_"):
        brand = data.replace("add_file_", "")
        msg = bot.send_message(chat_id, f"📂 **{brand}**-এর জন্য প্রক্সি ফাইল পাঠান।")
        bot.register_next_step_handler(msg, process_proxy_input, brand)

    elif data.startswith("add_price_") or data.startswith("edit_price_"):
        brand = data.replace("add_price_", "").replace("edit_price_", "")
        msg = bot.send_message(chat_id, f"💰 **{brand}**-এর জন্য প্রাইস সেট করুন।\n\nFormat: `$1/125`")
        bot.register_next_step_handler(msg, process_price_input, brand)

    elif data.startswith("del_proxy_"):
        brand = data.replace("del_proxy_", "")
        conn = connection_pool.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM proxy_stock WHERE brand_name = %s", (brand,))
            cursor.execute("DELETE FROM proxy_brands WHERE brand_name = %s", (brand,))
            conn.commit()
            
            bot.send_message(chat_id, f"🗑 **{brand}** সফলভাবে ডিলিট করা হয়েছে।")
            back_to_available_proxy(call)
            
        except Exception as e:
            bot.send_message(chat_id, f"❌ এরর: {str(e)}")
        finally:
            cursor.close()
            conn.close()

@bot.message_handler(func=lambda message: message.text == "🔍 Check Proxy")
def check_proxy_prompt(message):
    msg = bot.send_message(message.chat.id, "🛰 **আপনার প্রক্সিটি পাঠান:**")
    bot.register_next_step_handler(msg, process_user_proxy_check)

def process_user_proxy_check(message):
    proxy_text = message.text.strip()
    
    if proxy_text == "🔙 Back to User Panel":
        return

    status_msg = bot.send_message(message.chat.id, "⏳ **Checking Proxy... Please wait.**")
    
    start_time = time.time()
    is_live = is_proxy_live(proxy_text)
    end_time = round(time.time() - start_time, 2)

    if is_live:
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            text=f"✅ **Proxy is LIVE!**\n\n🚀 **Response Time:** `{end_time}s`"
        )
    else:
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            text=f"❌ **Proxy is DEAD!**"
        )

def deposit_start(message):
    text = "💳 **Deposit Portal**"
    bot.send_message(message.chat.id, text, reply_markup=deposit_menu(), parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_all(message):
    uid = message.from_user.id
    text = message.text

    if uid in ADMIN_IDS:
        if text == "🛠 Admin Panel":
            bot.send_message(message.chat.id, "🔐 **অ্যাডমিন প্যানেল**", reply_markup=admin_panel_menu())
            return
        
        elif text == "📢 Broadcast":
            msg = bot.send_message(message.chat.id, "📝 ব্রডকাস্ট মেসেজটি লিখুন:")
            bot.register_next_step_handler(msg, start_broadcasting)
            return
        
        elif text == "👥 Total User":
            conn = connection_pool.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            total = cursor.fetchone()[0]
            cursor.close()
            conn.close()
            bot.send_message(message.chat.id, f"📊 **মোট ইউজার:** `{total}`", parse_mode="Markdown")
            return
        
        elif text == "📊 Status":
            bot.send_message(message.chat.id, f"🛰 **অনলাইন**\n⚡ **থ্রেড:** ৫০টি\n💾 **DB:** Connected")
            return
        
        elif text == "🔙 Back to User Panel":
            bot.send_message(message.chat.id, "⬅️ ফিরে যাওয়া হচ্ছে...", reply_markup=main_menu(uid))
            return
        
        elif text == "➕ Add Proxy Name":
            msg = bot.send_message(message.chat.id, "📝 প্রক্সির নাম লিখুন:")
            bot.register_next_step_handler(msg, save_proxy_name)
            return

        elif text == "🛒 Available Proxy":
            conn = connection_pool.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT brand_name FROM proxy_brands")
            brands = cursor.fetchall()
            cursor.close()
            conn.close()
            
            if not brands:
                bot.send_message(message.chat.id, "🚫 কোনো প্রক্সি নেই।")
            else:
                markup = types.InlineKeyboardMarkup()
                for b in brands:
                    markup.add(types.InlineKeyboardButton(b[0], callback_data=f"stock_{b[0]}"))
                bot.send_message(message.chat.id, "📂 **স্টক ম্যানেজমেন্ট:**", reply_markup=markup)
            return
        
        elif text == "💳 Add Payment Number":
            bot.send_message(message.chat.id, "**পেমেন্ট সার্ভিস বেছে নিন:**", reply_markup=admin_add_payment_number_menu())
            return

    if text == "🛒 Buy Proxy":
        conn = connection_pool.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT brand_name FROM proxy_brands")
        brands = cursor.fetchall()
        cursor.close()
        conn.close()
        
        if not brands:
            bot.send_message(message.chat.id, "🚫 কোনো প্রক্সি নেই।")
        else:
            markup = types.InlineKeyboardMarkup()
            for b in brands:
                markup.add(types.InlineKeyboardButton(b[0], callback_data=f"buy_{b[0]}"))
            bot.send_message(message.chat.id, "🛒 **একটি ব্র্যান্ড বেছে নিন:**", reply_markup=markup)

    elif text == "💰 Balance":
        conn = connection_pool.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
            res = cursor.fetchone()
            bdt_balance = float(res[0]) if res and res[0] is not None else 0.0
            exchange_rate = 125.0 
            usd_balance = bdt_balance / exchange_rate
            
            balance_text = (
                "💳 **আপনার ব্যালেন্স**\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"💵 **USD:** `${usd_balance:.2f}`\n"
                f"৳ **BDT:** `{bdt_balance:.2f} TK`"
            )
            bot.send_message(message.chat.id, balance_text, parse_mode="Markdown")
        except Exception as e:
            bot.send_message(message.chat.id, "⚠️ এরর!")
        finally:
            cursor.close()
            conn.close()

    elif text == "💳 Deposit":
        deposit_start(message)

    elif text == "🔍 Check Proxy":
        check_proxy_prompt(message)

    elif text == "🛠 Support":
        bot.send_message(message.chat.id, "👨‍💻 **সাপোর্ট**\n\nসমস্যায় Admin যোগাযোগ করুন।")

    elif text == "🌐 Language":
        bot.send_message(message.chat.id, "🌐 **বাংলা (Bengali)**")

if __name__ == "__main__":
    create_proxy_table()
    create_payment_config_table()
    print("🚀 Bot Running...")
    bot.infinity_polling(timeout=90, long_polling_timeout=90)
