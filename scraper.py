"""
Greek Supermarket Price Scraper
Υποστηρίζει: AB Vassilopoulos, Sklavenitis, Lidl GR, My Market
"""

import requests
import json
import time
import random
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional
import sqlite3
import os

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Product:
    chain: str
    chain_sku: str
    name: str
    price: float
    price_per_unit: Optional[float]
    unit: Optional[str]
    brand: Optional[str]
    ean: Optional[str]
    image_url: Optional[str]
    is_offer: bool
    offer_original_price: Optional[float]
    category: Optional[str]
    url: Optional[str]
    scraped_at: str = ""

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.utcnow().isoformat()


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "el-GR,el;q=0.9,en;q=0.8",
}


def get(url: str, params: dict = None, headers: dict = None, retries=3) -> requests.Response:
    """GET με retry και random delay."""
    h = {**HEADERS, **(headers or {})}
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, headers=h, timeout=15)
            resp.raise_for_status()
            # Polite delay: 1-3 δευτερόλεπτα
            time.sleep(random.uniform(1.0, 3.0))
            return resp
        except requests.RequestException as e:
            print(f"[WARN] Attempt {attempt+1}/{retries} failed for {url}: {e}")
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts")


# ---------------------------------------------------------------------------
# AB Vassilopoulos scraper
# AB χρησιμοποιεί SAP Hybris — υπάρχει JSON API
# ---------------------------------------------------------------------------

class ABScraper:
    BASE = "https://www.ab.gr"
    API  = "https://www.ab.gr/api/2.0/gr/el/products/search"

    CATEGORIES = [
        "φρέσκα-γαλακτοκομικά-αυγά",
        "αλλαντικά-τυροκομικά",
        "ψωμί-αρτοσκευάσματα",
        "κατεψυγμένα",
        "ροφήματα",
        "καφές-ροφήματα",
        "κονσέρβες-είδη-παντοπωλείου",
        "είδη-καθαρισμού",
        "προσωπική-φροντίδα",
    ]

    def scrape_category(self, category_slug: str, max_pages: int = 5) -> list[Product]:
        products = []
        for page in range(max_pages):
            try:
                resp = get(
                    self.API,
                    params={
                        "query": f":relevance:allCategories:{category_slug}",
                        "currentPage": page,
                        "pageSize": 48,
                        "fields": "FULL",
                    },
                    headers={"Referer": f"{self.BASE}/category/{category_slug}"}
                )
                data = resp.json()
                items = data.get("products", [])
                if not items:
                    break

                for item in items:
                    p = self._parse(item, category_slug)
                    if p:
                        products.append(p)

                total_pages = data.get("pagination", {}).get("totalPages", 1)
                if page >= total_pages - 1:
                    break

            except Exception as e:
                print(f"[AB] Error on category={category_slug} page={page}: {e}")
                break

        return products

    def _parse(self, item: dict, category: str) -> Optional[Product]:
        try:
            price_data = item.get("price", {})
            price = float(price_data.get("value", 0))
            if price <= 0:
                return None

            # Έλεγχος για προσφορά
            was_price = None
            is_offer = False
            if item.get("potentialPromotions"):
                promo = item["potentialPromotions"][0]
                if promo.get("price"):
                    was_price = price
                    price = float(promo["price"].get("value", price))
                    is_offer = True

            # Τιμή ανά μονάδα
            ppu = None
            unit = None
            if item.get("pricePerUnit"):
                ppu_str = item["pricePerUnit"].get("value")
                unit = item["pricePerUnit"].get("unit")
                if ppu_str:
                    ppu = float(ppu_str)

            return Product(
                chain="ab",
                chain_sku=item.get("code", ""),
                name=item.get("name", ""),
                price=price,
                price_per_unit=ppu,
                unit=unit,
                brand=item.get("brand", {}).get("name") if item.get("brand") else None,
                ean=item.get("ean"),
                image_url=(item.get("images") or [{}])[0].get("url"),
                is_offer=is_offer,
                offer_original_price=was_price,
                category=category,
                url=f"{self.BASE}/p/{item.get('code', '')}",
            )
        except Exception as e:
            print(f"[AB] Parse error: {e}")
            return None

    def scrape_all(self) -> list[Product]:
        all_products = []
        for cat in self.CATEGORIES:
            print(f"[AB] Scraping category: {cat}")
            products = self.scrape_category(cat)
            print(f"[AB]   → {len(products)} products")
            all_products.extend(products)
        return all_products


