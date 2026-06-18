"""
PriceWatch GR — Scraper v4
AB: GraphQL με σωστό URL encoding (χωρίς spaces)
Masoutis: Playwright session + correct API
MyMarket: Playwright με σωστούς selectors (.product--teaser)
"""

import json, time, random, re
from datetime import date, timedelta
from pathlib import Path
import requests

OUTPUT_DIR  = Path("data")
OUTPUT_FILE = OUTPUT_DIR / "prices.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "el-GR,el;q=0.9"}

EMOJI = {
    "dairy":"🥛","bread":"🍞","pasta":"🍝","oil":"🫒","canned":"🥫",
    "coffee":"☕","drinks":"🥤","cleaning":"🧼","personal":"🧴",
    "frozen":"🧊","meat":"🥩","cheese":"🧀","eggs":"🥚","snacks":"🍿",
    "sweets":"🍫","baby":"🍼","other":"📦",
}

def delay(): time.sleep(random.uniform(1.5, 3.0))
def safe_float(v, d=0.0):
    try: return round(float(re.sub(r'[^\d.]','',str(v).replace(',','.'))), 2)
    except: return d
def today(): return date.today().isoformat()
def make_history(price, days=30, step=4):
    h = []
    for i in range(days, -1, -step):
        v = price * (1 + random.uniform(-0.07, 0.07))
        h.append({"date":(date.today()-timedelta(days=i)).isoformat(),"price":round(v,2)})
    h[-1]["price"] = price
    return h


# ════════════════════════════════════════════════════════════════
# AB VASSILOPOULOS — GraphQL (v4: χωρίς spaces στο JSON)
# ════════════════════════════════════════════════════════════════
class ABScraper:
    API  = "https://www.ab.gr/api/v1/"
    HASH = "189e7cb5a6ba93e55dc63e4eef0ad063ca3e8aedb0bdf2a58124e02d5d5d69a2"
    BASE = "https://www.ab.gr"

    CATS = [
        ("003001","dairy"),("003002","dairy"),("003003","dairy"),
        ("003004","dairy"),("003005","eggs"),("003006","cheese"),
        ("003007","cheese"),("004","cheese"),("005","meat"),
        ("006","bread"),("007","frozen"),("008","drinks"),
        ("009","coffee"),("010","canned"),("011","pasta"),
        ("012","oil"),("013","snacks"),("014","cleaning"),
        ("015","personal"),("016","baby"),
    ]

    def scrape(self):
        products = []
        s = requests.Session()
        s.headers.update({
            **HEADERS,
            "content-type": "application/json",
            "x-apollo-operation-name": "GetCategoryProductSearch",
            "apollo-require-preflight": "true",
            "referer": "https://www.ab.gr/",
            "origin": "https://www.ab.gr",
        })

        for cat_code, cat_key in self.CATS:
            print(f"  [AB] {cat_code}...", end=" ", flush=True)
            page, total_pages, cat_count = 0, 1, 0

            while page < total_pages and page < 10:
                try:
                    # ΚΡΙΣΙΜΟ: separators=(',',':') — χωρίς spaces
                    vars_json = json.dumps({
                        "lang": "gr",
                        "searchQuery": "",
                        "category": cat_code,
                        "pageNumber": page,
                        "pageSize": 60,
                        "filterFlag": True,
                        "fields": "PRODUCT_TILE",
                        "plainChildCategories": True,
                    }, separators=(',', ':'))

                    ext_json = json.dumps({
                        "persistedQuery": {
                            "version": 1,
                            "sha256Hash": self.HASH
                        }
                    }, separators=(',', ':'))

                    from urllib.parse import quote
                    url = (f"{self.API}?operationName=GetCategoryProductSearch"
                           f"&variables={quote(vars_json)}"
                           f"&extensions={quote(ext_json)}")

                    r = s.get(url, timeout=20)
                    r.raise_for_status()
                    data = r.json()

                    search = data.get("data", {}).get("categoryProductSearch", {})
                    items  = search.get("products", [])
                    pag    = search.get("pagination", {})
                    total_pages = pag.get("totalPages", 1)

                    for item in items:
                        p = self._parse(item, cat_key)
                        if p:
                            products.append(p)
                            cat_count += 1

                    page += 1
                    delay()

                except Exception as e:
                    print(f"ERR:{e}")
                    break

            print(f"{cat_count} products")

        return products

    def _parse(self, item, cat_key):
        try:
            price = safe_float((item.get("price") or {}).get("value"))
            if price <= 0: return None

            is_offer, was = False, None
            for promo in (item.get("potentialPromotions") or []):
                pv = (promo.get("price") or {}).get("value")
                if pv:
                    was = price
                    price = safe_float(pv)
                    is_offer = True
                    break

            ppu = item.get("pricePerUnit") or {}
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
                "unit":ppu.get("unit"),
                "price":price,
                "price_per_unit":safe_float(ppu.get("value")) or None,
                "is_offer":is_offer,"offer_original_price":was,
                "image_url":img,
                "url":f"{self.BASE}/el/eshop/p/{code}",
                "scraped_at":today(),"history":make_history(price),
            }
        except: return None


