"""
PriceWatch GR — Scraper v6
Στρατηγική:
  1. Open Food Facts Greek export → product catalog με EAN
  2. AB Vassilopoulos Playwright → τιμές με EAN
  3. MyMarket Playwright → τιμές με fuzzy name matching
  4. Cross-chain price comparison μέσω EAN matching
"""

import json, time, random, re, csv, io, gzip
from datetime import date, timedelta
from pathlib import Path
import requests

OUTPUT_DIR  = Path("data")
OUTPUT_FILE = OUTPUT_DIR / "prices.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/125.0.0.0 Safari/537.36")

EMOJI = {
    "dairy":"🥛","bread":"🍞","pasta":"🍝","oil":"🫒","canned":"🥫",
    "coffee":"☕","drinks":"🥤","cleaning":"🧼","personal":"🧴",
    "frozen":"🧊","meat":"🥩","cheese":"🧀","eggs":"🥚","snacks":"🍿",
    "sweets":"🍫","baby":"🍼","other":"📦",
}

# Mapping από OFF categories → μας
OFF_CAT_MAP = {
    "en:dairy":          "dairy",
    "en:milks":          "dairy",
    "en:yogurts":        "dairy",
    "en:cheeses":        "cheese",
    "en:meats":          "meat",
    "en:breads":         "bread",
    "en:frozen-foods":   "frozen",
    "en:beverages":      "drinks",
    "en:waters":         "drinks",
    "en:coffees":        "coffee",
    "en:pastas":         "pasta",
    "en:oils":           "oil",
    "en:canned-foods":   "canned",
    "en:snacks":         "snacks",
    "en:chocolates":     "sweets",
    "en:biscuits":       "snacks",
    "en:cleaning-agents":"cleaning",
    "en:baby-foods":     "baby",
}

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

def normalize_name(name):
    """Κανονικοποίηση για fuzzy matching."""
    return re.sub(r'\s+', ' ', name.lower().strip())

def fuzzy_match(name1, name2, threshold=0.6):
    """Απλό token-based similarity."""
    t1 = set(normalize_name(name1).split())
    t2 = set(normalize_name(name2).split())
    if not t1 or not t2: return 0
    inter = t1 & t2
    return len(inter) / max(len(t1), len(t2))

def make_browser(pw):
    return pw.chromium.launch(
        headless=True,
        args=["--no-sandbox","--disable-blink-features=AutomationControlled",
              "--disable-dev-shm-usage"]
    )

def make_context(browser):
    return browser.new_context(
        user_agent=UA, locale="el-GR",
        viewport={"width":1280,"height":800},
        extra_http_headers={"Accept-Language":"el-GR,el;q=0.9,en;q=0.8"},
    )

def accept_cookies(page):
    for t in ("Αποδοχή","Accept","OK","Συμφωνώ","ΑΠΟΔΟΧΗ"):
        try:
            btn = page.get_by_text(t, exact=False).first
            if btn.is_visible(timeout=2000): btn.click(); time.sleep(0.5); return
        except: pass

def scroll_load(page, times=4, delay_ms=500):
    for _ in range(times):
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        page.wait_for_timeout(delay_ms)


