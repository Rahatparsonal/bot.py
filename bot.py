# -*- coding: utf-8 -*-
import asyncio
import re
import requests
from bs4 import BeautifulSoup
import time
import json
import os
import traceback
from telegram import Bot
from urllib.parse import urljoin
from datetime import datetime, timedelta

YOUR_BOT_TOKEN = "8182995788:AAHqlO0RWeMJgxp9c0bTPwPptzqdd1BdOaE"
YOUR_CHAT_IDS = ["-1002525241084"]

LOGIN_URL = "https://www.ivasms.com/login"
BASE_URL = "https://www.ivasms.com/"
SMS_API_ENDPOINT = "https://www.ivasms.com/portal/sms/received/getsms"

USERNAME = "mdrahatparsonal@gmail.com"
PASSWORD = "Rahat@999"

POLLING_INTERVAL_SECONDS = 0.4
STATE_FILE = "processed_sms_ids_ivasms.json"

COUNTRY_FLAGS = {
    "Afghanistan": "🇦🇫", "Bangladesh": "🇧🇩", "India": "🇮🇳",
    "United States": "🇺🇸", "Pakistan": "🇵🇰", "Nepal": "🇳🇵",
    "United Kingdom": "🇬🇧", "Saudi Arabia": "🇸🇦", "TOGO": "🇹🇬",
    "Unknown Country": "🏴‍☠️"
}

KNOWN_SERVICES = {
    "Telegram": "📩", "WhatsApp": "🟢", "Facebook": "📘", "Instagram": "📸", "Messenger": "💬",
    "Google": "🔍", "Gmail": "✉️", "YouTube": "▶️", "Twitter": "🐦", "X": "❌",
    "TikTok": "🎵", "Snapchat": "👻", "Amazon": "🛒", "eBay": "📦", "AliExpress": "📦",
    "Alibaba": "🏭", "Flipkart": "📦", "Microsoft": "🪟", "Outlook": "📧", "Skype": "📞",
    "Netflix": "🎬", "Spotify": "🎶", "Apple": "🍏", "iCloud": "☁️", "PayPal": "💰",
    "Stripe": "💳", "Cash App": "💵", "Venmo": "💸", "Zelle": "🏦", "Wise": "🌐",
    "Binance": "🪙", "Coinbase": "🪙", "KuCoin": "🪙", "Bybit": "📈", "OKX": "🟠",
    "Huobi": "🔥", "Kraken": "🐙", "MetaMask": "🦊", "Discord": "🗨️", "Steam": "🎮",
    "Epic Games": "🕹️", "PlayStation": "🎮", "Xbox": "🎮", "Twitch": "📺", "Reddit": "👽",
    "Yahoo": "🟣", "ProtonMail": "🔐", "Zoho": "📬", "Quora": "❓", "StackOverflow": "🧑‍💻",
    "LinkedIn": "💼", "Indeed": "📋", "Upwork": "🧑‍💻", "Fiverr": "💻", "Glassdoor": "🔎",
    "Airbnb": "🏠", "Booking.com": "🛏️", "Uber": "🚗", "Lyft": "🚕", "Bolt": "🚖",
    "Careem": "🚗", "Swiggy": "🍔", "Zomato": "🍽️", "Foodpanda": "🍱",
    "McDonald's": "🍟", "KFC": "🍗", "Nike": "👟", "Adidas": "👟", "Shein": "👗",
    "OnlyFans": "🔞", "Tinder": "🔥", "Bumble": "🐝", "Grindr": "😈", "Signal": "🔐",
    "Viber": "📞", "Line": "💬", "WeChat": "💬", "VK": "🌐", "Unknown": "❓"
}

def escape_markdown(text):
    escape_chars = r'\\_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))

def detect_service(sms_text, service_div_text):
    """SMS টেক্সট ও সার্ভিস ডিভ টেক্সট দেখে সঠিক সার্ভিস নাম ও আইকন বের করে।"""
    service_text = service_div_text or ""
    # সার্ভিস ডিভ থেকে চেষ্টা করব সনাক্ত করতে
    for svc_name in KNOWN_SERVICES:
        if svc_name.lower() in service_text.lower() or svc_name.lower() in sms_text.lower():
            return svc_name
    return "Unknown"

