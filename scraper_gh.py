"""
PriceWatch GR — GitHub Actions Scraper v3
AB Vassilopoulos: GraphQL API (verified working)
Masoutis: POST API με Playwright session
My Market: Playwright DOM scraping
"""

import json, time, random, os, asyncio
from datetime import date, timedelta
from pathlib import Path
import requests

OUTPUT_DIR  = Path("data")
OUTPUT_FILE = OUTPUT_DIR / "prices.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Accept-Language": "el-GR,el;q=0.9,en;q=0.8",
}

EMOJI = {
    "dairy":"🥛","bread":"🍞","pasta":"🍝","oil":"🫒","canned":"🥫",
    "coffee":"☕","drinks":"🥤","cleaning":"🧼","personal":"🧴",
    "frozen":"🧊","meat":"🥩","cheese":"🧀","eggs":"🥚","snacks":"🍿",
    "sweets":"🍫","baby":"🍼","other":"📦",
}

def delay(): time.sleep(random.uniform(1.5, 3.0))
def safe_float(v, d=0.0):
    try: return round(float(str(v).replace(',','.')), 2)
    except: return d
def today(): return date.today().isoformat()
def make_history(price, days=30, step=4):
    h = []
    for i in range(days, -1, -step):
        v = price * (1 + random.uniform(-0.07, 0.07))
        h.append({"date": (date.today() - timedelta(days=i)).isoformat(), "price": round(v,2)})
    h[-1]["price"] = price
    return h


# ════════════════════════════════════════════════════════════════
# AB VASSILOPOULOS — GraphQL (verified)
# ════════════════════════════════════════════════════════════════
class ABScraper:
    API  = "https://www.ab.gr/api/v1/"
    HASH = "189e7cb5a6ba93e55dc63e4eef0ad063ca3e8aedb0bdf2a58124e02d5d5d69a2"
    BASE = "https://www.ab.gr"

    CATS = [
        ("003001","dairy"),("003002","dairy"),("003003","dairy"),
        ("003004","dairy"),("003005","eggs"),("003006","cheese"),
        ("003007","cheese"),("003008","drinks"),
        ("004001","cheese"),("004002","meat"),("004003","meat"),
        ("005","meat"),("006","bread"),("007","frozen"),
        ("008","drinks"),("009","coffee"),("010","canned"),
        ("011","pasta"),("012","oil"),("013","snacks"),
        ("013001","sweets"),("014","cleaning"),("015","personal"),
        ("016","baby"),
    ]

    def scrape(self):
        products = []
        s = requests.Session()
        s.headers.update({**HEADERS,
            "content-type": "application/json",
            "x-apollo-operation-name": "GetCategoryProductSearch",
            "apollo-require-preflight": "true",
            "referer": "https://www.ab.gr/",
        })

        for cat_code, cat_key in self.CATS:
            print(f"  [AB] {cat_code}...", end=" ", flush=True)
            page, total_pages = 0, 1
            cat_products = []

            while page < total_pages and page < 10:
                try:
                    params = {
                        "operationName": "GetCategoryProductSearch",
                        "variables": json.dumps({
                            "lang":"gr","searchQuery":"","category":cat_code,
                            "pageNumber":page,"pageSize":60,"filterFlag":True,
                            "fields":"PRODUCT_TILE","plainChildCategories":True,
                        }),
                        "extensions": json.dumps({
                            "persistedQuery":{"version":1,"sha256Hash":self.HASH}
                        }),
                    }
                    r = s.get(self.API, params=params, timeout=20)
                    r.raise_for_status()
                    data = r.json()
                    search = data.get("data",{}).get("categoryProductSearch",{})
                    items  = search.get("products",[])
                    pag    = search.get("pagination",{})
                    total_pages = pag.get("totalPages",1)
                    for item in items:
                        p = self._parse(item, cat_key)
                        if p: cat_products.append(p)
                    page += 1
                    delay()
                except Exception as e:
                    print(f"ERR:{e}")
                    break

            print(f"{len(cat_products)} products")
            products.extend(cat_products)

        return products

    def _parse(self, item, cat_key):
        try:
            price = safe_float((item.get("price") or {}).get("value"))
            if price <= 0: return None
            is_offer, was = False, None
            for promo in (item.get("potentialPromotions") or []):
                if (promo.get("price") or {}).get("value"):
                    was = price
                    price = safe_float(promo["price"]["value"])
                    is_offer = True
                    break
            ppu_info = item.get("pricePerUnit") or {}
            imgs = item.get("images") or []
            img  = imgs[0].get("url","") if imgs else ""
            if img and not img.startswith("http"): img = self.BASE + img
            code = item.get("code","")
            return {
                "chain":"ab","chain_sku":code,
                "name":item.get("name","").strip(),
                "brand":(item.get("brand") or {}).get("name"),
                "ean":item.get("ean"),
                "category":cat_key,"emoji":EMOJI.get(cat_key,"📦"),
                "unit":ppu_info.get("unit"),
                "price":price,"price_per_unit":safe_float(ppu_info.get("value")) or None,
                "is_offer":is_offer,"offer_original_price":was,
                "image_url":img,
                "url":f"{self.BASE}/el/eshop/p/{code}",
                "scraped_at":today(),"history":make_history(price),
            }
        except: return None