# ════════════════════════════════════════════════════════════════
# STEP 1: Open Food Facts — Greek products catalog
# ════════════════════════════════════════════════════════════════
class OFFCatalog:
    """
    Κατεβάζει το Greek products export από Open Food Facts.
    Επιστρέφει dict: EAN -> product info
    """
    # Μικρό filtered export για Ελλάδα
    API_URL = "https://world.openfoodfacts.org/api/v2/search"

    GREEK_BRANDS = [
        "ΔΕΛΤΑ","ΜΕΒΓΑΛ","ΟΛΥΜΠΟΣ","ΑΓΝΟ","ΦΑΓΕ","ΔΩΔΩΝΗ",
        "BARBA STATHIS","ΧΡΥΣΗ ΖΥΜΗ","ΠΑΠΑΔΟΠΟΥΛΟΣ","CHIPITA",
        "ΒΙΤΑΚ","ΑΛΛΑΤΙΝΗ","JOTIS","ΜΠΑΡΜΠΑ ΣΤΑΘΗΣ",
        "ΚΡΗΤΙΚΟΣ","ΚΑΛΑΜΠΟΚΑΣ","ΤΥΡΑΣ",
    ]

    CATEGORIES = [
        "dairy-products", "cheeses", "meats", "breads",
        "frozen-foods", "beverages", "coffees", "pastas",
        "oils-and-fats", "canned-foods", "snacks", "chocolates",
        "cleaning-products", "baby-foods",
    ]

    def fetch(self, max_products=5000):
        catalog = {}
        session = requests.Session()
        session.headers.update({"User-Agent": "PriceWatchGR/1.0 (contact@pricewatch.gr)"})

        print("  [OFF] Fetching Greek product catalog...")

        for category in self.CATEGORIES:
            page = 1
            cat_count = 0
            while cat_count < 500:
                try:
                    r = session.get(self.API_URL, params={
                        "categories_tags": f"en:{category}",
                        "countries_tags": "en:greece",
                        "fields": "code,product_name,product_name_el,brands,categories_tags,image_url,quantity",
                        "page": page,
                        "page_size": 100,
                        "json": "true",
                    }, timeout=20)
                    r.raise_for_status()
                    data = r.json()
                    products = data.get("products", [])
                    if not products: break

                    for p in products:
                        ean = p.get("code","").strip()
                        name = (p.get("product_name_el") or p.get("product_name","")).strip()
                        if not ean or not name or len(ean) < 8: continue

                        # Map category
                        cat_tags = p.get("categories_tags", [])
                        cat_key = "other"
                        for tag in cat_tags:
                            if tag in OFF_CAT_MAP:
                                cat_key = OFF_CAT_MAP[tag]
                                break

                        catalog[ean] = {
                            "ean": ean,
                            "name": name,
                            "brand": p.get("brands","").split(",")[0].strip(),
                            "category": cat_key,
                            "emoji": EMOJI.get(cat_key, "📦"),
                            "image_url": p.get("image_url",""),
                            "quantity": p.get("quantity",""),
                        }
                        cat_count += 1

                    if len(products) < 100: break
                    page += 1
                    time.sleep(0.5)  # Polite για OFF

                except Exception as e:
                    print(f"    [OFF] Error {category} p{page}: {e}")
                    break

            print(f"    [OFF] {category}: {cat_count} products")
            if len(catalog) >= max_products: break

        print(f"  [OFF] Total catalog: {len(catalog)} products")
        return catalog