async def send_telegram_message(bot_token, chat_id, message_data):
    try:
        time_str = message_data.get("time", "N/A")
        number_str = message_data.get("number", "N/A")
        country_name = message_data.get("country", "N/A")
        flag_emoji = message_data.get("flag", "🏴‍☠️")
        service_name = message_data.get("service", "Unknown")
        code_str = message_data.get("code", "N/A")
        full_sms_text = message_data.get("full_sms", "N/A")

        icon = KNOWN_SERVICES.get(service_name, "❓")

        full_message = (
            f"🔔 *You have successfully received OTP*\n\n"
            f"📞 *Number:* `{escape_markdown(number_str)}`\n"
            f"🔑 *Code:* `{escape_markdown(code_str)}`\n"
            f"🏆 *Service:* {icon} {escape_markdown(service_name)}\n"
            f"🌎 *Country:* {escape_markdown(country_name)} {flag_emoji}\n"
            f"⏳ *Time:* `{escape_markdown(time_str)}`\n"
            f"💬 *Message:*\n"
            f"```\n{full_sms_text}\n```"
        )
        bot = Bot(token=bot_token)
        await bot.send_message(chat_id=chat_id, text=full_message, parse_mode='MarkdownV2')
    except Exception as e:
        print(f"❌ চ্যাট আইডি {chat_id}-তে মেসেজ পাঠাতে সমস্যা: {e}")

def load_processed_ids():
    if not os.path.exists(STATE_FILE): return set()
    try:
        with open(STATE_FILE, 'r') as f: return set(json.load(f))
    except (json.JSONDecodeError, FileNotFoundError): return set()

def save_processed_id(sms_id):
    processed_ids = load_processed_ids()
    processed_ids.add(sms_id)
    with open(STATE_FILE, 'w') as f: json.dump(list(processed_ids), f)

def fetch_sms_from_api(session, headers, csrf_token):
    all_messages = []
    try:
        today = datetime.now()
        start_date = today - timedelta(days=1)
        from_date_str = start_date.strftime('%m/%d/%Y')
        to_date_str = today.strftime('%m/%d/%Y')

        first_payload = {'from': from_date_str, 'to': to_date_str, '_token': csrf_token}
        print("ℹ️ ধাপ ১: SMS গ্রুপগুলোর তালিকা আনা হচ্ছে...")
        summary_response = session.post(SMS_API_ENDPOINT, headers=headers, data=first_payload)
        summary_response.raise_for_status()
        summary_soup = BeautifulSoup(summary_response.text, 'html.parser')
        group_divs = summary_soup.find_all('div', {'class': 'pointer'})
        if not group_divs:
            print("✔️ কোনো SMS গ্রুপ পাওয়া যায়নি।")
            return []
        group_ids = [re.search(r"getDetials\('(.+?)'\)", div.get('onclick', '')).group(1) for div in group_divs if re.search(r"getDetials\('(.+?)'\)", div.get('onclick', ''))]
        print(f"✅ ধাপ ১ সম্পন্ন। {len(group_ids)} টি গ্রুপ পাওয়া গেছে।")

        numbers_url = urljoin(BASE_URL, "portal/sms/received/getsms/number")
        sms_url = urljoin(BASE_URL, "portal/sms/received/getsms/number/sms")

        for group_id in group_ids:
            print(f"ℹ️ ধাপ ২: '{group_id}' গ্রুপ থেকে ফোন নম্বর আনা হচ্ছে...")
            numbers_payload = {'start': from_date_str, 'end': to_date_str, 'range': group_id, '_token': csrf_token}
            numbers_response = session.post(numbers_url, headers=headers, data=numbers_payload)
            numbers_soup = BeautifulSoup(numbers_response.text, 'html.parser')
            number_divs = numbers_soup.select("div[onclick*='getDetialsNumber']")
            if not number_divs: continue
            phone_numbers = [div.text.strip() for div in number_divs]
            print(f"✅ '{group_id}' গ্রুপে {len(phone_numbers)} টি নম্বর পাওয়া গেছে।")

            for phone_number in phone_numbers:
                print(f"ℹ️ ধাপ ৩: '{phone_number}' নম্বর থেকে SMS আনা হচ্ছে...")
                sms_payload = {'start': from_date_str, 'end': to_date_str, 'Number': phone_number, 'Range': group_id, '_token': csrf_token}
                sms_response = session.post(sms_url, headers=headers, data=sms_payload)
                sms_soup = BeautifulSoup(sms_response.text, 'html.parser')
                final_sms_cards = sms_soup.find_all('div', class_='card-body')

                for card in final_sms_cards:
                    sms_text_p = card.find('p', class_='mb-0')
                    if sms_text_p:
                        sms_text = sms_text_p.get_text(separator='\n').strip()
                        date_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        country_name = group_id.split(' ')[0]
                        service_div = card.find('div', class_='col-sm-4')
                        service_div_text = service_div.text if service_div else ""
                        service = detect_service(sms_text, service_div_text)
                        code_match = re.search(r'(\d{3}-\d{3})', sms_text) or re.search(r'\b(\d{4,8})\b', sms_text)
                        code = code_match.group(1) if code_match else "N/A"
                        unique_id = f"{phone_number}-{sms_text}"
                        flag = COUNTRY_FLAGS.get(country_name, "🏴‍☠️")

                        all_messages.append({
                            "id": unique_id, "time": date_str, "number": phone_number, "country": country_name,
                            "flag": flag, "service": service, "code": code, "full_sms": sms_text
                        })
        if all_messages:
            print(f"✅✅✅ চূড়ান্ত ধাপ সম্পন্ন। মোট {len(all_messages)} টি মেসেজ পার্স করা হয়েছে।")
        return all_messages
    except Exception as e:
        print(f"❌ API ডেটা আনতে বা প্রসেস করতে সমস্যা হয়েছে: {e}")
        traceback.print_exc()
        return []

