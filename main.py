import logging
import requests
import re
from bs4 import BeautifulSoup
from googlesearch import search
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from flask import Flask, request
import os
import asyncio

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
app = Flask(__name__)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

SUPPORTED_SITES = {
    'nguyenkim': 'nguyenkim.com',
    'hc': 'hc.com.vn',
    'ecomart': 'ecomart.com.vn',
    'dienmaycholon': 'dienmaycholon.vn'
}

def extract_price_and_promo(soup):
    text = soup.get_text(separator=" ", strip=True)
    prices = re.findall(r"\d[\d\.]{3,}(?:₫|đ| VNĐ| vnđ|)", text)
    promos = re.findall(r"(tặng|giảm|quà tặng|ưu đãi|khuyến mãi)[^.:\n]{0,100}", text, flags=re.IGNORECASE)
    return prices[0] if prices else None, promos[0] if promos else None

def get_product_info(query, source_key):
    domain = SUPPORTED_SITES.get(source_key)
    if not domain:
        return "❌ Không hỗ trợ nguồn này."

    try:
        urls = list(search(f"{query} site:{domain}", num_results=5))
        url = next((u for u in urls if domain in u), None)
        if not url:
            return f"❌ Không tìm thấy sản phẩm trên {domain}"

        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")

        title_tag = soup.find("h1")
        title = title_tag.text.strip() if title_tag else query

        price, promo = extract_price_and_promo(soup)
        msg = f"✅ *{title}*"
        if price:
            msg += f"\n💰 Giá: {price}"
        else:
            msg += "\n❌ Không tìm thấy giá rõ ràng."

        if promo:
            msg += f"\n🎁 KM: {promo}"
        msg += f"\n🔗 {url}"
        return msg

    except Exception as e:
        return f"❌ Lỗi: {e}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Nhập theo cú pháp `tenweb:tên sản phẩm`, ví dụ:\n`dienmaycholon:AC-305`")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if ':' not in text:
        await update.message.reply_text("❗ Vui lòng nhập theo cú pháp `nguon:tên sản phẩm`, ví dụ:\n`hc:tủ lạnh LG`")
        return

    source_key, query = text.split(':', 1)
    source_key = source_key.strip().lower()
    query = query.strip()

    await update.message.reply_text(f"🔍 Đang tìm `{query}` trên {source_key}...")
    result = get_product_info(query, source_key)
    await update.message.reply_text(result, parse_mode="Markdown")

telegram_app = Application.builder().token(BOT_TOKEN).build()
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

@app.route("/", methods=["GET"])
def index():
    return "Bot đang chạy!"

@app.route("/", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), telegram_app.bot)

    async def process():
        await telegram_app.initialize()
        await telegram_app.process_update(update)
        await telegram_app.shutdown()

    asyncio.run(process())
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