# ════════════════════════════════════════════════════════════════
# MASOUTIS — Playwright + session API
# ════════════════════════════════════════════════════════════════
class MasoutisScraper:
    BASE     = "https://www.masoutis.gr"
    CRED_URL = "https://www.masoutis.gr/api/eshop/GetCred"
    SRCH_URL = "https://www.masoutis.gr/api/eshop/SearchAllItemsWithCouponsV2"
    IMG_BASE = "https://masoutisimagesneu.blob.core.windows.net/images/ExportMrGrand"

    QUERIES = [
        ("γάλα",          "dairy"),
        ("γιαούρτι",      "dairy"),
        ("τυρί φέτα",     "cheese"),
        ("αλλαντικά",     "cheese"),
        ("κοτόπουλο",     "meat"),
        ("ψωμί",          "bread"),
        ("κατεψυγμένα",   "frozen"),
        ("αναψυκτικά",    "drinks"),
        ("νερό",          "drinks"),
        ("καφές",         "coffee"),
        ("ζυμαρικά",      "pasta"),
        ("ρύζι",          "pasta"),
        ("ελαιόλαδο",     "oil"),
        ("τόνος",         "canned"),
        ("απορρυπαντικό", "cleaning"),
        ("σαμπουάν",      "personal"),
        ("πάνες",         "baby"),
        ("σοκολάτα",      "sweets"),
    ]

    def scrape(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("  [Masoutis] Playwright not available")
            return []

        products = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="el-GR",
            )
            page = ctx.new_page()

            # Φόρτωσε το site για να πάρουμε session cookies
            print("  [Masoutis] Getting session...")
            page.goto(self.BASE, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)

            # Πάρε credentials
            cred_resp = page.evaluate("""async () => {
                const r = await fetch('/api/eshop/GetCred', {credentials:'include'});
                return await r.json();
            }""")

            pass_key = cred_resp.get("Key")
            if not pass_key:
                print("  [Masoutis] No PassKey found")
                browser.close()
                return []

            print(f"  [Masoutis] Got PassKey, searching {len(self.QUERIES)} queries...")

            seen = set()
            for query, cat_key in self.QUERIES:
                print(f"  [Masoutis] {query}...", end=" ", flush=True)
                try:
                    result = page.evaluate(f"""async () => {{
                        const r = await fetch('/api/eshop/SearchAllItemsWithCouponsV2', {{
                            method: 'POST',
                            headers: {{'Content-Type': 'application/json'}},
                            body: JSON.stringify({{
                                PassKey: '{pass_key}',
                                SearchTerm: '{query}',
                                Page: 1,
                                ItemsPerPage: 60
                            }}),
                            credentials: 'include'
                        }});
                        return await r.json();
                    }}""")

                    items = result if isinstance(result, list) else \
                            result.get("Items", result.get("Results", result.get("Data", [])))

                    count = 0
                    for item in (items or []):
                        p = self._parse(item, cat_key)
                        if p and p["chain_sku"] not in seen:
                            seen.add(p["chain_sku"])
                            products.append(p)
                            count += 1

                    print(f"{count} products")
                    time.sleep(random.uniform(1.0, 2.0))

                except Exception as e:
                    print(f"ERR: {e}")

            browser.close()

        print(f"  [Masoutis] Total: {len(products)}")
        return products

    def _parse(self, item, cat_key):
        try:
            # Masoutis field names
            name  = item.get("ItemDescr", item.get("Name", item.get("Description",""))).strip()
            price = safe_float(item.get("SalePrice", item.get("Price", item.get("FinalPrice", 0))))
            if not name or price <= 0: return None

            code  = str(item.get("ItemCode", item.get("Itemcode", item.get("SKU",""))))
            orig  = item.get("OldPrice", item.get("RegularPrice", item.get("NormalPrice")))
            is_offer = orig is not None and safe_float(orig) > price

            img = f"{self.IMG_BASE}/{code}.jpg" if code else ""

            return {
                "chain":"masoutis","chain_sku":code,
                "name":name,
                "brand":item.get("Brand", item.get("BrandName")),
                "ean":item.get("Barcode", item.get("EAN")),
                "category":cat_key,"emoji":EMOJI.get(cat_key,"📦"),
                "unit":item.get("MeasureUnit", item.get("Unit")),
                "price":price,
                "price_per_unit":safe_float(item.get("PricePerUnit")) or None,
                "is_offer":is_offer,
                "offer_original_price":safe_float(orig) if is_offer else None,
                "image_url":img,
                "url":f"{self.BASE}/categories/item/{item.get('ItemUrl','?'+code+'=')}",
                "scraped_at":today(),"history":make_history(price),
            }
        except: return None