# ---------------------------------------------------------------------------
# Sklavenitis scraper
# Χρησιμοποιεί Magento 2 — JSON API διαθέσιμο
# ---------------------------------------------------------------------------

class SklavenitissScraper:
    BASE = "https://www.sklavenitis.gr"
    API  = "https://www.sklavenitis.gr/api/catalog/products"

    CATEGORIES = [
        "galaktokomika-avga",
        "allantika",
        "psiomi",
        "katepsygmena",
        "anapsyktika-xymoi",
        "kafes-rofihmata",
        "konserves-pantopoleio",
        "katharistika",
        "prosopikhfrontida",
    ]

    def scrape_category(self, category_slug: str, max_pages: int = 5) -> list[Product]:
        products = []
        for page in range(1, max_pages + 1):
            try:
                resp = get(
                    self.API,
                    params={
                        "category": category_slug,
                        "page": page,
                        "per_page": 48,
                    },
                    headers={"Referer": f"{self.BASE}/{category_slug}/"}
                )
                data = resp.json()
                items = data.get("items", data.get("products", []))
                if not items:
                    break

                for item in items:
                    p = self._parse(item, category_slug)
                    if p:
                        products.append(p)

                if len(items) < 48:
                    break

            except Exception as e:
                print(f"[Sklavenitis] Error on category={category_slug} page={page}: {e}")
                break

        return products

    def _parse(self, item: dict, category: str) -> Optional[Product]:
        try:
            price = float(item.get("price", item.get("final_price", 0)))
            if price <= 0:
                return None

            original = item.get("original_price") or item.get("regular_price")
            is_offer = original is not None and float(original) > price

            return Product(
                chain="sklavenitis",
                chain_sku=str(item.get("id", item.get("sku", ""))),
                name=item.get("name", ""),
                price=price,
                price_per_unit=item.get("price_per_unit"),
                unit=item.get("unit"),
                brand=item.get("brand"),
                ean=item.get("ean") or item.get("barcode"),
                image_url=item.get("image") or item.get("thumbnail"),
                is_offer=is_offer,
                offer_original_price=float(original) if is_offer else None,
                category=category,
                url=f"{self.BASE}/{item.get('url_key', '')}",
            )
        except Exception as e:
            print(f"[Sklavenitis] Parse error: {e}")
            return None

    def scrape_all(self) -> list[Product]:
        all_products = []
        for cat in self.CATEGORIES:
            print(f"[Sklavenitis] Scraping category: {cat}")
            products = self.scrape_category(cat)
            print(f"[Sklavenitis]   → {len(products)} products")
            all_products.extend(products)
        return all_products


# ---------------------------------------------------------------------------
# Lidl GR scraper
# Lidl έχει public JSON feed για τα eshop προϊόντα τους
# ---------------------------------------------------------------------------