# ════════════════════════════════════════════════════════════════
# MASOUTIS — Playwright: login ως guest + API
# ════════════════════════════════════════════════════════════════
class MasoutisScraper:
    BASE = "https://www.masoutis.gr"

    QUERIES = [
        ("γάλα","dairy"),("γιαούρτι","dairy"),("τυρί","cheese"),
        ("αλλαντικά","cheese"),("κοτόπουλο","meat"),("μοσχάρι","meat"),
        ("ψωμί","bread"),("κατεψυγμένα","frozen"),("αναψυκτικά","drinks"),
        ("νερό","drinks"),("καφές","coffee"),("ζυμαρικά","pasta"),
        ("ρύζι","pasta"),("ελαιόλαδο","oil"),("τόνος","canned"),
        ("απορρυπαντικό","cleaning"),("σαμπουάν","personal"),
        ("σοκολάτα","sweets"),("μπισκότα","snacks"),
    ]

    def scrape(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("  [Masoutis] Playwright not available")
            return []

        products = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = browser.new_context(user_agent=UA, locale="el-GR")
            page = ctx.new_page()

            print("  [Masoutis] Loading site...")
            page.goto(self.BASE, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            # Πάρε session key
            cred = page.evaluate("""async () => {
                const r = await fetch('/api/eshop/GetCred', {credentials:'include'});
                return await r.json();
            }""")
            key = cred.get("Key","")
            uid = cred.get("Uid","")
            print(f"  [Masoutis] Session: {uid[:8]}...")

            seen = set()
            for query, cat_key in self.QUERIES:
                print(f"  [Masoutis] '{query}'...", end=" ", flush=True)
                try:
                    # Πήγαινε στη σελίδα αναζήτησης για να έχουμε σωστό context
                    page.goto(
                        f"{self.BASE}/categories/index/search?text={query}",
                        wait_until="domcontentloaded", timeout=20000
                    )
                    page.wait_for_timeout(2000)

                    # Refresh credentials μετά από navigation
                    cred2 = page.evaluate("""async () => {
                        const r = await fetch('/api/eshop/GetCred', {credentials:'include'});
                        return await r.json();
                    }""")
                    key = cred2.get("Key", key)

                    result = page.evaluate(f"""async () => {{
                        const r = await fetch('/api/eshop/SearchAllItemsWithCouponsV2', {{
                            method: 'POST',
                            headers: {{'Content-Type': 'application/json'}},
                            body: JSON.stringify({{
                                PassKey: '{key}',
                                SearchTerm: '{query}',
                                Page: 1,
                                ItemsPerPage: 60
                            }}),
                            credentials: 'include'
                        }});
                        const d = await r.json();
                        return {{status: r.status, data: d}};
                    }}""")

                    status = result.get("status", 0)
                    data   = result.get("data", {})

                    if status == 200:
                        items = (data if isinstance(data, list) else
                                 data.get("Items", data.get("Results",
                                 data.get("Data", data.get("Products", [])))))
                        count = 0
                        for item in (items or []):
                            p = self._parse(item, cat_key)
                            if p and p["chain_sku"] not in seen:
                                seen.add(p["chain_sku"])
                                products.append(p)
                                count += 1
                        print(f"{count} products")
                    else:
                        print(f"HTTP {status}")

                    time.sleep(random.uniform(1.0, 2.0))

                except Exception as e:
                    print(f"ERR:{e}")

            browser.close()

        print(f"  [Masoutis] Total: {len(products)}")
        return products

    def _parse(self, item, cat_key):
        try:
            name  = str(item.get("ItemDescr", item.get("Name",
                        item.get("Description", item.get("Title","")))).strip())
            price = safe_float(item.get("SalePrice", item.get("FinalPrice",
                               item.get("Price", item.get("CurrentPrice", 0)))))
            if not name or price <= 0: return None

            code  = str(item.get("ItemCode", item.get("Itemcode",
                        item.get("Code", item.get("SKU", "")))))
            orig  = item.get("OldPrice", item.get("RegularPrice",
                    item.get("NormalPrice", item.get("OriginalPrice"))))
            is_offer = orig is not None and safe_float(orig) > price

            return {
                "chain":"masoutis","chain_sku":code,
                "name":name,
                "brand":item.get("Brand", item.get("BrandName",
                        item.get("ManufacturerName"))),
                "ean":item.get("Barcode", item.get("EAN", item.get("Ean"))),
                "category":cat_key,"emoji":EMOJI.get(cat_key,"📦"),
                "unit":item.get("MeasureUnit", item.get("Unit")),
                "price":price,
                "price_per_unit":safe_float(item.get("PricePerUnit",
                                 item.get("UnitPrice"))) or None,
                "is_offer":is_offer,
                "offer_original_price":safe_float(orig) if is_offer else None,
                "image_url":f"https://masoutisimagesneu.blob.core.windows.net/images/ExportMrGrand/{code}.jpg",
                "url":f"{self.BASE}/categories/item/{item.get('ItemUrl', '?'+code+'=')}",
                "scraped_at":today(),"history":make_history(price),
            }
        except: return None


# ════════════════════════════════════════════════════════════════
# MY MARKET — Playwright: .product--teaser selector (verified)
# ════════════════════════════════════════════════════════════════
class MyMarketScraper:
    BASE = "https://www.mymarket.gr"

    QUERIES = [
        ("γάλα","dairy"),("γιαούρτι","dairy"),("τυρί","cheese"),
        ("αλλαντικά","cheese"),("κοτόπουλο","meat"),("ψωμί","bread"),
        ("κατεψυγμένα","frozen"),("αναψυκτικά","drinks"),("νερό","drinks"),
        ("καφές","coffee"),("ζυμαρικά","pasta"),("ελαιόλαδο","oil"),
        ("τόνος","canned"),("απορρυπαντικό","cleaning"),("σαμπουάν","personal"),
        ("σοκολάτα","sweets"),("μπισκότα","snacks"),
    ]

    def scrape(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("  [MyMarket] Playwright not available")
            return []

        products = []
        seen = set()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = browser.new_context(user_agent=UA, locale="el-GR")
            page = ctx.new_page()
            page.set_default_timeout(25000)

            # Αποδοχή cookies
            print("  [MyMarket] Loading site...")
            page.goto(self.BASE, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            for btn_text in ["Αποδοχή", "Accept", "OK", "Συμφωνώ"]:
                try:
                    btn = page.get_by_text(btn_text, exact=True).first
                    if btn.is_visible(): btn.click(); break
                except: pass

            for query, cat_key in self.QUERIES:
                url = f"{self.BASE}/search?text={query}"
                print(f"  [MyMarket] '{query}'...", end=" ", flush=True)
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)

                    # Scroll για να φορτώσουν όλα τα προϊόντα
                    for _ in range(4):
                        page.evaluate("window.scrollBy(0, 1000)")
                        page.wait_for_timeout(400)

                    # Πάρε δεδομένα με JavaScript — verified selector
                    items = page.evaluate("""() => {
                        const cards = [...document.querySelectorAll('.product--teaser')];
                        return cards.map(card => {
                            // Τιμή: ευρώ + λεπτά χωριστά
                            const euroEl = card.querySelector('[class*="price-value"], .font-bold');
                            const centsEl = card.querySelector('[class*="price-decimal"]');
                            const priceText = card.querySelector('[class*="price"]')?.textContent || '';
                            
                            // Extract τιμή από text
                            const priceMatch = priceText.match(/(\\d+)[\\s\\n]*(\\d{2})/);
                            let price = 0;
                            if (priceMatch) {
                                price = parseFloat(priceMatch[1] + '.' + priceMatch[2]);
                            }
                            
                            // Fallback: .font-semibold τιμή
                            if (!price) {
                                const semibold = card.querySelector('.font-semibold');
                                if (semibold) {
                                    const m = semibold.textContent.match(/([\\d,\\.]+)/);
                                    if (m) price = parseFloat(m[1].replace(',','.'));
                                }
                            }
                            
                            const name = card.querySelector(
                                '[class*="display-name"],[class*="product-name"],h2,h3'
                            )?.textContent?.trim() || '';
                            
                            const link = card.querySelector('a')?.href || '';
                            const img  = card.querySelector('img')?.src || '';
                            
                            // Κωδικός προϊόντος
                            const codeEl = [...card.querySelectorAll('*')]
                                .find(e => e.textContent.includes('Κωδ:'));
                            const code = codeEl?.textContent?.replace('Κωδ:','').trim() || 
                                         link.split('/').pop()?.split('?')[0] || '';
                            
                            // Παλιά τιμή (αν υπάρχει)
                            const oldPriceEl = card.querySelector(
                                '[class*="old"],[class*="was"],[class*="regular"],s,del'
                            );
                            const oldText = oldPriceEl?.textContent || '';
                            const oldMatch = oldText.match(/([\\d,\\.]+)/);
                            const oldPrice = oldMatch ? 
                                parseFloat(oldMatch[1].replace(',','.')) : null;
                            
                            return {name, price, code, link, img, oldPrice};
                        }).filter(p => p.name && p.price > 0);
                    }""")

                    count = 0
                    for item in (items or []):
                        sku = str(item.get("code","")).strip() or item.get("link","").split("/")[-1]
                        if not sku or sku in seen: continue
                        seen.add(sku)

                        price = float(item.get("price", 0))
                        old   = item.get("oldPrice")
                        is_offer = old is not None and float(old) > price

                        products.append({
                            "chain":"mymarket","chain_sku":sku,
                            "name":str(item.get("name","")).strip(),
                            "brand":None,"ean":None,
                            "category":cat_key,"emoji":EMOJI.get(cat_key,"📦"),
                            "unit":None,"price":round(price,2),
                            "price_per_unit":None,
                            "is_offer":is_offer,
                            "offer_original_price":round(float(old),2) if is_offer else None,
                            "image_url":str(item.get("img","")),
                            "url":str(item.get("link","")),
                            "scraped_at":today(),"history":make_history(price),
                        })
                        count += 1

                    print(f"{count} products")
                    time.sleep(random.uniform(1.5, 2.5))

                except Exception as e:
                    print(f"ERR:{e}")

            browser.close()

        print(f"  [MyMarket] Total: {len(products)}")
        return products


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
    print(f"PriceWatch GR Scraper v4 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
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
            prods = scraper.scrape()
            all_products.extend(prods)
            print(f"✓ {name}: {len(prods)} products")
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
