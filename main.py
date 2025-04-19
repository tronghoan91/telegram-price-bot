import os
import asyncio
from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters

TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Ví dụ: https://<tên-app>.onrender.com/webhook

# Tạo app Flask
app = Flask(__name__)

# Tạo bot Telegram async
telegram_app = Application.builder().token(TOKEN).build()


# --- HANDLERS ---
async def start(update: Update, context):
    await update.message.reply_text("Bot đã sẵn sàng quét giá!")


async def echo(update: Update, context):
    await update.message.reply_text(f"Bạn vừa gửi: {update.message.text}")


# --- Đăng ký handler ---
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))


# --- ROUTE nhận Webhook ---
@app.route('/webhook', methods=['POST'])
async def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return 'OK'


# --- Trang chính để test ---
@app.route('/')
def home():
    return 'Bot is running!'


# --- Thiết lập Webhook và chạy app ---
if __name__ == '__main__':
    bot = Bot(TOKEN)
    asyncio.run(bot.set_webhook(WEBHOOK_URL))

    from hypercorn.asyncio import serve
    from hypercorn.config import Config

    config = Config()
    config.bind = ["0.0.0.0:10000"]  # Render sẽ chạy cổng này
    asyncio.run(serve(app, config))