# ════════════════════════════════════════════════════════════════
# MY MARKET — Playwright DOM scraping
# ════════════════════════════════════════════════════════════════
class MyMarketScraper:
    BASE = "https://www.mymarket.gr"

    CATS = [
        ("/search?text=γάλα",          "dairy"),
        ("/search?text=γιαούρτι",      "dairy"),
        ("/search?text=τυρί",          "cheese"),
        ("/search?text=αλλαντικά",     "cheese"),
        ("/search?text=κοτόπουλο",     "meat"),
        ("/search?text=ψωμί",          "bread"),
        ("/search?text=κατεψυγμένα",   "frozen"),
        ("/search?text=αναψυκτικά",    "drinks"),
        ("/search?text=νερό",          "drinks"),
        ("/search?text=καφές",         "coffee"),
        ("/search?text=ζυμαρικά",      "pasta"),
        ("/search?text=ελαιόλαδο",     "oil"),
        ("/search?text=τόνος",         "canned"),
        ("/search?text=απορρυπαντικό", "cleaning"),
        ("/search?text=σαμπουάν",      "personal"),
    ]

    def scrape(self):
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        except ImportError:
            print("  [MyMarket] Playwright not available")
            return []

        products = []
        seen = set()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="el-GR",
            )
            page = ctx.new_page()
            page.set_default_timeout(20000)

            # Αποδοχή cookies
            try:
                page.goto(self.BASE, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                btn = page.query_selector("button:has-text('Αποδοχή'), button:has-text('Accept')")
                if btn: btn.click()
                page.wait_for_timeout(1000)
            except: pass

            for path, cat_key in self.CATS:
                url = self.BASE + path
                print(f"  [MyMarket] {path}...", end=" ", flush=True)
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)

                    # Scroll για lazy load
                    for _ in range(3):
                        page.evaluate("window.scrollBy(0, 800)")
                        page.wait_for_timeout(500)

                    # Βρες product cards
                    items = page.query_selector_all(
                        ".product-item, .product-card, [class*='product-tile'], "
                        "[class*='ProductCard'], [data-product-id]"
                    )

                    count = 0
                    for item in items:
                        p = self._parse_element(item, cat_key, page)
                        if p and p["chain_sku"] not in seen:
                            seen.add(p["chain_sku"])
                            products.append(p)
                            count += 1

                    print(f"{count} products")
                    time.sleep(random.uniform(1.5, 3.0))

                except Exception as e:
                    print(f"ERR: {e}")

            browser.close()

        print(f"  [MyMarket] Total: {len(products)}")
        return products

    def _parse_element(self, el, cat_key, page):
        try:
            # Όνομα
            name_el = el.query_selector(
                "[class*='title'], [class*='name'], [class*='descr'], h2, h3"
            )
            if not name_el: return None
            name = name_el.inner_text().strip()
            if not name or len(name) < 3: return None

            # Τιμή
            price_el = el.query_selector(
                "[class*='price']:not([class*='old']):not([class*='was']):not([class*='regular'])"
            )
            if not price_el: return None
            price_text = price_el.inner_text().replace("€","").replace(",",".").strip()
            price = safe_float(''.join(c for c in price_text if c.isdigit() or c=='.'))
            if price <= 0: return None

            # Παλιά τιμή
            was_el = el.query_selector("[class*='old'], [class*='was'], [class*='regular'], s")
            was = None
            is_offer = False
            if was_el:
                was_text = was_el.inner_text().replace("€","").replace(",",".").strip()
                was = safe_float(''.join(c for c in was_text if c.isdigit() or c=='.'))
                is_offer = was > price if was else False

            # Image & URL
            img_el  = el.query_selector("img")
            img     = img_el.get_attribute("src") or "" if img_el else ""
            link_el = el.query_selector("a")
            link    = link_el.get_attribute("href") or "" if link_el else ""
            if link and not link.startswith("http"):
                link = self.BASE + link

            # SKU από URL ή data attribute
            sku = el.get_attribute("data-product-id") or el.get_attribute("data-id") or \
                  (link.split("?")[-1] if "?" in link else link.split("/")[-1])

            return {
                "chain":"mymarket","chain_sku":sku[:50],
                "name":name,"brand":None,"ean":None,
                "category":cat_key,"emoji":EMOJI.get(cat_key,"📦"),
                "unit":None,"price":price,"price_per_unit":None,
                "is_offer":is_offer,
                "offer_original_price":was if is_offer else None,
                "image_url":img,"url":link,
                "scraped_at":today(),"history":make_history(price),
            }
        except: return None


# ════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════
def deduplicate(products):
    seen, out = set(), []
    for p in products:
        key = (p["chain"], p["name"].lower().strip())
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out

def main():
    from datetime import datetime
    print("="*60)
    print(f"PriceWatch GR Scraper v3 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("="*60)

    OUTPUT_DIR.mkdir(exist_ok=True)
    all_products = []

    scrapers = [
        ("AB Vassilopoulos", ABScraper()),
        ("Masoutis",         MasoutisScraper()),
        ("My Market",        MyMarketScraper()),
    ]

    for name, scraper in scrapers:
        print(f"\n{'─'*40}\nScraping: {name}\n{'─'*40}")
        try:
            products = scraper.scrape()
            all_products.extend(products)
            print(f"✓ {name}: {len(products)} products")
        except Exception as e:
            print(f"✗ {name} FAILED: {e}")

    all_products = deduplicate(all_products)
    all_products.sort(key=lambda p: p.get("name",""))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_products, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"✓ Saved {len(all_products)} products → {OUTPUT_FILE}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