class LidlScraper:
    API = "https://www.lidl.gr/api/product-search/v2/search"

    CATEGORIES = [
        "Γαλακτοκομικά",
        "Κρεατικά & Αλλαντικά",
        "Ψωμί & Αρτοσκευάσματα",
        "Κατεψυγμένα",
        "Ροφήματα",
        "Καφές & Τσάι",
        "Κονσέρβες & Τρόφιμα",
        "Καθαριστικά",
        "Προσωπική Φροντίδα",
    ]

    def scrape_category(self, category: str, max_pages: int = 5) -> list[Product]:
        products = []
        for page in range(max_pages):
            try:
                resp = get(
                    self.API,
                    params={
                        "query": category,
                        "page": page,
                        "pageSize": 36,
                        "country": "GR",
                        "language": "el",
                        "categoryId": "",
                    }
                )
                data = resp.json()
                items = data.get("gridData", {}).get("products", [])
                if not items:
                    break

                for item in items:
                    p = self._parse(item, category)
                    if p:
                        products.append(p)

                if page >= data.get("gridData", {}).get("totalPages", 1) - 1:
                    break

            except Exception as e:
                print(f"[Lidl] Error on category={category} page={page}: {e}")
                break

        return products

    def _parse(self, item: dict, category: str) -> Optional[Product]:
        try:
            price_info = item.get("price", {})
            price = float(price_info.get("price", 0))
            if price <= 0:
                return None

            original = price_info.get("regularPrice")
            is_offer = original is not None and float(original) > price

            return Product(
                chain="lidl",
                chain_sku=str(item.get("productId", item.get("id", ""))),
                name=item.get("fullTitle", item.get("title", "")),
                price=price,
                price_per_unit=item.get("pricePerUnit", {}).get("price") if item.get("pricePerUnit") else None,
                unit=item.get("pricePerUnit", {}).get("unit") if item.get("pricePerUnit") else None,
                brand=item.get("brand"),
                ean=None,  # Lidl δε δίνει EAN εύκολα
                image_url=item.get("image", {}).get("src") if item.get("image") else None,
                is_offer=is_offer,
                offer_original_price=float(original) if is_offer else None,
                category=category,
                url=f"https://www.lidl.gr{item.get('canonicalUrl', '')}",
            )
        except Exception as e:
            print(f"[Lidl] Parse error: {e}")
            return None

    def scrape_all(self) -> list[Product]:
        all_products = []
        for cat in self.CATEGORIES:
            print(f"[Lidl] Scraping category: {cat}")
            products = self.scrape_category(cat)
            print(f"[Lidl]   → {len(products)} products")
            all_products.extend(products)
        return all_products


# ---------------------------------------------------------------------------
# My Market scraper
# ---------------------------------------------------------------------------

class MyMarketScraper:
    BASE = "https://www.mymarket.gr"
    API  = "https://www.mymarket.gr/api/products"

    CATEGORIES = [
        "galaktokomika",
        "allantika-tyrokomika",
        "artopoiimata",
        "katepsygmena",
        "anapsyktika",
        "kafes-rofiimata",
        "konserves-trofiima",
        "katharistika",
        "prosopikhfrontida",
    ]

    def scrape_category(self, category_slug: str, max_pages: int = 5) -> list[Product]:
        products = []
        for page in range(1, max_pages + 1):
            try:
                resp = get(
                    f"{self.API}/{category_slug}",
                    params={"page": page, "per_page": 40},
                    headers={"Referer": f"{self.BASE}/category/{category_slug}/"}
                )
                data = resp.json()
                items = data.get("data", data.get("products", []))
                if not items:
                    break

                for item in items:
                    p = self._parse(item, category_slug)
                    if p:
                        products.append(p)

                if len(items) < 40:
                    break

            except Exception as e:
                print(f"[MyMarket] Error on category={category_slug} page={page}: {e}")
                break

        return products

    def _parse(self, item: dict, category: str) -> Optional[Product]:
        try:
            price = float(item.get("price", item.get("final_price", 0)))
            if price <= 0:
                return None

            original = item.get("regular_price") or item.get("original_price")
            is_offer = original is not None and float(original) > price

            return Product(
                chain="mymarket",
                chain_sku=str(item.get("id", item.get("sku", ""))),
                name=item.get("name", item.get("title", "")),
                price=price,
                price_per_unit=item.get("price_per_unit"),
                unit=item.get("measurement_unit"),
                brand=item.get("brand", {}).get("name") if isinstance(item.get("brand"), dict) else item.get("brand"),
                ean=item.get("ean") or item.get("barcode"),
                image_url=item.get("image_url") or item.get("thumbnail"),
                is_offer=is_offer,
                offer_original_price=float(original) if is_offer else None,
                category=category,
                url=f"{self.BASE}/product/{item.get('slug', item.get('id', ''))}",
            )
        except Exception as e:
            print(f"[MyMarket] Parse error: {e}")
            return None

    def scrape_all(self) -> list[Product]:
        all_products = []
        for cat in self.CATEGORIES:
            print(f"[MyMarket] Scraping category: {cat}")
            products = self.scrape_category(cat)
            print(f"[MyMarket]   → {len(products)} products")
            all_products.extend(products)
        return all_products


