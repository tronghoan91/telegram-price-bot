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

Now tuned around queries like: "Magic AC-381" (also tries variants: AC381 / AC 381 / AC-381).

Supported retailers:
- Nguyễn Kim (nguyenkim.com)
- Điện Máy Chợ Lớn (dienmaycholon.vn)
- Pico (pico.vn)
- HC (hc.com.vn)
- Eco-mart (eco-mart.vn)

How it works:
1) Build multiple query variants to improve recall (AC-381 → AC381, etc.).
2) Use **updated site search endpoints** and robust **site-specific selectors** to capture the FIRST product result link.
3) Open product page → parse price (JSON-LD first, then DOM selectors, then text fallback).
4) Aggregate results across all sites and reply.

Env vars:
- BOT_TOKEN (Telegram bot token)
- DEBUG = 1 (optional: include extra notes)
"""

# =============================
# CONFIG & LOGGING
# =============================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
DEBUG = os.environ.get("DEBUG", "0") == "1"

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

def normalize_query_variants(q: str) -> List[str]:
    q = (q or "").strip()
    base = re.sub(r"\s+", " ", q).strip()
    tokens = base.split()
    variants = {base}
    # Add compact and spaced model variants for tokens like AC-381
    for t in tokens:
        if re.search(r"[A-Za-z]{1,5}-?\d{2,4}", t):
            compact = t.replace("-", "")
            spaced = re.sub(r"([A-Za-z]+)-?(\d+)", r"\1 \2", t)
            variants.add(base.replace(t, compact))
            variants.add(base.replace(t, spaced))
    return list(variants)


def vn_number(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"(\d{1,3}(?:[.\s]\d{3})+|\d+)", text)
    if not m:
        return None
    raw = m.group(1).replace(" ", "")
    digits = re.sub(r"\D", "", raw)
    if not digits or len(digits) < 5:
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
        '[itemprop="price"]', 'meta[itemprop="price"]', '[data-price]',
        'meta[property="product:price:amount"]',
        '.price', '.product-price', '.price-current', '.product__price',
        '.special-price .price', '.price-sale', '.gia-ban', '.current-price',
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


def first_match(soup: BeautifulSoup, selectors: List[str], base: str) -> Optional[str]:
    for css in selectors:
        node = soup.select_one(css)
        if node and node.get("href") and not node.get("href").startswith("#"):
            href = node.get("href")
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

    def search_urls(self, q: str) -> List[str]:
        raise NotImplementedError

    def search_selectors(self) -> List[str]:
        return ["a[href*='/san-pham/']", "a[href*='/product/']", "a[href*='/p/']"]

    def find_product_url(self, q: str) -> Optional[str]:
        for variant in normalize_query_variants(q):
            for url in self.search_urls(variant):
                try:
                    html = http_get(url).text
                    soup = BeautifulSoup(html, "html.parser")
                    link = first_match(soup, self.search_selectors(), self.base_url)
                    if link:
                        if DEBUG:
                            logger.info(f"[{self.site_name}] Hit: {link} (query='{variant}')")
                        return link
                except Exception as e:
                    logger.info(f"[{self.site_name}] search error: {e}")
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
# SITE IMPLEMENTATIONS (UPDATED)
# =============================

class NguyenKimScraper(BaseScraper):
    site_name = "Nguyễn Kim"
    base_url = "https://www.nguyenkim.com"

    def search_urls(self, q: str) -> List[str]:
        return [f"{self.base_url}/search?q={quote_plus(q)}"]

    def search_selectors(self) -> List[str]:
        return [
            "a[href*='/p/']",
            ".product-item a[href]",
            ".item a[href]",
        ]


class DMCLScraper(BaseScraper):
    site_name = "Điện Máy Chợ Lớn"
    base_url = "https://www.dienmaycholon.vn"

    def search_urls(self, q: str) -> List[str]:
        return [f"{self.base_url}/tim-kiem?kwd={quote_plus(q)}"]

    def search_selectors(self) -> List[str]:
        return [
            ".product .b-name a[href]",
            ".product__box-name a[href]",
            "a[href*='/san-pham/']",
        ]


class PicoScraper(BaseScraper):
    site_name = "Pico"
    base_url = "https://pico.vn"

    def search_urls(self, q: str) -> List[str]:
        return [f"{self.base_url}/search?q={quote_plus(q)}"]

    def search_selectors(self) -> List[str]:
        return [
            ".product-name a[href]",
            ".proloop-name a[href]",
            "a[href*='/san-pham/']",
            "a[href$='.html']",
        ]


class HCScraper(BaseScraper):
    site_name = "HC"
    base_url = "https://hc.com.vn"

    def search_urls(self, q: str) -> List[str]:
        return [
            f"{self.base_url}/tim-kiem?q={quote_plus(q)}",
            f"{self.base_url}/ords/search?q={quote_plus(q)}",
        ]

    def search_selectors(self) -> List[str]:
        return [
            ".product-item .product-item-link[href]",
            ".product .product-name a[href]",
            "a[href*='/ords/product/']",
            "a[href*='/san-pham/']",
        ]


class EcomartScraper(BaseScraper):
    site_name = "Eco-mart"
    base_url = "https://eco-mart.vn"

    def search_urls(self, q: str) -> List[str]:
        return [f"{self.base_url}/?s={quote_plus(q)}&post_type=product"]

    def search_selectors(self) -> List[str]:
        return [
            ".woocommerce-LoopProduct-link.woocommerce-loop-product__link[href]",
            ".product-title a[href]",
            "a[href*='/product/']",
            "a[href*='/san-pham/']",
        ]


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
        if r.note and (DEBUG or not r.price):
            lines.append(f"• Ghi chú: {r.note}")
    return "\n".join(lines).strip()


# =============================
# TELEGRAM BOT HANDLERS
# =============================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Gửi tên sản phẩm (VD: 'Magic AC-381' hoặc 'Magic AC381') để mình quét giá trên Nguyễn Kim, Điện Máy Chợ Lớn, Pico, HC và Eco-mart."
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = (update.message.text or "").strip()
    if not q:
        await update.message.reply_text("Vui lòng nhập tên sản phẩm bạn muốn tra giá.")
        return
    await update.message.reply_text(f"🔍 Đang quét giá cho: {q} ...")
    results = scrape_all(q)
    text = format_results(results)
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
    update = Update.de_json(request.get_json(force=True), telegram_app.bot)
    asyncio.run(telegram_app.process_update(update))
    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)
