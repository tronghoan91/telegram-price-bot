
import logging
import os
import re
import asyncio
from bs4 import BeautifulSoup
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = "7062147168:AAGHaOBKLIpvEqFPJdvs7uLjr81zWzjWlIk"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Gửi tên sản phẩm để bắt đầu quét giá từ Nguyễn Kim và Pico nhé!")

def clean_text(text):
    return re.sub(r"\s+", " ", text).strip()

def search_google(query, site):
    from urllib.parse import quote_plus
    search_url = f"https://www.google.com/search?q={quote_plus(query)}+site:{site}"
    response = requests.get(search_url, headers=headers)
    soup = BeautifulSoup(response.text, "html.parser")
    for link in soup.find_all("a"):
        href = link.get("href")
        if href and "/url?q=" in href:
            real_url = href.split("/url?q=")[1].split("&")[0]
            if site in real_url:
                return real_url
    return None

def get_nguyenkim_data(url):
    try:
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")

        title = soup.find("h1").get_text(strip=True)
        price_block = soup.select_one(".product-info__price .price-value")
        price = price_block.get_text(strip=True) if price_block else "Không rõ"

        old_price_block = soup.select_one(".product-info__price .price-old")
        discount = old_price_block.get_text(strip=True) if old_price_block else ""

        promo_block = soup.select_one(".product-promotion__content")
        promo = clean_text(promo_block.get_text()) if promo_block else ""

        return {
            "name": title,
            "price": price,
            "discount": discount,
            "promo": promo,
            "url": url
        }
    except Exception as e:
        return None

def get_pico_data(url):
    try:
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")

        title = soup.find("h1")
        title = title.get_text(strip=True) if title else "Không rõ tên"

        price = soup.find("span", class_="price")
        price = price.get_text(strip=True) if price else "Không rõ giá"

        promo_block = soup.find("div", class_="product-promotion-content")
        promo = clean_text(promo_block.get_text()) if promo_block else ""

        return {
            "name": title,
            "price": price,
            "promo": promo,
            "url": url
        }
    except Exception as e:
        return None

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Nhập tên sản phẩm sau lệnh /search VD: /search AC-305")
        return

    await update.message.reply_text(f"🔍 Đang tìm *{query}* trên nguyenkim.com...")
    nk_url = search_google(query, "nguyenkim.com")
    if nk_url:
        data = get_nguyenkim_data(nk_url)
        if data:
            msg = f"✅ *{data['name']}*\n💰 Giá: {data['price']}"
            if data['discount']:
                msg += f" (Giá gốc: {data['discount']})"
            if data['promo']:
                msg += f"\n🎁 KM: {data['promo']}"
            msg += f"\n🔗 [Xem sản phẩm]({data['url']})"
            await update.message.reply_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Không tìm thấy sản phẩm trên Nguyễn Kim.")

    await update.message.reply_text(f"🔍 Đang tìm *{query}* trên pico.vn...")
    pico_url = search_google(query, "pico.vn")
    if pico_url:
        data = get_pico_data(pico_url)
        if data:
            msg = f"✅ *{data['name']}*\n💰 Giá: {data['price']}"
            if data['promo']:
                msg += f"\n🎁 KM: {data['promo']}"
            msg += f"\n🔗 [Xem sản phẩm]({data['url']})"
            await update.message.reply_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Không tìm thấy sản phẩm trên Pico.")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search))
    print("Bot is running...")
    app.run_polling()
