import requests
import os
import csv
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date

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

# ── CATEGORIES ────────────────────────────────────────────────────────────────
# Exactly the 10 product types requested. Each keyword list is tight and
# specific — no brand names, no catch-alls. If a product doesn't clearly
# match one of these, it is dropped.

CATEGORIES = [
    ("🪢 Ropes", [
        "climbing rope", "dynamic rope", "static rope", "half rope", "twin rope",
        "dry rope", "single rope", "lead rope",
        # match " rope " / "rope," / starts with "rope" to avoid "ropework" etc
    ]),
    ("🔗 Carabiners", [
        "carabiner", "karabiner", "biner",
        "screwgate", "wiregate", "snapgate", "autolock",
        "triact", "magnetron", "ball lock", "twist lock", "screw lock",
        "hms ", " hms,", "pear-shaped", "d-shape", "oval carabiner",
    ]),
    ("⚡ Quickdraws", [
        "quickdraw", "quick draw", "express set", "sport draw",
        "alpine draw", "wire draw",
    ]),
    ("👟 Climbing Shoes", [
        "climbing shoe", "climbing boot", "rock shoe", "bouldering shoe",
        # Unambiguous model names that are shoes and nothing else
        "mythos", "vapor v", "vapor vx", "solution comp", "miura vs",
        "miura lace", "katana lace", "skwama", "futura", "testarossa",
        "genius", "drago", "tc pro", "anasazi", "tarantulace", "tarantula",
        "instinct vs", "instinct vsr", "helix", "finale", "oracle",
        "python shoe", "momentum shoe",
    ]),
    ("🔒 Harnesses", [
        "harness", "climbing harness", "sit harness", "belay harness",
        "sport harness", "trad harness", "big wall harness",
        "chest harness", "full body harness",
    ]),
    ("🛡️ Slings & Cords", [
        "sling", "runner",
        "dyneema sling", "nylon sling", "spectra sling",
        "accessory cord", "cordelette", "prussik", "prusik",
        "tape sling", "sewn sling",
    ]),
    ("⚙️ Belay Devices", [
        "belay device", "belay plate", "belay tool",
        "grigri", "gri-gri", "reverso", "atc ", " atc,",
        "mega jul", "smart alpine", "verso ",
        "assisted braking", "auto-blocking", "tube device",
    ]),
    ("🧗 Ascenders", [
        "ascender", "jumar", "hand ascender", "chest ascender",
        "micro ascender", "rope clamp", "tibloc", "ropeman",
        "basic ascender", "croll",
    ]),
    ("⬇️ Descenders", [
        "descender", "figure 8", "figure-8", "rappel device",
        "abseil device", "rack ", " rack,", "i'dwall", "id wall",
        "stop descender", "simple descender",
    ]),
]

# Build one flat set of all kept keywords for a fast first-pass check
_ALL_KEEP_PATTERNS = [kw for _, kws in CATEGORIES for kw in kws]

def categorise(product_name):
    """
    Returns category_label if the product matches one of the 10 types,
    or None if it should be dropped. No catch-all — unknown = dropped.

    Explicit type words in the product name (rope, descender, ascender,
    harness) take priority so e.g. "ATC Pilot Descender" → Descenders
    even though "atc" would normally match Belay Devices first.
    """
    name_lower = product_name.lower()

    # Priority overrides — if the product name contains these explicit type
    # words, categorise immediately without checking other keywords first.
    if re.search(r'\bdescender\b', name_lower):
        return "⬇️ Descenders"
    if re.search(r'\bascender\b', name_lower):
        return "🧗 Ascenders"
    if re.search(r'\bharness\b', name_lower):
        return "🔒 Harnesses"
    if re.search(r'\brope\b', name_lower):
        return "🪢 Ropes"

    for cat_label, keywords in CATEGORIES:
        if any(kw in name_lower for kw in keywords):
            return cat_label

    return None  # doesn't match any of the 10 types → drop it

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

    vat       = VAT_MULTIPLIER if store["prices_ex_vat"] else 1.0
    is_sale   = store["sale_collection"]
    min_price = store["min_price"]

    for collection in store["collections"]:
        print(f"  Checking {store['name']} / {collection} ...")
        page = 1
        while True:
            products = fetch_collection(store["url"], collection, page)
            if not products:
                break

            for product in products:
                category = categorise(product["title"])
                if category is None:
                    continue  # not one of our 10 types → skip

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
        return f"<p>No deals found today ({today}) across your 10 product types.</p>"

    by_category = {}
    for d in deals:
        by_category.setdefault(d["category"], []).append(d)

    cat_order = [
        "🔗 Carabiners",
        "⚡ Quickdraws",
        "🪢 Ropes",
        "🛡️ Slings & Cords",
        "🔒 Harnesses",
        "⚙️ Belay Devices",
        "🧗 Ascenders",
        "⬇️ Descenders",
        "👟 Climbing Shoes",
    ]

    sections = ""
    for cat in cat_order:
        if cat not in by_category:
            continue
        items = sorted(by_category[cat], key=lambda x: x["discount_pct"], reverse=True)
        rows = ""
        for d in items:
            badge = (
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
                <td style="padding:7px 8px;border-bottom:1px solid #f0f0f0;text-align:center;">{badge}</td>
            </tr>"""

        sections += f"""
        <h3 style="margin:24px 0 6px;color:#333;font-size:15px;">{cat}
            <span style="font-weight:normal;color:#999;font-size:13px;">({len(items)})</span>
        </h3>
        <table style="width:100%;border-collapse:collapse;margin-bottom:8px;">
            <thead>
                <tr style="background:#f8f8f8;text-align:left;">
                    <th style="padding:6px 8px;font-size:12px;color:#888;">Store</th>
                    <th style="padding:6px 8px;font-size:12px;color:#888;">Product</th>
                    <th style="padding:6px 8px;font-size:12px;color:#888;text-align:right;">Price</th>
                    <th style="padding:6px 8px;font-size:12px;color:#888;text-align:right;">Was</th>
                    <th style="padding:6px 8px;font-size:12px;color:#888;text-align:center;">Saving</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>"""

    store_counts = {}
    for d in deals:
        store_counts[d["store"]] = store_counts.get(d["store"], 0) + 1
    summary = " · ".join(f"{s}: {n}" for s, n in sorted(store_counts.items()))

    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:820px;margin:auto;color:#333;padding:16px;">
        <h2 style="color:#1a6bcc;margin-bottom:4px;">🧗 Climbing Deals — {today}</h2>
        <p style="margin:0 0 4px;color:#555;">{len(deals)} deals across {len(by_category)} categories</p>
        <p style="margin:0 0 16px;color:#999;font-size:12px;">{summary}</p>
        {sections}
        <p style="margin-top:24px;color:#bbb;font-size:11px;">
            All prices include UK VAT · Full list in deals_log.csv in your GitHub repo
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
        print(f"  → {len(deals)} deals at {store['name']}")
        all_deals.extend(deals)

    all_deals.sort(key=lambda x: x["discount_pct"], reverse=True)

    print(f"\nTotal: {len(all_deals)} deals")
    log_deals(all_deals)
    send_email(all_deals, today)
    print("\nDone ✔\n")

if __name__ == "__main__":
    main()
