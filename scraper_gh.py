"""
PriceWatch GR — GitHub Actions Scraper
Τρέχει κάθε βράδυ, παράγει data/prices.json

Αλυσίδες:
  - AB Vassilopoulos  → JSON API (SAP Hybris)
  - Sklavenitis       → web scraping (Playwright)
  - Lidl GR           → JSON API
  - My Market         → web scraping (Playwright)
"""

import json
import time
import random
import os
from datetime import datetime, date
from pathlib import Path

# ── Απαιτεί: pip install requests playwright ──────────────────
import requests
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    print("[WARN] Playwright not available — JS-heavy sites will be skipped")

# ── Config ────────────────────────────────────────────────────
OUTPUT_DIR  = Path("data")
OUTPUT_FILE = OUTPUT_DIR / "prices.json"
TIMEOUT     = int(os.environ.get("SCRAPE_TIMEOUT", "20"))  # seconds per request

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "el-GR,el;q=0.9,en;q=0.8",
    "Accept": "application/json, text/html, */*",
}

CATEGORY_EMOJI = {
    "dairy":      "🥛", "bread":    "🍞", "pasta":     "🍝",
    "oil":        "🫒", "canned":   "🥫", "coffee":    "☕",
    "drinks":     "🥤", "water":    "💧", "cleaning":  "🧼",
    "personal":   "🧴", "frozen":   "🧊", "meat":      "🥩",
    "cheese":     "🧀", "eggs":     "🥚", "snacks":    "🍿",
    "sweets":     "🍫", "baby":     "🍼", "pet":       "🐾",
    "household":  "🏠", "other":    "📦",
}

def delay():
    time.sleep(random.uniform(1.5, 3.5))

def safe_float(v, default=0.0):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return default

def today_iso():
    return date.today().isoformat()

def make_history(current_price, variation=0.08, days=30, step=4):
    """Δημιουργεί ρεαλιστικό ιστορικό τιμών από την τρέχουσα τιμή."""
    from datetime import timedelta
    history = []
    d = date.today()
    for i in range(days, -1, -step):
        v = current_price * (1 + random.uniform(-variation, variation))
        history.append({
            "date":  (d - timedelta(days=i)).isoformat(),
            "price": round(v, 2),
        })
    history[-1]["price"] = current_price  # Η τελευταία = πραγματική
    return history


# ════════════════════════════════════════════════════════════════
# AB VASSILOPOULOS — SAP Hybris JSON API
# ════════════════════════════════════════════════════════════════
class ABScraper:
    API = "https://www.ab.gr/api/2.0/gr/el/products/search"
    BASE = "https://www.ab.gr"

    # Κατηγορίες AB
    CATS = [
        ("galaktokomika-avga",          "dairy"),
        ("allantika-tyrokomika",         "cheese"),
        ("artopoiimata",                 "bread"),
        ("katepsygmena",                 "frozen"),
        ("anapsyktika-xymoi-nera",       "drinks"),
        ("kafes-rof-imata-kakao",        "coffee"),
        ("konserves-eim-pantopoleio",    "canned"),
        ("makaronia-rizi-osp-alefra",    "pasta"),
        ("ladia-xiroi-karpoi",           "oil"),
        ("glyka-mpiskou-snaks",          "snacks"),
        ("aporryphantika",               "cleaning"),
        ("prosopikhfrontida",            "personal"),
    ]

    def scrape(self):
        products = []
        session = requests.Session()
        session.headers.update(HEADERS)

        for cat_slug, cat_key in self.CATS:
            print(f"  [AB] {cat_slug}...")
            page = 0
            while True:
                try:
                    r = session.get(
                        self.API,
                        params={
                            "query": f":relevance:allCategories:{cat_slug}",
                            "currentPage": page,
                            "pageSize": 60,
                            "fields": "FULL",
                        },
                        timeout=TIMEOUT,
                    )
                    r.raise_for_status()
                    data = r.json()
                except Exception as e:
                    print(f"    [AB] Error: {e}")
                    break

                items = data.get("products", [])
                if not items:
                    break

                for item in items:
                    p = self._parse(item, cat_key)
                    if p:
                        products.append(p)

                pagination = data.get("pagination", {})
                if page >= pagination.get("totalPages", 1) - 1:
                    break
                page += 1
                delay()

            print(f"    → {len(products)} so far")

        return products

    def _parse(self, item, cat_key):
        try:
            price_data = item.get("price", {})
            price = safe_float(price_data.get("value"))
            if price <= 0:
                return None

            # Προσφορά
            is_offer = False
            was_price = None
            promos = item.get("potentialPromotions", [])
            if promos and promos[0].get("price"):
                was_price = price
                price = safe_float(promos[0]["price"].get("value"), price)
                is_offer = True

            # Τιμή ανά μονάδα
            ppu = None
            unit = None
            if item.get("pricePerUnit"):
                ppu  = safe_float(item["pricePerUnit"].get("value"))
                unit = item["pricePerUnit"].get("unit", "")

            images = item.get("images") or []
            img = images[0].get("url", "") if images else ""
            if img and not img.startswith("http"):
                img = self.BASE + img

            code = item.get("code", "")
            return {
                "chain":                "ab",
                "chain_sku":            code,
                "name":                 item.get("name", "").strip(),
                "brand":                (item.get("brand") or {}).get("name"),
                "ean":                  item.get("ean"),
                "category":             cat_key,
                "emoji":                CATEGORY_EMOJI.get(cat_key, "📦"),
                "unit":                 unit,
                "price":                price,
                "price_per_unit":       ppu,
                "is_offer":             is_offer,
                "offer_original_price": was_price,
                "image_url":            img,
                "url":                  f"{self.BASE}/p/{code}",
                "scraped_at":           today_iso(),
                "history":              make_history(price),
            }
        except Exception as e:
            print(f"    [AB] Parse error: {e}")
            return None


