import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.constants import ParseMode
import openpyxl

TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def escape_markdown(text):
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return ''.join(['\\' + char if char in escape_chars else char for char in text])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Xin chào! Gửi file Excel chứa danh sách sản phẩm để mình quét giá nhé.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = update.message.document
    if file.mime_type != 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
        await update.message.reply_text("Vui lòng gửi file Excel định dạng .xlsx nhé.")
        return

    file_path = await file.get_file()
    file_name = f"/tmp/{file.file_name}"
    await file_path.download_to_drive(file_name)

    workbook = openpyxl.load_workbook(file_name)
    sheet = workbook.active

    results = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        product_name = row[0]
        if product_name:
            link = f"https://www.google.com/search?q={product_name.replace(' ', '+')}+site%3Anguyenkim.com"
            text = f"*{escape_markdown(product_name)}*\n[🔗 Mua tại Nguyễn Kim]({link})"
            results.append(text)

    for result in results:
        await update.message.reply_text(result, parse_mode=ParseMode.MARKDOWN_V2)

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    app.run_polling()
