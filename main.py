import logging
import requests
import re
from bs4 import BeautifulSoup
from googlesearch import search
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from flask import Flask, request
import os
import json

# ==== BOT TOKEN ====
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7062147168:AAGHaOBKLIpvEqFPJdvs7uLjr81zWzjWlIk")

# ==== FLASK APP ====
app = Flask(__name__)

# ==== LOGGING ====
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ==== HÀM QUÉT GIÁ TỪ NGUYỄN KIM ====
def get_nguyenkim_price(product_name):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }

    query = f"{product_name} site:nguyenkim.com"
    urls = list(search(query, num_results=5))
    product_url = next((u for u in urls if "nguyenkim.com" in u), None)

    if not product_url:
        return "❌ Không tìm thấy sản phẩm trên Nguyễn Kim."

    try:
        resp = requests.get(product_url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")

        title_tag = soup.find("h1")
        title = title_tag.text.strip() if title_tag else product_name

        text = soup.get_text(separator=" ", strip=True)
        matches = re.findall(r"\d[\d\.]+(?:₫|đ| VNĐ| vnđ)", text)

        if matches:
            price = matches[0]
            return f"✅ {title}\n💰 Giá: {price}\n🔗 {product_url}"
        else:
            return f"✅ {title}\n❌ Không tìm thấy giá rõ ràng.\n🔗 {product_url}"

    except Exception as e:
        return f"❌ Lỗi khi lấy dữ liệu từ Nguyễn Kim: {e}"

# ==== LỆNH /start ====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Gửi tên sản phẩm để mình quét giá từ Nguyễn Kim cho bạn!")

# ==== XỬ LÝ NỘI DUNG CHAT ====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    product_name = update.message.text.strip()
    await update.message.reply_text(f"🔍 Đang tìm giá cho: {product_name} ...")
    result = get_nguyenkim_price(product_name)
    await update.message.reply_text(result)

# ==== TẠO APP TELEGRAM ====
telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# ==== ROUTE KIỂM TRA ====
@app.route("/", methods=["GET"])
def index():
    return "Bot đang hoạt động!", 200

# ==== ROUTE WEBHOOK TELEGRAM ====
@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, telegram_app.bot)
    telegram_app.create_task(telegram_app.process_update(update))
    return "OK", 200

# ==== CHẠY FLASK ====
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