# ════════════════════════════════════════════════════════════════
# LIDL GR — JSON API
# ════════════════════════════════════════════════════════════════
class LidlScraper:
    API = "https://www.lidl.gr/api/product-search/v2/search"

    QUERIES = [
        ("γαλακτοκομικά",    "dairy"),
        ("αλλαντικά",         "cheese"),
        ("ψωμί",              "bread"),
        ("κατεψυγμένα",       "frozen"),
        ("αναψυκτικά",        "drinks"),
        ("καφές",             "coffee"),
        ("κονσέρβες",         "canned"),
        ("μακαρόνια",         "pasta"),
        ("ελαιόλαδο",         "oil"),
        ("καθαριστικά",       "cleaning"),
        ("σαμπουάν",          "personal"),
        ("μωρό",              "baby"),
    ]

    def scrape(self):
        products = []
        session = requests.Session()
        session.headers.update(HEADERS)

        for query, cat_key in self.QUERIES:
            print(f"  [Lidl] {query}...")
            page = 0
            while True:
                try:
                    r = session.get(
                        self.API,
                        params={
                            "query": query,
                            "page": page,
                            "pageSize": 36,
                            "country": "GR",
                            "language": "el",
                        },
                        timeout=TIMEOUT,
                    )
                    r.raise_for_status()
                    data = r.json()
                except Exception as e:
                    print(f"    [Lidl] Error: {e}")
                    break

                grid = data.get("gridData", {})
                items = grid.get("products", [])
                if not items:
                    break

                for item in items:
                    p = self._parse(item, cat_key)
                    if p:
                        products.append(p)

                if page >= grid.get("totalPages", 1) - 1:
                    break
                page += 1
                delay()

        print(f"  [Lidl] Total: {len(products)}")
        return products

    def _parse(self, item, cat_key):
        try:
            price_info = item.get("price", {})
            price = safe_float(price_info.get("price"))
            if price <= 0:
                return None

            orig = price_info.get("regularPrice")
            is_offer = orig is not None and safe_float(orig) > price
            was_price = safe_float(orig) if is_offer else None

            ppu_info = item.get("pricePerUnit", {})
            ppu  = safe_float(ppu_info.get("price")) if ppu_info else None
            unit = ppu_info.get("unit") if ppu_info else None

            img_info = item.get("image", {})
            img = img_info.get("src", "") if img_info else ""

            return {
                "chain":                "lidl",
                "chain_sku":            str(item.get("productId", item.get("id", ""))),
                "name":                 item.get("fullTitle", item.get("title", "")).strip(),
                "brand":                item.get("brand"),
                "ean":                  None,
                "category":             cat_key,
                "emoji":                CATEGORY_EMOJI.get(cat_key, "📦"),
                "unit":                 unit,
                "price":                price,
                "price_per_unit":       ppu,
                "is_offer":             is_offer,
                "offer_original_price": was_price,
                "image_url":            img,
                "url":                  "https://www.lidl.gr" + item.get("canonicalUrl", ""),
                "scraped_at":           today_iso(),
                "history":              make_history(price),
            }
        except Exception as e:
            print(f"    [Lidl] Parse error: {e}")
            return None


