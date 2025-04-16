
import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.constants import ParseMode

# Hàm escape markdown V2 an toàn
def escape_markdown(text: str) -> str:
    escape_chars = r"_*[]()~`>#+-=|{}.!"  # Các ký tự MarkdownV2 cần escape
    return ''.join(['\' + char if char in escape_chars else char for char in text])

# Hàm phản hồi lệnh /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = "Xin chào! Tôi là bot hỗ trợ quét giá sản phẩm."
    await context.bot.send_message(chat_id=update.effective_chat.id, text=escape_markdown(message), parse_mode=ParseMode.MARKDOWN_V2)

# Hàm phản hồi lệnh /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = "Gửi tôi tên sản phẩm hoặc file Excel, tôi sẽ trả về bảng giá từ các website."
    await context.bot.send_message(chat_id=update.effective_chat.id, text=escape_markdown(message), parse_mode=ParseMode.MARKDOWN_V2)

# Cấu hình logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Tạo ứng dụng bot từ token
TOKEN = os.getenv("BOT_TOKEN")
app = ApplicationBuilder().token(TOKEN).build()

# Gán lệnh vào handler
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_command))

# Khởi chạy bot
if __name__ == '__main__':
    app.run_polling()
