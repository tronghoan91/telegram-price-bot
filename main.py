from flask import Flask, request
import logging
import requests
import re
from bs4 import BeautifulSoup
from googlesearch import search
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
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
    'eco': 'eco-mart.vn',
    'dienmaycholon': 'dienmaycholon.vn',
    'pico': 'pico.vn'
}

def extract_price_and_promo(soup, domain):
    text = soup.get_text(separator=" ", strip=True)
    price = None
    promo = None

    if "dienmaycholon.vn" in domain:
        price_tag = soup.select_one(".price, .product-price, .box-price")
        if price_tag:
            price = price_tag.get_text(strip=True)
    elif "eco-mart.vn" in domain:
        price_tag = soup.select_one("span.price, div.price, p.price")
        if price_tag:
            price = price_tag.get_text(strip=True)
    elif "nguyenkim.com" in domain:
        price_tag = soup.find("div", class_=re.compile("price|product-price"))
        if price_tag:
            price = price_tag.get_text(strip=True)
    elif "pico.vn" in domain:
        price_tag = soup.select_one(".product-detail__price-current, .product-price, .current-price")
        if price_tag:
            price = price_tag.get_text(strip=True)

    if "hc.com.vn" in domain or not price:
        match = re.findall(r"\d[\d\.]{3,}(?:₫|đ| VNĐ| vnđ|)", text)
        price = match[0] if match else price

    match = re.findall(r"(tặng|giảm|ưu đãi|quà tặng)[^.:\\n]{0,100}", text, re.IGNORECASE)
    promo = match[0] if match else None

    return price, promo

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

        price, promo = extract_price_and_promo(soup, domain)

        msg = f"✅ <b>{title}</b>"
        if price:
            msg += f"\n💰 <b>Giá:</b> {price}"
        else:
            msg += "\n❌ Không tìm thấy giá rõ ràng."

        if promo:
            msg += f"\n🎁 <b>KM:</b> {promo}"
        msg += f'\n🔗 <a href="{url}">Xem sản phẩm</a>'
        return msg

    except Exception as e:
        return f"❌ Lỗi: {str(e)}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Nhập theo cú pháp <code>nguon:tên sản phẩm</code>, ví dụ:\n"
        "<code>hc:tủ lạnh LG</code>, <code>pico:quạt điều hòa</code>",
        parse_mode="HTML"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if ':' not in text:
        await update.message.reply_text("❗ Vui lòng nhập theo cú pháp <code>nguon:tên sản phẩm</code>", parse_mode="HTML")
        return

    source_key, query = text.split(':', 1)
    source_key = source_key.strip().lower()
    query = query.strip()

    await update.message.reply_text(f"🔍 Đang tìm <b>{query}</b> trên <b>{source_key}</b>...", parse_mode="HTML")
    result = get_product_info(query, source_key)
    await update.message.reply_text(result, parse_mode="HTML")

telegram_app = Application.builder().token(BOT_TOKEN).build()
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

@app.route("/", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), telegram_app.bot)

    async def process():
        await telegram_app.initialize()
        await telegram_app.process_update(update)

    asyncio.run(process())
    return "OK", 200

@app.route("/", methods=["GET"])
def alive():
    return "Bot is alive!"

if __name__ == "__main__":
    telegram_app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        url_path=BOT_TOKEN,
        webhook_url=f"https://https://telegram-bot-zfdp.onrender.com/{BOT_TOKEN}"  # THAY LINK NÀY
    )