# ════════════════════════════════════════════════════════════════
# STEP 2: AB Vassilopoulos — τιμές με EAN (Playwright)
# ════════════════════════════════════════════════════════════════
class ABScraper:
    BASE = "https://www.ab.gr"
    HASH = "189e7cb5a6ba93e55dc63e4eef0ad063ca3e8aedb0bdf2a58124e02d5d5d69a2"

    CATS = [
        ("003001","dairy"),("003002","dairy"),("003003","dairy"),
        ("003004","dairy"),("003005","eggs"),("004","cheese"),
        ("005","meat"),("006","bread"),("007","frozen"),
        ("008","drinks"),("009","coffee"),("010","canned"),
        ("011","pasta"),("012","oil"),("013","snacks"),
        ("014","cleaning"),("015","personal"),("016","baby"),
    ]

    FETCH_JS = """async (catCode, hash, pageNum) => {
        const vars = JSON.stringify({
            lang:'gr', searchQuery:'', category:catCode,
            pageNumber:pageNum, pageSize:60, filterFlag:true,
            fields:'PRODUCT_TILE', plainChildCategories:true
        });
        const ext = JSON.stringify({persistedQuery:{version:1,sha256Hash:hash}});
        const url = `/api/v1/?operationName=GetCategoryProductSearch` +
            `&variables=${encodeURIComponent(vars)}` +
            `&extensions=${encodeURIComponent(ext)}`;
        try {
            const r = await fetch(url, {headers:{
                'content-type':'application/json',
                'x-apollo-operation-name':'GetCategoryProductSearch',
                'apollo-require-preflight':'true'
            }});
            if (!r.ok) return {error: r.status};
            const d = await r.json();
            const s = d?.data?.categoryProductSearch || {};
            return {
                products: s.products || [],
                totalPages: s.pagination?.totalPages || 1,
            };
        } catch(e) { return {error: String(e)}; }
    }"""

    def scrape(self):
        from playwright.sync_api import sync_playwright
        results = {}  # EAN -> price info

        with sync_playwright() as pw:
            browser = make_browser(pw)
            ctx     = make_context(browser)
            page    = ctx.new_page()
            page.set_default_timeout(30000)

            print("  [AB] Init...")
            page.goto(f"{self.BASE}/el/eshop", wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            accept_cookies(page)

            for cat_code, cat_key in self.CATS:
                print(f"  [AB] {cat_code}...", end=" ", flush=True)
                cat_count, page_num = 0, 0

                # Navigate στη category page για context
                try:
                    page.goto(f"{self.BASE}/el/eshop/c/{cat_code}",
                              wait_until="domcontentloaded")
                    page.wait_for_timeout(1000)
                except: pass

                while page_num < 15:
                    try:
                        res = page.evaluate(self.FETCH_JS, cat_code, self.HASH, page_num)
                        if res.get("error"):
                            print(f"ERR:{res['error']}")
                            break

                        items = res.get("products", [])
                        total_pages = res.get("totalPages", 1)

                        for item in items:
                            ean  = item.get("ean","").strip()
                            code = item.get("code","").strip()
                            name = item.get("name","").strip()
                            if not name: continue

                            price = safe_float((item.get("price") or {}).get("value"))
                            if price <= 0: continue

                            is_offer, was = False, None
                            for promo in (item.get("potentialPromotions") or []):
                                pv = (promo.get("price") or {}).get("value")
                                if pv: was=price; price=safe_float(pv); is_offer=True; break

                            ppu  = item.get("pricePerUnit") or {}
                            imgs = item.get("images") or []
                            img  = imgs[0].get("url","") if imgs else ""
                            if img and not img.startswith("http"): img = self.BASE + img

                            entry = {
                                "chain":"ab","chain_sku":code,
                                "name":name,
                                "brand":(item.get("brand") or {}).get("name"),
                                "ean":ean or None,
                                "category":cat_key,"emoji":EMOJI.get(cat_key,"📦"),
                                "unit":ppu.get("unit"),
                                "price":price,
                                "price_per_unit":safe_float(ppu.get("value")) or None,
                                "is_offer":is_offer,"offer_original_price":was,
                                "image_url":img,
                                "url":f"{self.BASE}/el/eshop/p/{code}",
                                "scraped_at":today(),
                                "history":make_history(price),
                            }

                            # Index by EAN αν υπάρχει, αλλιώς by name
                            key = ean if ean else f"ab_name_{normalize_name(name)}"
                            results[key] = entry
                            cat_count += 1

                        if page_num >= total_pages - 1: break
                        page_num += 1
                        time.sleep(random.uniform(0.8, 1.5))

                    except Exception as e:
                        print(f"ERR:{e}"); break

                print(f"{cat_count} products")

            browser.close()

        print(f"  [AB] Total: {len(results)} products")
        return results


# ════════════════════════════════════════════════════════════════
# STEP 3: MyMarket — τιμές (Playwright)
# ════════════════════════════════════════════════════════════════
class MyMarketScraper:
    BASE = "https://www.mymarket.gr"

    QUERIES = [
        ("γάλα","dairy"),("γιαούρτι","dairy"),("τυρί","cheese"),
        ("φέτα","cheese"),("αλλαντικά","cheese"),("κοτόπουλο","meat"),
        ("μοσχάρι","meat"),("ψωμί","bread"),("κατεψυγμένα","frozen"),
        ("αναψυκτικά","drinks"),("νερό","drinks"),("χυμός","drinks"),
        ("καφές","coffee"),("ζυμαρικά","pasta"),("ρύζι","pasta"),
        ("ελαιόλαδο","oil"),("τόνος","canned"),("κονσέρβα","canned"),
        ("απορρυπαντικό","cleaning"),("σαμπουάν","personal"),
        ("σοκολάτα","sweets"),("μπισκότα","snacks"),
    ]

    EXTRACT_JS = """() => {
        const cards = [...document.querySelectorAll('.product--teaser')];
        return cards.map(card => {
            const name = card.querySelector(
                '[class*="display-name"],[class*="product-name"],h2,h3'
            )?.textContent?.trim() || '';
            if (!name || name.length < 3) return null;

            const priceText = card.querySelector('[class*="price"]')?.textContent || '';
            const pm = priceText.replace(/\s+/g,' ').match(/(\d+)\s+(\d{2})(?!\d)/);
            let price = 0;
            if (pm) price = parseFloat(pm[1] + '.' + pm[2]);
            if (!price) {
                const fm = priceText.match(/(\d+)[,\.](\d{2})\s*€/);
                if (fm) price = parseFloat(fm[1] + '.' + fm[2]);
            }
            if (!price || price <= 0) return null;

            const oldEl = card.querySelector('[class*="old"],[class*="was"],s,del');
            const oldText = oldEl?.textContent || '';
            const om = oldText.match(/(\d+)[,\.](\d{2})/);
            const oldPrice = om ? parseFloat(om[1]+'.'+om[2]) : null;

            const link = card.querySelector('a')?.href || '';
            const img  = card.querySelector('img')?.src || '';
            const slug = link.split('/').filter(Boolean).pop() || '';
            const codeEl = [...card.querySelectorAll('*')]
                .find(e => e.children.length===0 && e.textContent.includes('Κωδ:'));
            const code = codeEl?.textContent?.replace('Κωδ:','').trim() || slug;

            return {name, price, oldPrice, code, link, img};
        }).filter(Boolean);
    }"""

    def scrape(self):
        from playwright.sync_api import sync_playwright
        results = {}  # name_key -> price info
        seen = set()

        with sync_playwright() as pw:
            browser = make_browser(pw)
            ctx     = make_context(browser)
            page    = ctx.new_page()
            page.set_default_timeout(30000)

            print("  [MyMarket] Init...")
            page.goto(self.BASE, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            accept_cookies(page)
            page.wait_for_timeout(500)

            for query, cat_key in self.QUERIES:
                print(f"  [MyMarket] '{query}'...", end=" ", flush=True)
                try:
                    page.goto(f"{self.BASE}/search?text={query}",
                              wait_until="domcontentloaded")
                    page.wait_for_timeout(2500)
                    scroll_load(page, times=4, delay_ms=500)

                    items = page.evaluate(self.EXTRACT_JS)
                    count = 0
                    for item in (items or []):
                        code = str(item.get("code","")).strip()
                        name = str(item.get("name","")).strip()
                        if not name or code in seen: continue
                        if code: seen.add(code)

                        price    = float(item.get("price", 0))
                        old      = item.get("oldPrice")
                        is_offer = old is not None and float(old) > price

                        entry = {
                            "chain":"mymarket","chain_sku":code,
                            "name":name,"brand":None,"ean":None,
                            "category":cat_key,"emoji":EMOJI.get(cat_key,"📦"),
                            "unit":None,"price":round(price,2),
                            "price_per_unit":None,
                            "is_offer":is_offer,
                            "offer_original_price":round(float(old),2) if is_offer else None,
                            "image_url":str(item.get("img","")),
                            "url":str(item.get("link","")),
                            "scraped_at":today(),
                            "history":make_history(price),
                        }
                        # Index by normalized name για fuzzy matching
                        name_key = f"mym_name_{normalize_name(name)}"
                        results[name_key] = entry
                        count += 1

                    print(f"{count} products")
                    time.sleep(random.uniform(1.0, 2.0))

                except Exception as e:
                    print(f"ERR:{e}")

            browser.close()

        print(f"  [MyMarket] Total: {len(results)} products")
        return results


# ════════════════════════════════════════════════════════════════
# STEP 4: Cross-chain matching & merge
# ════════════════════════════════════════════════════════════════
def merge_products(off_catalog, ab_products, mym_products):
    """
    Δημιουργεί unified product list με τιμές ανά αλυσίδα.
    Matching strategy:
      1. EAN exact match (AB has EAN)
      2. Name fuzzy match (MyMarket)
    """
    print("\n[Merge] Starting cross-chain matching...")
    final = []

    # Build AB index by EAN and by name
    ab_by_ean  = {v["ean"]:v for v in ab_products.values() if v.get("ean")}
    ab_by_name = {normalize_name(v["name"]):v for v in ab_products.values()}

    # Build MyMarket index by name
    mym_by_name = {normalize_name(v["name"]):v for v in mym_products.values()}
    mym_names   = list(mym_by_name.keys())

    processed_eans = set()
    processed_names = set()

    # --- Pass 1: OFF catalog products ---
    for ean, off_prod in off_catalog.items():
        name_norm = normalize_name(off_prod["name"])
        chains = {}

        # AB by EAN
        if ean in ab_by_ean:
            chains["ab"] = ab_by_ean[ean]
            processed_eans.add(ean)

        # MyMarket by fuzzy name
        best_mym_score = 0
        best_mym = None
        for mym_name, mym_prod in mym_by_name.items():
            score = fuzzy_match(off_prod["name"], mym_prod["name"])
            if score > best_mym_score and score >= 0.65:
                best_mym_score = score
                best_mym = mym_prod

        if best_mym:
            chains["mymarket"] = best_mym

        if not chains: continue  # Δεν βρήκαμε τιμές πουθενά

        # Δημιουργία unified product
        product = {
            "ean": ean,
            "name": off_prod["name"],
            "brand": off_prod.get("brand") or (chains.get("ab") or {}).get("brand"),
            "category": off_prod["category"],
            "emoji": off_prod["emoji"],
            "image_url": (off_prod.get("image_url") or
                         (chains.get("ab") or {}).get("image_url","")),
            "quantity": off_prod.get("quantity",""),
            "scraped_at": today(),
            "chains": {}
        }

        for chain_name, chain_data in chains.items():
            product["chains"][chain_name] = {
                "price": chain_data["price"],
                "price_per_unit": chain_data.get("price_per_unit"),
                "unit": chain_data.get("unit"),
                "is_offer": chain_data.get("is_offer", False),
                "offer_original_price": chain_data.get("offer_original_price"),
                "url": chain_data.get("url",""),
                "history": chain_data.get("history", []),
            }

        # Flat format για συμβατότητα με το frontend
        # Κάθε chain = ξεχωριστό record
        for chain_name, chain_data in product["chains"].items():
            final.append({
                **chain_data,
                "chain": chain_name,
                "chain_sku": (chains[chain_name] or {}).get("chain_sku",""),
                "ean": ean,
                "name": product["name"],
                "brand": product["brand"],
                "category": product["category"],
                "emoji": product["emoji"],
                "image_url": product["image_url"],
                "scraped_at": today(),
            })

        processed_names.add(name_norm)

    # --- Pass 2: AB products χωρίς EAN match στο OFF ---
    for key, ab_prod in ab_products.items():
        if ab_prod.get("ean") in processed_eans: continue
        name_norm = normalize_name(ab_prod["name"])
        if name_norm in processed_names: continue
        # Πρόσθεσε ως standalone AB product
        final.append(ab_prod)
        processed_names.add(name_norm)

    # --- Pass 3: MyMarket products χωρίς match ---
    for key, mym_prod in mym_products.items():
        name_norm = normalize_name(mym_prod["name"])
        if name_norm in processed_names: continue
        final.append(mym_prod)
        processed_names.add(name_norm)

    # Stats
    matched = sum(1 for p in final if p.get("ean") and p.get("chain") in ["ab","mymarket"])
    print(f"[Merge] Total records: {len(final)}")
    print(f"[Merge] With EAN: {sum(1 for p in final if p.get('ean'))}")
    print(f"[Merge] AB: {sum(1 for p in final if p.get('chain')=='ab')}")
    print(f"[Merge] MyMarket: {sum(1 for p in final if p.get('chain')=='mymarket')}")

    return final


# ════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════
def main():
    from datetime import datetime
    print("="*60)
    print(f"PriceWatch GR Scraper v6 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("="*60)

    OUTPUT_DIR.mkdir(exist_ok=True)

    # Step 1: OFF Catalog
    print("\n── Step 1: Open Food Facts Catalog ──")
    off = OFFCatalog()
    catalog = off.fetch(max_products=8000)

    # Step 2: AB prices
    print("\n── Step 2: AB Vassilopoulos ──")
    ab = ABScraper()
    ab_products = ab.scrape()

    # Step 3: MyMarket prices
    print("\n── Step 3: My Market ──")
    mym = MyMarketScraper()
    mym_products = mym.scrape()

    # Step 4: Merge
    print("\n── Step 4: Cross-chain matching ──")
    final = merge_products(catalog, ab_products, mym_products)
    final.sort(key=lambda p: p.get("name",""))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"✓ Saved {len(final)} records → {OUTPUT_FILE}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