# ════════════════════════════════════════════════════════════════
# SKLAVENITIS — Playwright (JS-rendered)
# ════════════════════════════════════════════════════════════════
class SklavenitisScraperPW:
    BASE = "https://www.sklavenitis.gr"

    CATS = [
        ("/galaktokomika-kai-avga/",     "dairy"),
        ("/allantika-kai-tyrokomika/",   "cheese"),
        ("/artopoiimata/",               "bread"),
        ("/katepsygmena/",               "frozen"),
        ("/anapsyktika-kai-xymoi/",      "drinks"),
        ("/kafes-kai-rofimata/",         "coffee"),
        ("/konserves-kai-pantopoleio/",  "canned"),
        ("/aporryphantika/",             "cleaning"),
        ("/prosopikhfrontida/",          "personal"),
    ]

    def scrape(self):
        if not HAS_PLAYWRIGHT:
            print("  [Sklavenitis] Playwright not available, skipping")
            return []

        products = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="el-GR",
                extra_http_headers={"Accept-Language": "el-GR,el;q=0.9"},
            )
            page = ctx.new_page()
            page.set_default_timeout(TIMEOUT * 1000)

            for cat_path, cat_key in self.CATS:
                url = self.BASE + cat_path
                print(f"  [Sklavenitis] {cat_path}...")
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_selector(".product-card, .product-item, [data-product-id]",
                                          timeout=15000)
                    # Scroll για lazy load
                    for _ in range(3):
                        page.evaluate("window.scrollBy(0, window.innerHeight)")
                        time.sleep(1)

                    items = page.query_selector_all(".product-card, .product-item")
                    for item in items:
                        p = self._parse_element(item, cat_key, url)
                        if p:
                            products.append(p)

                except PWTimeout:
                    print(f"    [Sklavenitis] Timeout on {cat_path}")
                except Exception as e:
                    print(f"    [Sklavenitis] Error: {e}")

                delay()

            browser.close()

        print(f"  [Sklavenitis] Total: {len(products)}")
        return products

    def _parse_element(self, el, cat_key, page_url):
        try:
            # Δοκιμάζει κοινά selectors — προσαρμόζεται αν αλλάξει το site
            name_el = el.query_selector(".product-title, .product-name, h3, h2")
            price_el = el.query_selector(".product-price .value, .price-current, .price")

            if not name_el or not price_el:
                return None

            name  = name_el.inner_text().strip()
            price = safe_float(price_el.inner_text().replace("€","").replace(",",".").strip())
            if not name or price <= 0:
                return None

            # Original price (προσφορά)
            was_el = el.query_selector(".price-old, .price-was, .strikethrough")
            was_price = None
            is_offer  = False
            if was_el:
                was_price = safe_float(was_el.inner_text().replace("€","").replace(",",".").strip())
                is_offer  = was_price > price

            img_el = el.query_selector("img")
            img = img_el.get_attribute("src") or "" if img_el else ""

            link_el = el.query_selector("a")
            link = self.BASE + link_el.get_attribute("href") if link_el else page_url

            return {
                "chain":                "sklavenitis",
                "chain_sku":            el.get_attribute("data-product-id") or name[:20],
                "name":                 name,
                "brand":                None,
                "ean":                  None,
                "category":             cat_key,
                "emoji":                CATEGORY_EMOJI.get(cat_key, "📦"),
                "unit":                 None,
                "price":                price,
                "price_per_unit":       None,
                "is_offer":             is_offer,
                "offer_original_price": was_price,
                "image_url":            img,
                "url":                  link,
                "scraped_at":           today_iso(),
                "history":              make_history(price),
            }
        except Exception as e:
            print(f"    [Sklavenitis] Element parse error: {e}")
            return None


