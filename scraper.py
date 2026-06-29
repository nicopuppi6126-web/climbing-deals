import requests
import os
import csv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date
import re

# ── CONFIG ────────────────────────────────────────────────────────────────────

RECIPIENT_EMAIL = "nicopuppi6126@gmail.com"
SENDER_EMAIL    = os.environ["GMAIL_ADDRESS"]
SENDER_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]

MIN_DISCOUNT_PCT = 20
LOG_FILE         = "deals_log.csv"
VAT_MULTIPLIER   = 1.20

STORES = [
    {
        "name": "Go Outdoors",
        "url":  "https://www.gooutdoors.co.uk",
        "collections": ["climbing-sale", "sale-climbing"],
        "sale_collection": True,
        "min_price": 5.0,
        "prices_ex_vat": False,
    },
    {
        "name": "Tiso",
        "url":  "https://www.tiso.com",
        "collections": ["sale"],
        "sale_collection": True,
        "min_price": 5.0,
        "prices_ex_vat": False,
    },
    {
        "name": "Dick's Climbing",
        "url":  "https://www.dicksclimbing.com",
        "collections": ["all"],
        "sale_collection": False,
        "min_price": 1.0,
        "prices_ex_vat": True,
    },
    {
        "name": "Rock + Run",
        "url":  "https://rockrun.com",
        "collections": ["outlet"],
        "sale_collection": False,
        "min_price": 1.0,
        "prices_ex_vat": False,
    },
    {
        "name": "Bananafingers",
        "url":  "https://bananafingers.co.uk",
        "collections": ["bargain-bin", "bargain-of-the-day", "summer-sale-collection", "last-season-s"],
        "sale_collection": False,
        "min_price": 1.0,
        "prices_ex_vat": False,
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

# ── CATEGORISATION ────────────────────────────────────────────────────────────
# Each category is (display_name, list_of_keywords).
# The FIRST matching category wins, so order matters —
# shoes must come before the clothing EXCLUDE block.
# Products that match EXCLUDE_CLOTHING and no earlier category are dropped.

CATEGORIES = [
    ("👟 Footwear", [
        "climbing shoe", "climbing boot", "approach shoe", "approach boot",
        "bouldering shoe", "rock shoe", "scarpa", "la sportiva", "boreal",
        "evolv", "mad rock", "five ten", "unparallel", "tenaya", "red chili",
        "mythos", "vapor", "solution", "finale", "miura", "katana",
        "futura", "skwama", "instinct", "testarossa", "genius", "drago",
    ]),
    ("⚙️ Hardware", [
        "carabiner", "karabiner", "quickdraw", "quick draw", "draw",
        "cam", "friend", "nut ", " nut,", "stopper", "hex ", "tricam",
        "belay device", "belay plate", "atc", "grigri", "reverso",
        "descender", "figure 8", "ascender", "jumar", "pulley",
        "anchor", "connector", "maillon", "snapgate", "wiregate",
        "screwgate", "autolock", "triact", "magnetron",
        "petzl", "black diamond", "dmm", "wild country", "camp ",
        "mammut", "edelrid", "kong", "climbing technology",
    ]),
    ("🪢 Ropes & Slings", [
        "rope", "cord", "sling", "runner", "quicksling", "dyneema",
        "spectra", "webbing", "tape sling", "alpine draw",
    ]),
    ("🪖 Protection & Safety", [
        "helmet", "crash pad", "bouldering mat", "landing pad",
    ]),
    ("🎒 Bags & Packs", [
        "chalk bag", "chalk bucket", "rope bag", "rope tarp",
        "haul bag", "crag bag", "climbing bag", "gear bag",
        "climbing pack", "climbing rucksack",
    ]),
    ("🧴 Accessories & Training", [
        "chalk", "liquid chalk", "chalk ball",
        "fingerboard", "hangboard", "campus board", "training board",
        "crimp", "hold", "pulley system",
        "tape", "climbing tape", "finger tape",
        "brush", "cleaning brush", "tick mark",
        "crampon", "ice axe", "ice tool",
        "harness", "sit harness", "chest harness", "full body harness",
        "via ferrata", "via-ferrata",
        "clip stick", "stick clip", "bolt", "anchor kit",
        "guidebook", "guide book",
        "boot banana", "gear sling",
    ]),
]

# Words that identify clothing to EXCLUDE.
# Uses word-boundary regex so "pant" matches "Pant"/"Pants" but not "important",
# "tank" matches "Tank Top" but not "titanium", etc.
CLOTHING_WORDS = [
    "jacket", "fleece", "softshell", "hardshell", "windshell",
    "trouser", "trousers", "pant", "pants", "legging", "leggings",
    "short", "shorts", "base layer", "baselayer", "mid layer", "midlayer",
    "t-shirt", "tshirt", "shirt", "polo", "hoodie", "hoody",
    "sweatshirt", "jumper", "sweater", "gilet", "vest", "puffer",
    "sock", "socks", "glove", "gloves", "gaiter", "gaiters",
    "balaclava", "beanie", "hat", "buff", "neck gaiter", "headband",
    "underwear", "brief", "boxer", "jogger", "joggers", "tights",
    "tank", "tee", "insulated",
]

_CLOTHING_RE = re.compile(
    r'\b(' + '|'.join(re.escape(w) for w in CLOTHING_WORDS) + r')\b',
    re.IGNORECASE
)

def categorise(product_name):
    """Return category label, or None if the product should be excluded."""
    name_lower = product_name.lower()

    # Check keep-categories first (shoes, hardware, etc.)
    for cat_label, keywords in CATEGORIES:
        if any(kw in name_lower for kw in keywords):
            return cat_label

    # Clothing check uses word-boundary regex — no trailing-space tricks needed
    if _CLOTHING_RE.search(product_name):
        return None  # drop it

    return "🔧 Other Gear"

# ── SCRAPING ──────────────────────────────────────────────────────────────────

def fetch_collection(store_url, collection, page=1):
    url = f"{store_url}/collections/{collection}/products.json?limit=250&page={page}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.json().get("products", [])
    except Exception as e:
        print(f"  ⚠ Failed {url}: {e}")
        return []

def get_deals(store):
    deals = []
    seen = set()

    vat     = VAT_MULTIPLIER if store["prices_ex_vat"] else 1.0
    is_sale = store["sale_collection"]
    min_price = store["min_price"]

    for collection in store["collections"]:
        print(f"  Checking {store['name']} / {collection} ...")
        page = 1
        while True:
            products = fetch_collection(store["url"], collection, page)
            if not products:
                break
            for product in products:
                # Check category before processing variants (saves time)
                category = categorise(product["title"])
                if category is None:
                    continue  # clothing — skip

                for variant in product.get("variants", []):
                    vid = variant.get("id")
                    if vid in seen:
                        continue
                    seen.add(vid)

                    raw_price   = float(variant.get("price") or 0)
                    raw_compare = float(variant.get("compare_at_price") or 0)
                    price   = round(raw_price   * vat, 2)
                    compare = round(raw_compare * vat, 2)

                    if price < min_price:
                        continue

                    if is_sale:
                        if compare > price > 0:
                            discount_pct = round((1 - price / compare) * 100)
                            was_str = f"£{compare:.2f}"
                        else:
                            discount_pct = 0
                            was_str = "—"
                    else:
                        if not (compare > price > 0):
                            continue
                        discount_pct = round((1 - price / compare) * 100)
                        if discount_pct < MIN_DISCOUNT_PCT:
                            continue
                        was_str = f"£{compare:.2f}"

                    title = product["title"]
                    if variant.get("title") and variant["title"].lower() != "default title":
                        title += f" — {variant['title']}"

                    deals.append({
                        "store":        store["name"],
                        "product":      title,
                        "category":     category,
                        "price":        f"£{price:.2f}",
                        "was":          was_str,
                        "discount_pct": discount_pct,
                        "url":          f"{store['url']}/products/{product['handle']}",
                        "date":         str(date.today()),
                    })

            if len(products) < 250:
                break
            page += 1

    return deals

# ── LOGGING ───────────────────────────────────────────────────────────────────

def log_deals(deals):
    # Overwrite each run — the CSV always reflects today's deals only
    with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["date", "store", "category", "product", "price", "was", "discount_pct", "url"]
        )
        writer.writeheader()
        writer.writerows(deals)
    print(f"  ✔ Saved {len(deals)} deals to {LOG_FILE}")

# ── EMAIL ─────────────────────────────────────────────────────────────────────

def build_email_html(deals, today):
    if not deals:
        return f"<p>No relevant climbing deals found today ({today}) matching criteria.</p>"

    # Group by category, then sort within each by discount
    by_category = {}
    for d in deals:
        by_category.setdefault(d["category"], []).append(d)

    # Category display order
    cat_order = [
        "⚙️ Hardware",
        "👟 Footwear",
        "🪢 Ropes & Slings",
        "🪖 Protection & Safety",
        "🎒 Bags & Packs",
        "🧴 Accessories & Training",
        "🔧 Other Gear",
    ]

    sections = ""
    for cat in cat_order:
        if cat not in by_category:
            continue
        items = sorted(by_category[cat], key=lambda x: x["discount_pct"], reverse=True)
        rows = ""
        for d in items:
            discount_badge = (
                f'<span style="background:#d4edda;color:#155724;padding:2px 7px;'
                f'border-radius:4px;font-weight:bold;font-size:12px;">-{d["discount_pct"]}%</span>'
                if d["discount_pct"] > 0 else
                '<span style="color:#999;font-size:12px;">sale</span>'
            )
            rows += f"""
            <tr>
                <td style="padding:7px 8px;border-bottom:1px solid #f0f0f0;font-size:13px;color:#555;">{d['store']}</td>
                <td style="padding:7px 8px;border-bottom:1px solid #f0f0f0;font-size:13px;">
                    <a href="{d['url']}" style="color:#1a6bcc;text-decoration:none;">{d['product']}</a>
                </td>
                <td style="padding:7px 8px;border-bottom:1px solid #f0f0f0;text-align:right;font-weight:bold;font-size:13px;white-space:nowrap;">{d['price']}</td>
                <td style="padding:7px 8px;border-bottom:1px solid #f0f0f0;text-align:right;color:#aaa;text-decoration:line-through;font-size:12px;white-space:nowrap;">{d['was']}</td>
                <td style="padding:7px 8px;border-bottom:1px solid #f0f0f0;text-align:center;">{discount_badge}</td>
            </tr>"""

        sections += f"""
        <h3 style="margin:24px 0 6px;color:#333;font-size:15px;">{cat} <span style="font-weight:normal;color:#999;font-size:13px;">({len(items)} deals)</span></h3>
        <table style="width:100%;border-collapse:collapse;margin-bottom:8px;">
            <thead>
                <tr style="background:#f8f8f8;text-align:left;">
                    <th style="padding:6px 8px;font-size:12px;color:#888;font-weight:600;">Store</th>
                    <th style="padding:6px 8px;font-size:12px;color:#888;font-weight:600;">Product</th>
                    <th style="padding:6px 8px;font-size:12px;color:#888;font-weight:600;text-align:right;">Price</th>
                    <th style="padding:6px 8px;font-size:12px;color:#888;font-weight:600;text-align:right;">Was</th>
                    <th style="padding:6px 8px;font-size:12px;color:#888;font-weight:600;text-align:center;">Saving</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>"""

    store_counts = {}
    for d in deals:
        store_counts[d["store"]] = store_counts.get(d["store"], 0) + 1
    store_summary = " · ".join(f"{s}: {n}" for s, n in sorted(store_counts.items()))

    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:820px;margin:auto;color:#333;padding:16px;">
        <h2 style="color:#1a6bcc;margin-bottom:4px;">🧗 Climbing Deals — {today}</h2>
        <p style="margin:0 0 4px;color:#555;">{len(deals)} deals found · no clothing included</p>
        <p style="margin:0 0 16px;color:#999;font-size:12px;">{store_summary}</p>
        {sections}
        <p style="margin-top:24px;color:#bbb;font-size:11px;">
            All prices include UK VAT · Full history in deals_log.csv in your GitHub repo
        </p>
    </body></html>
    """

def send_email(deals, today):
    subject = f"🧗 Climbing Deals {today} — {len(deals)} found"
    html    = build_email_html(deals, today)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = RECIPIENT_EMAIL
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
    print(f"  ✔ Email sent to {RECIPIENT_EMAIL}")

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    today = str(date.today())
    print(f"\n🧗 Climbing Deals Scraper — {today}\n")

    all_deals = []
    for store in STORES:
        deals = get_deals(store)
        print(f"  → {len(deals)} relevant deals at {store['name']}")
        all_deals.extend(deals)

    all_deals.sort(key=lambda x: x["discount_pct"], reverse=True)

    print(f"\nTotal relevant deals: {len(all_deals)}")
    log_deals(all_deals)
    send_email(all_deals, today)
    print("\nDone ✔\n")

if __name__ == "__main__":
    main()
