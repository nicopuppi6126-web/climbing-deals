import requests
import json
import os
import csv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date

# ── CONFIG ────────────────────────────────────────────────────────────────────

RECIPIENT_EMAIL = "nicopuppi6126@gmail.com"
SENDER_EMAIL    = os.environ["GMAIL_ADDRESS"]   # set in GitHub secrets
SENDER_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]  # set in GitHub secrets

MIN_DISCOUNT_PCT = 20   # only show deals with at least this % off
LOG_FILE         = "deals_log.csv"

STORES = [
    {
        "name": "Go Outdoors",
        "url":  "https://www.gooutdoors.co.uk",
        "collections": ["climbing"],
    },
    {
        "name": "Tiso",
        "url":  "https://www.tiso.com",
        "collections": ["climbing"],
    },
    {
        "name": "Dick's Climbing",
        "url":  "https://www.dicksclimbing.com",
        "collections": ["all"],
    },
    {
        "name": "Rock + Run",
        "url":  "https://rockrun.com",
        "collections": ["all"],
    },
    {
        "name": "Bananafingers",
        "url":  "https://bananafingers.co.uk",
        "collections": ["all"],
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

# ── SCRAPING ──────────────────────────────────────────────────────────────────

def fetch_collection(store_url, collection, page=1):
    """Fetch one page of products from a Shopify collection JSON endpoint."""
    url = f"{store_url}/collections/{collection}/products.json?limit=250&page={page}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.json().get("products", [])
    except Exception as e:
        print(f"  ⚠ Failed to fetch {url}: {e}")
        return []

def get_deals(store):
    deals = []
    for collection in store["collections"]:
        print(f"  Checking {store['name']} / {collection} ...")
        page = 1
        while True:
            products = fetch_collection(store["url"], collection, page)
            if not products:
                break
            for product in products:
                for variant in product.get("variants", []):
                    price         = float(variant.get("price") or 0)
                    compare_price = float(variant.get("compare_at_price") or 0)
                    if compare_price > price > 0:
                        discount_pct = round((1 - price / compare_price) * 100)
                        if discount_pct >= MIN_DISCOUNT_PCT:
                            title = product["title"]
                            if variant.get("title") and variant["title"].lower() != "default title":
                                title += f" — {variant['title']}"
                            deals.append({
                                "store":        store["name"],
                                "product":      title,
                                "price":        f"£{price:.2f}",
                                "was":          f"£{compare_price:.2f}",
                                "discount_pct": discount_pct,
                                "url":          f"{store['url']}/products/{product['handle']}",
                                "date":         str(date.today()),
                            })
            # Shopify returns fewer than 250 when it's the last page
            if len(products) < 250:
                break
            page += 1
    return deals

# ── LOGGING ───────────────────────────────────────────────────────────────────

def log_deals(deals):
    """Append today's deals to the CSV log (creates file + header if missing)."""
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["date", "store", "product", "price", "was", "discount_pct", "url"]
        )
        if not file_exists:
            writer.writeheader()
        writer.writerows(deals)
    print(f"  ✔ Logged {len(deals)} deals to {LOG_FILE}")

# ── EMAIL ─────────────────────────────────────────────────────────────────────

def build_email_html(deals, today):
    if not deals:
        return f"<p>No deals found today ({today}) matching your criteria (≥{MIN_DISCOUNT_PCT}% off).</p>"

    # Group by store
    by_store = {}
    for d in deals:
        by_store.setdefault(d["store"], []).append(d)

    rows = ""
    for store, items in sorted(by_store.items()):
        items_sorted = sorted(items, key=lambda x: x["discount_pct"], reverse=True)
        for d in items_sorted:
            rows += f"""
            <tr>
                <td style="padding:8px;border-bottom:1px solid #eee;">{d['store']}</td>
                <td style="padding:8px;border-bottom:1px solid #eee;">
                    <a href="{d['url']}" style="color:#1a6bcc;text-decoration:none;">{d['product']}</a>
                </td>
                <td style="padding:8px;border-bottom:1px solid #eee;text-align:right;">{d['price']}</td>
                <td style="padding:8px;border-bottom:1px solid #eee;text-align:right;color:#999;text-decoration:line-through;">{d['was']}</td>
                <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;">
                    <span style="background:#d4edda;color:#155724;padding:3px 8px;border-radius:4px;font-weight:bold;">
                        -{d['discount_pct']}%
                    </span>
                </td>
            </tr>"""

    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:800px;margin:auto;color:#333;">
        <h2 style="color:#1a6bcc;">🧗 Climbing Deals — {today}</h2>
        <p>{len(deals)} deals found across {len(by_store)} stores (≥{MIN_DISCOUNT_PCT}% off)</p>
        <table style="width:100%;border-collapse:collapse;">
            <thead>
                <tr style="background:#f5f5f5;text-align:left;">
                    <th style="padding:8px;">Store</th>
                    <th style="padding:8px;">Product</th>
                    <th style="padding:8px;text-align:right;">Sale price</th>
                    <th style="padding:8px;text-align:right;">Was</th>
                    <th style="padding:8px;text-align:center;">Saving</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
        <p style="margin-top:24px;color:#999;font-size:12px;">
            Tracked daily · deals_log.csv in your GitHub repo has the full history
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

    print(f"\nTotal deals found: {len(all_deals)}")
    log_deals(all_deals)
    send_email(all_deals, today)
    print("\nDone ✔\n")

if __name__ == "__main__":
    main()