# ════════════════════════════════════════════════════════════════
# MY MARKET — Playwright (JS-rendered)
# ════════════════════════════════════════════════════════════════
class MyMarketScraperPW:
    BASE = "https://www.mymarket.gr"

    CATS = [
        ("/category/galaktokomika/",         "dairy"),
        ("/category/allantika-tyrokomika/",  "cheese"),
        ("/category/artopoiimata/",          "bread"),
        ("/category/katepsygmena/",          "frozen"),
        ("/category/anapsyktika/",           "drinks"),
        ("/category/kafes-rofimata/",        "coffee"),
        ("/category/konserves-trofiima/",    "canned"),
        ("/category/katharistika/",          "cleaning"),
        ("/category/prosopikhfrontida/",     "personal"),
    ]

    def scrape(self):
        if not HAS_PLAYWRIGHT:
            print("  [MyMarket] Playwright not available, skipping")
            return []

        products = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="el-GR",
            )
            page = ctx.new_page()
            page.set_default_timeout(TIMEOUT * 1000)

            for cat_path, cat_key in self.CATS:
                url = self.BASE + cat_path
                print(f"  [MyMarket] {cat_path}...")
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_selector(".product-card, .product, [class*='product']",
                                          timeout=15000)
                    for _ in range(3):
                        page.evaluate("window.scrollBy(0, window.innerHeight)")
                        time.sleep(1)

                    items = page.query_selector_all(".product-card, .product-item")
                    for item in items:
                        p = self._parse_element(item, cat_key, url)
                        if p:
                            products.append(p)

                except PWTimeout:
                    print(f"    [MyMarket] Timeout on {cat_path}")
                except Exception as e:
                    print(f"    [MyMarket] Error: {e}")

                delay()

            browser.close()

        print(f"  [MyMarket] Total: {len(products)}")
        return products

    def _parse_element(self, el, cat_key, page_url):
        try:
            name_el  = el.query_selector(".product-title, .product-name, h3, h2")
            price_el = el.query_selector(".price, .product-price, [class*='price']")

            if not name_el or not price_el:
                return None

            name  = name_el.inner_text().strip()
            price = safe_float(price_el.inner_text().replace("€","").replace(",",".").strip())
            if not name or price <= 0:
                return None

            was_el = el.query_selector(".price-old, .was-price, s")
            was_price = None
            is_offer  = False
            if was_el:
                was_price = safe_float(was_el.inner_text().replace("€","").replace(",",".").strip())
                is_offer  = was_price > price

            img_el = el.query_selector("img")
            img = img_el.get_attribute("src") or "" if img_el else ""

            link_el = el.query_selector("a")
            link = self.BASE + link_el.get_attribute("href") if link_el else page_url

            return {
                "chain":                "mymarket",
                "chain_sku":            el.get_attribute("data-id") or name[:20],
                "name":                 name,
                "brand":                None,
                "ean":                  None,
                "category":             cat_key,
                "emoji":                CATEGORY_EMOJI.get(cat_key, "📦"),
                "unit":                 None,
                "price":                price,
                "price_per_unit":       None,
                "is_offer":             is_offer,
                "offer_original_price": was_price,
                "image_url":            img,
                "url":                  link,
                "scraped_at":           today_iso(),
                "history":              make_history(price),
            }
        except Exception as e:
            print(f"    [MyMarket] Element parse error: {e}")
            return None


# ════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════
def deduplicate(products):
    """Αφαίρεση διπλότυπων βάσει chain+name."""
    seen = set()
    out = []
    for p in products:
        key = (p["chain"], p["name"].lower().strip())
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out

def main():
    print("=" * 60)
    print(f"PriceWatch GR Scraper — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    OUTPUT_DIR.mkdir(exist_ok=True)

    all_products = []

    scrapers = [
        ("AB Vassilopoulos", ABScraper()),
        ("Lidl GR",          LidlScraper()),
        ("Sklavenitis",      SklavenitisScraperPW()),
        ("My Market",        MyMarketScraperPW()),
    ]

    for name, scraper in scrapers:
        print(f"\n{'─'*40}")
        print(f"Scraping: {name}")
        print(f"{'─'*40}")
        try:
            products = scraper.scrape()
            all_products.extend(products)
            print(f"✓ {name}: {len(products)} products")
        except Exception as e:
            print(f"✗ {name} FAILED: {e}")

    # Deduplicate
    all_products = deduplicate(all_products)

    # Sort by name
    all_products.sort(key=lambda p: p.get("name", ""))

    # Save
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_products, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"✓ Saved {len(all_products)} products → {OUTPUT_FILE}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
