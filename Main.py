import os
import re
import json
import time
import logging
from dataclasses import dataclass
from typing import Optional, List
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup
from flask import Flask, request

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import asyncio

"""
MAIN.PY — Multi-retailer price scraper bot (VN electronics chains)

Supported retailers (initial):
- Nguyễn Kim (nguyenkim.com)
- Điện Máy Chợ Lớn (dienmaycholon.vn)
- Pico (pico.vn)
- HC (hc.com.vn)
- Eco-mart (eco-mart.vn)

Bot usage:
- Send any product name (e.g., "Tivi LG 65UQ7550") → bot replies aggregated prices across retailers.

Environment:
- BOT_TOKEN (Telegram bot token) must be set in environment variables.

Run (local dev):
- python main.py

Deploy behind webhook: point Telegram webhook to your server's URL that handles POST "/".
"""

# =============================
# CONFIG & LOGGING
# =============================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("multi-price-bot")

# =============================
# HTTP SESSION & HELPERS
# =============================

def build_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    })
    return s

SESSION = build_session()


def http_get(url: str, timeout=12, retries=2, backoff=1.5) -> requests.Response:
    last_err = None
    for i in range(retries + 1):
        try:
            resp = SESSION.get(url, timeout=timeout)
            if resp.status_code in (200, 403, 503):  # still parse to catch JSON-LD
                return resp
            last_err = Exception(f"HTTP {resp.status_code} on {url}")
        except Exception as e:
            last_err = e
        if i < retries:
            time.sleep(backoff ** (i + 1))
    raise last_err or Exception("Unknown HTTP error")


# =============================
# NORMALIZATION & PARSERS
# =============================

def vn_number(text: Optional[str]) -> Optional[str]:
    """Extract the first plausible VND price and normalize with dot thousand sep."""
    if not text:
        return None
    m = re.search(r"(\d{1,3}(?:[.\s]\d{3})+|\d+)", text)
    if not m:
        return None
    raw = m.group(1).replace(" ", "")
    digits = re.sub(r"\D", "", raw)
    if not digits or len(digits) < 5:  # ignore tiny numbers (< 10k)
        return None
    parts = []
    while digits:
        parts.append(digits[-3:])
        digits = digits[:-3]
    return ".".join(reversed(parts)) + " ₫"


def parse_jsonld_price(soup: BeautifulSoup) -> Optional[str]:
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text(strip=True) or ""
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        def scan(obj):
            if isinstance(obj, dict):
                offers = obj.get("offers")
                if isinstance(offers, dict):
                    price = offers.get("price") or (
                        isinstance(offers.get("priceSpecification"), dict)
                        and offers["priceSpecification"].get("price")
                    )
                    if price:
                        return vn_number(str(price))
                for v in obj.values():
                    found = scan(v)
                    if found:
                        return found
            elif isinstance(obj, list):
                for it in obj:
                    found = scan(it)
                    if found:
                        return found
            return None

        price = scan(data)
        if price:
            return price
    return None


def parse_dom_price(soup: BeautifulSoup) -> Optional[str]:
    selectors = [
        '[itemprop="price"]',
        'meta[itemprop="price"]',
        '[data-price]',
        'meta[property="product:price:amount"]',
        '.price', '.product-price', '.price-current', '.product__price',
        '[class*="price"]', '[id*="price"]', 'ins .amount', '.amount', 'bdi'
    ]
    candidates = []
    for css in selectors:
        for node in soup.select(css):
            val = node.get("content") or node.get("data-price") or node.get_text(" ", strip=True)
            p = vn_number(val)
            if p:
                candidates.append(p)
    if candidates:
        unique = []
        for c in candidates:
            if c not in unique:
                unique.append(c)
        return unique[0]
    return vn_number(soup.get_text(" ", strip=True))


def pick_first_product_link_from_search(html: str, base: str, hints: List[str]) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    patterns = [f"a[href*='{h}']" for h in hints]
    link_tags = soup.select(",".join(patterns))
    for a in link_tags:
        href = a.get("href")
        if not href or href.startswith("#"):
            continue
        return href if href.startswith("http") else urljoin(base, href)
    return None


# =============================
# SCRAPER ABSTRACTION
# =============================

@dataclass
class PriceResult:
    site: str
    title: Optional[str]
    price: Optional[str]
    url: Optional[str]
    note: Optional[str] = None