def login_and_process():
    headers = {'User-Agent': 'Mozilla/5.0'}
    with requests.Session() as session:
        try:
            print("ℹ️ লগইন করার চেষ্টা করা হচ্ছে...")
            login_data = {'email': USERNAME, 'password': PASSWORD}
            login_page_res = session.get(LOGIN_URL, headers=headers)
            soup = BeautifulSoup(login_page_res.text, 'html.parser')
            token_input = soup.find('input', {'name': '_token'})
            if token_input: login_data['_token'] = token_input['value']
            login_res = session.post(LOGIN_URL, data=login_data, headers=headers)
            login_res.raise_for_status()
            if "login" in login_res.url:
                print("❌ লগইন ব্যর্থ হয়েছে। ইউজারনেম/পাসওয়ার্ড পরীক্ষা করুন।")
                return
            print("✅ লগইন সফল হয়েছে!")
            dashboard_soup = BeautifulSoup(login_res.text, 'html.parser')
            new_token_meta = dashboard_soup.find('meta', {'name': 'csrf-token'})
            new_token_input = dashboard_soup.find('input', {'name': '_token'})
            csrf_token = new_token_meta.get('content') if new_token_meta else new_token_input.get('value') if new_token_input else None
            if not csrf_token:
                print("❌ নতুন CSRF টোকেন খুঁজে পাওয়া যায়নি।")
                return
            headers['Referer'] = login_res.url
            messages = fetch_sms_from_api(session, headers, csrf_token)
            if not messages: return
            processed_ids = load_processed_ids()
            new_messages_found = 0
            for msg in reversed(messages):
                if msg["id"] not in processed_ids:
                    new_messages_found += 1
                    print(f"✔️ নতুন মেসেজ পাওয়া গেছে: {msg['number']} থেকে।")
                    for chat_id in YOUR_CHAT_IDS:
                        asyncio.run(send_telegram_message(YOUR_BOT_TOKEN, chat_id, msg))
                    save_processed_id(msg["id"])
            if new_messages_found > 0:
                print(f"✅ মোট {new_messages_found} টি নতুন মেসেজ টেলিগ্রামে পাঠানো হয়েছে।")
        except Exception as e:
            print(f"❌ মূল প্রসেসে একটি সমস্যা দেখা দিয়েছে: {e}")
            traceback.print_exc()

def main_loop():
    while True:
        print(f"\n--- [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] নতুন মেসেজের জন্য চেক করা হচ্ছে ---")
        login_and_process()
        print(f"--- পরবর্তী চেকের জন্য {POLLING_INTERVAL_SECONDS} সেকেন্ড অপেক্ষা করা হচ্ছে ---")
        time.sleep(POLLING_INTERVAL_SECONDS)

if __name__ == "__main__":
    print("🚀 iVasms to Telegram Bot চালু হচ্ছে...")
    print(f"🚀 প্রতি {POLLING_INTERVAL_SECONDS} সেকেন্ড পর পর নতুন মেসেজের জন্য চেক করা হবে।")
    print("⚠️ বট বন্ধ করতে Ctrl+C চাপুন।")
    main_loop()
