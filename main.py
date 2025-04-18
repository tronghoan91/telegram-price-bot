
import re
from bs4 import BeautifulSoup

SUPPORTED_SITES = {
    'nguyenkim': 'nguyenkim.com',
    'hc': 'hc.com.vn',
    'eco': 'eco-mart.vn',
    'dienmaycholon': 'dienmaycholon.vn',
    'pico': 'pico.vn'
}

def extract_price_and_promo(domain, soup):
    price = ""
    if "hc.com.vn" in domain:
        price_tag = soup.find("span", class_="product-detail__price--final")
        if price_tag:
            price = price_tag.get_text(strip=True)

    elif "eco-mart.vn" in domain:
        price_tag = soup.find("span", class_="woocommerce-Price-amount")
        if price_tag:
            price = price_tag.get_text(strip=True)

    elif "dienmaycholon.vn" in domain:
        price_tag = soup.find("span", class_="price")
        if price_tag:
            price = price_tag.get_text(strip=True)

    elif "nguyenkim.com" in domain:
        price_tag = soup.find("div", class_=re.compile("price|product-price"))
        if price_tag:
            price = price_tag.get_text(strip=True)

    elif "pico.vn" in domain:
        price_tag = soup.select_one("span.product-detail-price, .price, .product-price")
        if price_tag:
            price = price_tag.get_text(strip=True)

    return price