# ---------------------------------------------------------------------------
# SQLite storage (για local testing — αντικαθίσταται από Supabase στο production)
# ---------------------------------------------------------------------------

def init_db(db_path: str = "prices.db") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chain TEXT NOT NULL,
            chain_sku TEXT NOT NULL,
            name TEXT NOT NULL,
            brand TEXT,
            ean TEXT,
            category TEXT,
            image_url TEXT,
            url TEXT,
            unit TEXT,
            UNIQUE(chain, chain_sku)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chain TEXT NOT NULL,
            chain_sku TEXT NOT NULL,
            price REAL NOT NULL,
            price_per_unit REAL,
            is_offer INTEGER DEFAULT 0,
            offer_original_price REAL,
            scraped_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ph_chain_sku ON price_history(chain, chain_sku)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ph_scraped ON price_history(scraped_at)")
    conn.commit()
    return conn


def save_products(conn: sqlite3.Connection, products: list[Product]):
    for p in products:
        # Upsert product
        conn.execute("""
            INSERT INTO products (chain, chain_sku, name, brand, ean, category, image_url, url, unit)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chain, chain_sku) DO UPDATE SET
                name=excluded.name, brand=excluded.brand,
                ean=excluded.ean, image_url=excluded.image_url,
                url=excluded.url, unit=excluded.unit
        """, (p.chain, p.chain_sku, p.name, p.brand, p.ean,
              p.category, p.image_url, p.url, p.unit))

        # Insert price record
        conn.execute("""
            INSERT INTO price_history
                (chain, chain_sku, price, price_per_unit, is_offer, offer_original_price, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (p.chain, p.chain_sku, p.price, p.price_per_unit,
              int(p.is_offer), p.offer_original_price, p.scraped_at))

    conn.commit()
    print(f"[DB] Saved {len(products)} products")


def export_json(conn: sqlite3.Connection, output: str = "prices.json"):
    """Export τελευταίων τιμών σε JSON για το frontend."""
    rows = conn.execute("""
        SELECT
            p.chain, p.name, p.brand, p.ean, p.category,
            p.image_url, p.url, p.unit,
            ph.price, ph.price_per_unit, ph.is_offer,
            ph.offer_original_price, ph.scraped_at
        FROM products p
        JOIN (
            SELECT chain, chain_sku, MAX(scraped_at) as max_ts
            FROM price_history
            GROUP BY chain, chain_sku
        ) latest ON latest.chain = p.chain AND latest.chain_sku = p.chain_sku
        JOIN price_history ph
            ON ph.chain = p.chain
            AND ph.chain_sku = p.chain_sku
            AND ph.scraped_at = latest.max_ts
        ORDER BY p.name
    """).fetchall()

    data = [
        {
            "chain": r[0], "name": r[1], "brand": r[2], "ean": r[3],
            "category": r[4], "image_url": r[5], "url": r[6], "unit": r[7],
            "price": r[8], "price_per_unit": r[9], "is_offer": bool(r[10]),
            "offer_original_price": r[11], "scraped_at": r[12],
        }
        for r in rows
    ]

    with open(output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[Export] {len(data)} products → {output}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Greek Supermarket Scraper")
    print("=" * 60)

    conn = init_db()
    scrapers = [
        ("AB Vassilopoulos", ABScraper()),
        ("Sklavenitis",      SklavenitissScraper()),
        ("Lidl GR",          LidlScraper()),
        ("My Market",        MyMarketScraper()),
    ]

    for name, scraper in scrapers:
        print(f"\n{'─'*40}")
        print(f"Starting: {name}")
        print(f"{'─'*40}")
        try:
            products = scraper.scrape_all()
            save_products(conn, products)
            print(f"✓ {name}: {len(products)} products scraped & saved")
        except Exception as e:
            print(f"✗ {name} FAILED: {e}")

    print(f"\n{'─'*40}")
    print("Exporting JSON for frontend...")
    export_json(conn, "prices.json")
    print("Done! ✓")