class BaseScraper:
    site_name: str = "base"
    base_url: str = ""

    def search_url(self, q: str) -> str:
        raise NotImplementedError

    def product_hints(self) -> List[str]:
        return ["/product/", "/san-pham/", "/p/"]

    def find_product_url(self, q: str) -> Optional[str]:
        url = self.search_url(q)
        try:
            html = http_get(url).text
            link = pick_first_product_link_from_search(html, self.base_url, self.product_hints())
            return link
        except Exception:
            return None

    def parse_product(self, url: str) -> PriceResult:
        resp = http_get(url)
        soup = BeautifulSoup(resp.text, "html.parser")
        title = None
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)
        if not title and soup.title and soup.title.string:
            title = soup.title.string.strip()
        price = parse_jsonld_price(soup) or parse_dom_price(soup)
        note = None
        if not price:
            note = "Không tìm thấy giá rõ ràng (trang có thể render bằng JS)."
        return PriceResult(self.site_name, title, price, url, note)

    def get_price(self, q: str) -> PriceResult:
        product_url = self.find_product_url(q)
        if not product_url:
            return PriceResult(self.site_name, None, None, None, note="Không tìm thấy link sản phẩm từ trang tìm kiếm.")
        return self.parse_product(product_url)


# =============================
# SITE IMPLEMENTATIONS
# =============================

class NguyenKimScraper(BaseScraper):
    site_name = "Nguyễn Kim"
    base_url = "https://www.nguyenkim.com"

    def search_url(self, q: str) -> str:
        return f"{self.base_url}/search?q={quote_plus(q)}"

    def product_hints(self) -> List[str]:
        return ["/p/", "/san-pham/", ".html"]


class DMCLScraper(BaseScraper):
    site_name = "Điện Máy Chợ Lớn"
    base_url = "https://www.dienmaycholon.vn"

    def search_url(self, q: str) -> str:
        return f"{self.base_url}/tim-kiem?kwd={quote_plus(q)}"

    def product_hints(self) -> List[str]:
        return ["/san-pham/"]


class PicoScraper(BaseScraper):
    site_name = "Pico"
    base_url = "https://pico.vn"

    def search_url(self, q: str) -> str:
        return f"{self.base_url}/search?q={quote_plus(q)}"

    def product_hints(self) -> List[str]:
        return ["/san-pham/", ".html"]


class HCScraper(BaseScraper):
    site_name = "HC"
    base_url = "https://hc.com.vn"

    def search_url(self, q: str) -> str:
        # HC uses /ords/ for search on many deployments
        return f"{self.base_url}/ords/search?q={quote_plus(q)}"

    def product_hints(self) -> List[str]:
        return ["/ords/product/"]


class EcomartScraper(BaseScraper):
    site_name = "Eco-mart"
    base_url = "https://eco-mart.vn"

    def search_url(self, q: str) -> str:
        return f"{self.base_url}/?s={quote_plus(q)}&post_type=product"

    def product_hints(self) -> List[str]:
        return ["/product/", "/san-pham/"]


SCRAPERS: List[BaseScraper] = [
    NguyenKimScraper(),
    DMCLScraper(),
    PicoScraper(),
    HCScraper(),
    EcomartScraper(),
]


def scrape_all(product_name: str) -> List[PriceResult]:
    results: List[PriceResult] = []
    for s in SCRAPERS:
        try:
            results.append(s.get_price(product_name))
        except Exception as e:
            results.append(PriceResult(site=s.site_name, title=None, price=None, url=None, note=f"Lỗi: {e}"))
    return results


def format_results(results: List[PriceResult]) -> str:
    lines = ["🔎 Kết quả giá tham khảo:"]
    for r in results:
        lines.append(f"\n🏬 {r.site}")
        if r.title:
            lines.append(f"• Sản phẩm: {r.title}")
        if r.price:
            lines.append(f"• Giá: {r.price}")
        if r.url:
            lines.append(f"• Link: {r.url}")
        if r.note:
            lines.append(f"• Ghi chú: {r.note}")
    return "\n".join(lines).strip()


# =============================
# TELEGRAM BOT HANDLERS
# =============================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Gửi tên sản phẩm (VD: 'Tivi LG 65UQ7550') để mình quét giá trên Nguyễn Kim, Điện Máy Chợ Lớn, Pico, HC và Eco-mart."
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = (update.message.text or "").strip()
    if not q:
        await update.message.reply_text("Vui lòng nhập tên sản phẩm bạn muốn tra giá.")
        return
    await update.message.reply_text(f"🔍 Đang quét giá cho: {q} ...")
    results = scrape_all(q)
    text = format_results(results)
    # Telegram message limit safeguard
    if len(text) > 3800:
        text = text[:3800] + "\n... (rút gọn)"
    await update.message.reply_text(text, disable_web_page_preview=True)


def build_bot_app():
    if not BOT_TOKEN:
        logger.warning("BOT_TOKEN is empty! Set BOT_TOKEN in environment variables.")
    app = ApplicationBuilder().token(BOT_TOKEN or "invalid").build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app


telegram_app = build_bot_app()

# =============================
# FLASK APP (WEBHOOK ENTRY)
# =============================
flask_app = Flask(__name__)

@flask_app.get("/")
def index():
    return "OK: multi-price-bot is running", 200


@flask_app.post("/")
def webhook():
    # For compatibility with many existing setups using python-telegram-bot v20
    update = Update.de_json(request.get_json(force=True), telegram_app.bot)
    asyncio.run(telegram_app.process_update(update))
    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)
