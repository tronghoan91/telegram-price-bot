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
    'eco': 'eco-mart.vn',
    'dienmaycholon': 'dienmaycholon.vn',
    'pico': 'pico.vn'
}

def extract_price_and_promo(soup, domain):
    text = soup.get_text(separator=" ", strip=True)
    price = None
    promo = None

    if "pico.vn" in domain:
        price_tag = (
            soup.select_one(".product-detail-price ins") or
            soup.select_one(".price-final") or
            soup.select_one(".price span") or
            soup.select_one(".product-price ins") or
            soup.select_one(".product-price")
        )
        if price_tag:
            raw_price = price_tag.get_text(strip=True)
            price_match = re.search(r"\d[\d\.\,]{4,}", raw_price)
            if price_match:
                price = price_match.group()

    elif "hc.com.vn" in domain:
        match = re.findall(r"\d{1,3}(?:[.,]\d{3})+(?:₫|đ| VNĐ| vnđ)?", text)
        price = match[0] if match else None

    elif "dienmaycholon.vn" in domain:
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
            raw_price = price_tag.get_text(strip=True)
            price_match = re.search(r"\d[\d\.\,]{4,}", raw_price)
            if price_match:
                price = price_match.group()

    # Tìm khuyến mãi
    match = re.findall(r"(tặng|giảm|ưu đãi|quà tặng)[^.:\\n]{0,100}", text, re.IGNORECASE)
    promo = match[0] if match else None

    # Làm sạch định dạng giá
    if price:
        price = re.sub(r"[^\d]", "", price)
        if price:
            price = f"{int(price):,}đ".replace(",", ".")

    return price, promo.strip() if promo else None

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

        if "pico.vn" in domain:
            title_tag = soup.find("h1", class_="product-detail-name")
        elif "hc.com.vn" in domain:
            title_tag = soup.find("h1", class_="product-title")
        else:
            title_tag = soup.find("h1")

        title = title_tag.text.strip() if title_tag else query
        price, promo = extract_price_and_promo(soup, domain)

        msg = f"<b>✅ {title}</b>"
        if price:
            msg += f"\n💰 <b>Giá:</b> {price}"
        else:
            if "hc.com.vn" in domain:
                msg += "\n❗ Không thể trích xuất giá từ HC vì giá hiển thị bằng JavaScript."
            else:
                msg += "\n❌ Không tìm thấy giá rõ ràng."

        if promo:
            msg += f"\n\n🎁 <b>KM:</b> {promo}"
        msg += f'\n🔗 <a href="{url}">Xem sản phẩm</a>'
        return msg

    except Exception as e:
        return f"❌ Lỗi: {str(e)}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Gửi tên sản phẩm hoặc nhập theo cú pháp <code>nguon:tên sản phẩm</code>\n"
        "Ví dụ: <code>hc:tủ lạnh LG</code> hoặc <b>Magic A-030</b> để tìm tất cả các sàn.",
        parse_mode="HTML"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if ':' in text:
        source_key, query = text.split(':', 1)
        source_key = source_key.strip().lower()
        query = query.strip()
        await update.message.reply_text(f"🔍 Đang tìm <b>{query}</b> trên <b>{source_key}</b>...", parse_mode="HTML")
        result = get_product_info(query, source_key)
        await update.message.reply_text(result, parse_mode="HTML")
    else:
        query = text
        await update.message.reply_text(f"🔍 Đang tìm <b>{query}</b> trên tất cả các sàn...", parse_mode="HTML")
        for source_key in SUPPORTED_SITES:
            try:
                result = get_product_info(query, source_key)
                await update.message.reply_text(f"<b>🛍️ {source_key.upper()}</b>\n{result}", parse_mode="HTML")
            except Exception as e:
                await update.message.reply_text(f"❌ {source_key.upper()}: Lỗi khi tìm sản phẩm\n{str(e)}", parse_mode="HTML")

telegram_app = Application.builder().token(BOT_TOKEN).build()
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

@app.route("/", methods=["GET"])
def index():
    return "Bot is running!"

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
