import os
import logging
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

import requests
from bs4 import BeautifulSoup
from urllib.parse import quote

TOKEN = "7062147168:AAGHaOBKLIpvEqFPJdvs7uLjr81zWzjWlIk"
BOT_USERNAME = "Quet_gia_bot"
WEBHOOK_URL = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/webhook"

app = Flask(__name__)
telegram_app = ApplicationBuilder().token(TOKEN).build()

logging.basicConfig(level=logging.INFO)

# --- HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Xin chào! Gửi tin nhắn như PICO:AC-305 để tìm giá sản phẩm nhé.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.upper().startswith("PICO:"):
        query = text.split(":", 1)[1].strip()
        await update.message.reply_text(f"🔍 Đang tìm *{query}* trên *pico.vn*...", parse_mode="Markdown")
        result = search_pico(query)
        if result:
            title, price, promo, url, image = result
            message = f"✅ *{title}*\n💰 *Giá:* {price}\n🎁 *KM:* {promo or 'Không có'}"
            keyboard = [[InlineKeyboardButton("🔗 Xem sản phẩm", url=url)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_photo(photo=image, caption=message, parse_mode="Markdown", reply_markup=reply_markup)
        else:
            await update.message.reply_text("❌ Không tìm thấy sản phẩm trên pico.vn.")
    else:
        await update.message.reply_text("Vui lòng gửi theo cú pháp như: `PICO:AC-305`", parse_mode="Markdown")

def search_pico(query):
    headers = {"User-Agent": "Mozilla/5.0"}
    search_url = f"https://www.google.com/search?q={quote(query)}+site%3Apico.vn"
    res = requests.get(search_url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")
    links = [a['href'] for a in soup.select('a') if '/url?q=' in a['href']]
    product_link = None
    for link in links:
        url = link.split("/url?q=")[1].split("&")[0]
        if "pico.vn" in url and "/san-pham/" in url:
            product_link = url
            break
    if not product_link:
        return None

    res = requests.get(product_link, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")
    title_tag = soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else query
    price_tag = soup.select_one(".product-price, .price")
    price = price_tag.get_text(strip=True) if price_tag else "Không rõ"
    promo_tag = soup.select_one(".product-promo, .special-price")
    promo = promo_tag.get_text(strip=True) if promo_tag else None
    og_image = soup.find("meta", property="og:image")
    image_url = og_image["content"] if og_image and og_image.get("content") else None
    return title, price, promo, product_link, image_url

# --- REGISTER HANDLERS ---
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# --- FLASK ROUTES ---
@app.route('/webhook', methods=['POST'])
async def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return 'OK'

@app.route('/')
def home():
    return 'Bot is running!'

# --- SET WEBHOOK WHEN APP STARTS ---
@app.before_first_request
def setup_webhook():
    telegram_app.bot.set_webhook(WEBHOOK_URL)

