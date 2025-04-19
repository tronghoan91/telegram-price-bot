import os
import logging
import requests
import re
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from flask import Flask, request
import asyncio

# --- Cấu hình ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
app = Flask(__name__)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- Các nguồn hỗ trợ ---
SUPPORTED_SITES = {
    'nguyenkim': 'nguyenkim.com',
    'hc': 'hc.com.vn',
    'eco': 'eco-mart.vn',
    'cholon': 'dienmaycholon.vn',
    'pico': 'pico.vn',
    'shopee': 'shopee.vn',
    'mediamart': 'mediamart.vn',
    'dmx': 'dienmayxanh.com'
}

# --- Hàm trích xuất giá & khuyến mãi ---
def extract_price_and_promo(soup, domain):
    text = soup.get_text(separator=" ", strip=True)
    price = None
    promo = None

    # CỐ ĐỊNH vài site
    if "nguyenkim.com" in domain:
        tag = soup.select_one("div.product-price, div.price, span.price")
        price = tag.get_text(strip=True) if tag else None
    elif "eco-mart.vn" in domain or "mediamart.vn" in domain:
        tag = soup.select_one("span.price, .woocommerce-Price-amount")
        price = tag.get_text(strip=True) if tag else None
    elif "dienmaycholon.vn" in domain or "dienmayxanh.com" in domain:
        tag = soup.select_one(".price, .product-price")
        price = tag.get_text(strip=True) if tag else None
    elif "pico.vn" in domain:
        tag = soup.select_one(".product-detail-price, .price, .product-price")
        price = tag.get_text(strip=True) if tag else None
    # Shopee thường hiển thị bằng JS, dùng regex fallback
    # Các site khác dùng chung regex
    if not price:
        m = re.findall(r"\d[\d\.]{3,}(?:₫|đ| VNĐ| vnđ)", text)
        price = m[0] if m else None

    # Khuyến mãi
    m2 = re.findall(r"(tặng|giảm|ưu đãi|quà tặng)[^.:\n]{0,100}", text, re.IGNORECASE)
    promo = m2[0].strip() if m2 else None

    # Tinh chỉnh lại
    if price:
        mp = re.match(r'(\d[\d\.]+[đ₫])\s*(.*)', price)
        if mp:
            price = mp.group(1)
            extra = mp.group(2).strip()
            if extra:
                promo = (promo or "") + " " + extra

    return price, promo

# --- Lấy thông tin sản phẩm ---
def get_product_info(query, source_key):
    domain = SUPPORTED_SITES.get(source_key)
    if not domain:
        return "❌ Nguồn không được hỗ trợ."

    # Google search 5 kết quả
    try:
        from googlesearch import search
        urls = list(search(f"{query} site:{domain}", num_results=5))
    except ImportError:
        urls = []
    url = next((u for u in urls if domain in u), None)
    if not url:
        return f"❌ Không tìm thấy trên {domain}"

    # Request & parse
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=10)
    soup = BeautifulSoup(r.text, "html.parser")

    # Tên sản phẩm: h1 hoặc og:title hoặc query
    tag = soup.find("h1")
    if tag:
        title = tag.get_text(strip=True)
    else:
        og = soup.find("meta", property="og:title")
        title = og["content"].strip() if og and og.get("content") else query

    # Giá & KM
    price, promo = extract_price_and_promo(soup, domain)

    # Xây message
    msg = f"✅ *{title}*"
    if price:
        msg += f"\n💰 *Giá:* {price}"
    else:
        msg += "\n❌ Không xác định được giá."
    msg += f"\n🎁 *KM:* {promo or 'Không rõ'}"
    msg += f'\n🔗 [Xem sản phẩm]({url})'

    return msg

# --- Handler /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Gửi tin nhắn theo cú pháp `nguon:tên sản phẩm`, ví dụ:\n"
        "`nguyenkim:AC-305`, `hc:quạt hơi nước`, `pico:Magic A-030`",
        parse_mode="Markdown"
    )

# --- Handler tin nhắn ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if ':' not in txt:
        return await update.message.reply_text(
            "❗ Vui lòng nhập `nguon:tên sản phẩm`",
            parse_mode="Markdown"
        )
    key, query = txt.split(':', 1)
    key, query = key.lower().strip(), query.strip()
    await update.message.reply_text(f"🔍 Đang tìm *{query}* trên *{key}*...", parse_mode="Markdown")
    res = get_product_info(query, key)
    await update.message.reply_text(res, parse_mode="Markdown", disable_web_page_preview=True)

# --- Khởi tạo Telegram app ---
telegram_app = Application.builder().token(BOT_TOKEN).build()
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# --- Flask routes để Gunicorn gọi ---
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

# --- Entrypoint cho local/testing ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
