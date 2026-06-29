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
HTML_FILE        = "index.html"
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
# All short or risky keywords use word-boundary regex (\b) to prevent
# substring false positives (e.g. "rack" in "SingleTrack", "sling" in "Singletrack").
# Only long, unambiguous phrases use plain substring matching.

_ROPE_DIAMETER_RE = re.compile(r'\b(7\.[5-9]|8\.[0-9]|9\.[0-9]|10\.[0-9]|10|11)mm\b', re.IGNORECASE)

# Pre-compiled word-boundary patterns for risky short keywords
_WB = {kw: re.compile(r'\b' + re.escape(kw) + r'\b', re.IGNORECASE) for kw in [
    "rack", "atc", "hms", "biner", "sling", "runner", "cord",
]}

def _wb(kw, text):
    """Word-boundary match for a keyword against text."""
    return bool(_WB[kw].search(text))

CATEGORIES = [
    ("🪢 Ropes", [
        "climbing rope", "dynamic rope", "static rope", "half rope",
        "twin rope", "dry rope", "single rope", "lead rope",
    ]),
    ("🔗 Carabiners", [
        "carabiner", "karabiner", "screwgate", "wiregate", "snapgate",
        "autolock", "triact", "magnetron", "ball lock", "twist lock",
        "screw lock", "pear-shaped", "oval carabiner",
    ]),
    ("⚡ Quickdraws", [
        "quickdraw", "quick draw", "express set", "sport draw",
        "alpine draw", "wire draw",
    ]),
    ("👟 Climbing Shoes", [
        "climbing shoe", "climbing boot", "rock shoe", "bouldering shoe",
        "mythos", "vapor v", "vapor vx", "solution comp", "miura vs",
        "miura lace", "katana lace", "skwama", "futura", "testarossa",
        "genius", "drago", "tc pro", "anasazi", "tarantulace", "tarantula",
        "instinct vs", "instinct vsr", "helix", "finale", "oracle",
        "python shoe", "momentum shoe",
    ]),
    ("🔒 Harnesses", [
        "climbing harness", "sit harness", "belay harness",
        "sport harness", "trad harness", "big wall harness",
        "chest harness", "full body harness",
    ]),
    ("🛡️ Slings & Cords", [
        "dyneema sling", "nylon sling", "spectra sling", "tape sling",
        "sewn sling", "accessory cord", "cordelette", "prussik", "prusik",
    ]),
    ("⚙️ Belay Devices", [
        "belay device", "belay plate", "belay tool",
        "grigri", "gri-gri", "reverso", "mega jul", "smart alpine",
        "assisted braking", "auto-blocking", "tube device",
    ]),
    ("🧗 Ascenders", [
        "hand ascender", "chest ascender", "micro ascender",
        "rope clamp", "tibloc", "ropeman", "basic ascender", "croll", "jumar",
    ]),
    ("⬇️ Descenders", [
        "figure 8", "figure-8", "rappel device", "abseil device",
        "stop descender", "simple descender",
    ]),
    ("🎒 Rope Bags", [
        "rope bag", "rope tarp", "rope bucket",
    ]),
]

def categorise(product_name):
    """
    Returns a category label if the product is one of the wanted types,
    or None to drop it. No catch-all.

    Priority word-boundary overrides run first so explicit type words
    always win. Risky short keywords use \b matching to prevent substring
    false positives (e.g. rack in SingleTrack, sling in Singletrack).
    """
    name_lower = product_name.lower()

    # --- Priority overrides (word-boundary) ---
    if re.search(r'\bdescender\b', name_lower): return "⬇️ Descenders"
    if re.search(r'\bascender\b',  name_lower): return "🧗 Ascenders"
    if re.search(r'\bharness\b',   name_lower): return "🔒 Harnesses"
    if 'rope bag' in name_lower or 'rope tarp' in name_lower or 'rope bucket' in name_lower: return "🎒 Rope Bags"
    if re.search(r'\brope\b',      name_lower): return "🪢 Ropes"
    if _ROPE_DIAMETER_RE.search(product_name):     return "🪢 Ropes"

    # --- Word-boundary checks for risky short keywords ---
    if _wb("rack",   name_lower): return "⬇️ Descenders"
    if _wb("hms",    name_lower): return "🔗 Carabiners"
    if _wb("biner",  name_lower): return "🔗 Carabiners"
    if _wb("atc",    name_lower): return "⚙️ Belay Devices"
    if _wb("sling",  name_lower): return "🛡️ Slings & Cords"
    if _wb("runner", name_lower): return "🛡️ Slings & Cords"
    if _wb("cord",   name_lower): return "🛡️ Slings & Cords"

    # --- Phrase keyword matching for remaining categories ---
    for cat_label, keywords in CATEGORIES:
        if any(kw in name_lower for kw in keywords):
            return cat_label

    return None  # not one of the wanted types → drop

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
                    continue

                # Grab first image if available
                image_url = ""
                images = product.get("images", [])
                if images:
                    image_url = images[0].get("src", "")

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
                        "image":        image_url,
                        "date":         str(date.today()),
                    })

            if len(products) < 250:
                break
            page += 1

    return deals

# ── LOGGING (CSV) ─────────────────────────────────────────────────────────────

def log_deals(deals):
    with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["date","store","category","product","price","was","discount_pct","url","image"]
        )
        writer.writeheader()
        writer.writerows(deals)
    print(f"  ✔ Saved {len(deals)} deals to {LOG_FILE}")

# ── HTML PAGE ─────────────────────────────────────────────────────────────────

CAT_ORDER = [
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

def build_html(deals, today):
    by_cat = {}
    for d in deals:
        by_cat.setdefault(d["category"], []).append(d)

    nav_links = ""
    for cat in CAT_ORDER:
        if cat not in by_cat:
            continue
        slug = re.sub(r'[^a-z0-9]+', '-', cat.lower()).strip('-')
        label = re.sub(r'^[^\w]+', '', cat).strip()  # strip emoji for nav
        nav_links += f'<a href="#{slug}">{label} <span class="nav-count">({len(by_cat[cat])})</span></a>\n'

    sections = ""
    for cat in CAT_ORDER:
        if cat not in by_cat:
            continue
        slug = re.sub(r'[^a-z0-9]+', '-', cat.lower()).strip('-')
        items = sorted(by_cat[cat], key=lambda x: x["discount_pct"], reverse=True)

        cards = ""
        for d in items:
            badge = (
                f'<span class="badge">-{d["discount_pct"]}%</span>'
                if d["discount_pct"] > 0 else
                '<span class="badge sale">SALE</span>'
            )
            img_html = (
                f'<img src="{d["image"]}" alt="" loading="lazy">'
                if d["image"] else
                '<div class="no-img">No image</div>'
            )
            was_html = (
                f'<span class="was">{d["was"]}</span>' if d["was"] != "—" else ""
            )
            cards += f'''
            <a class="card" href="{d["url"]}" target="_blank" rel="noopener">
                <div class="card-img">{img_html}{badge}</div>
                <div class="card-body">
                    <div class="store">{d["store"]}</div>
                    <div class="name">{d["product"]}</div>
                    <div class="pricing">
                        <span class="price">{d["price"]}</span>
                        {was_html}
                    </div>
                </div>
            </a>'''

        sections += f'''
        <section id="{slug}">
            <h2>{cat} <span class="count">({len(items)})</span></h2>
            <div class="grid">{cards}</div>
        </section>'''

    store_counts = {}
    for d in deals:
        store_counts[d["store"]] = store_counts.get(d["store"], 0) + 1
    store_summary = " &nbsp;·&nbsp; ".join(
        f"{s}: <strong>{n}</strong>" for s, n in sorted(store_counts.items())
    )

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>🧗 Climbing Deals — {today}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #f4f4f4; color: #222; }}

  header {{ background: #1a1a2e; color: #fff; padding: 20px 32px; position: sticky;
            top: 0; z-index: 100; box-shadow: 0 2px 8px rgba(0,0,0,.3); }}
  header h1 {{ font-size: 1.3rem; margin-bottom: 4px; }}
  header .meta {{ font-size: .8rem; color: #aaa; margin-bottom: 12px; }}
  nav {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  nav a {{ background: #ffffff18; color: #ddd; text-decoration: none;
           padding: 4px 12px; border-radius: 20px; font-size: .78rem;
           transition: background .2s; white-space: nowrap; }}
  nav a:hover {{ background: #ffffff35; color: #fff; }}
  .nav-count {{ opacity: .6; }}

  main {{ max-width: 1400px; margin: 0 auto; padding: 24px 16px; }}

  section {{ margin-bottom: 40px; }}
  section h2 {{ font-size: 1.1rem; color: #333; margin-bottom: 14px;
               padding-bottom: 8px; border-bottom: 2px solid #ddd; }}
  .count {{ font-weight: normal; color: #999; font-size: .9rem; }}

  .grid {{ display: grid;
           grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
           gap: 14px; }}

  .card {{ background: #fff; border-radius: 10px; overflow: hidden;
           text-decoration: none; color: inherit;
           box-shadow: 0 1px 4px rgba(0,0,0,.1);
           transition: transform .15s, box-shadow .15s; display: flex;
           flex-direction: column; }}
  .card:hover {{ transform: translateY(-3px);
                 box-shadow: 0 6px 16px rgba(0,0,0,.15); }}

  .card-img {{ position: relative; aspect-ratio: 1; background: #f8f8f8;
               overflow: hidden; }}
  .card-img img {{ width: 100%; height: 100%; object-fit: contain; padding: 8px; }}
  .no-img {{ width: 100%; height: 100%; display: flex; align-items: center;
             justify-content: center; color: #ccc; font-size: .75rem; }}

  .badge {{ position: absolute; top: 8px; right: 8px; background: #2d8a4e;
            color: #fff; font-size: .72rem; font-weight: 700;
            padding: 3px 8px; border-radius: 20px; }}
  .badge.sale {{ background: #1a6bcc; }}

  .card-body {{ padding: 10px 12px 12px; flex: 1; display: flex;
                flex-direction: column; gap: 4px; }}
  .store {{ font-size: .7rem; color: #888; text-transform: uppercase;
            letter-spacing: .04em; }}
  .name {{ font-size: .82rem; font-weight: 600; color: #222; line-height: 1.3;
           flex: 1; }}
  .pricing {{ display: flex; align-items: baseline; gap: 6px; margin-top: 4px; }}
  .price {{ font-size: 1rem; font-weight: 700; color: #2d8a4e; }}
  .was {{ font-size: .78rem; color: #bbb; text-decoration: line-through; }}

  footer {{ text-align: center; padding: 24px; color: #aaa; font-size: .75rem; }}
</style>
</head>
<body>

<header>
  <h1>🧗 Climbing Deals — {today}</h1>
  <div class="meta">{len(deals)} deals &nbsp;·&nbsp; {store_summary} &nbsp;·&nbsp; prices inc. VAT</div>
  <nav>{nav_links}</nav>
</header>

<main>{sections}</main>

<footer>Updated daily · All prices include UK VAT · Click any card to open in store</footer>

</body>
</html>'''

def save_html(deals, today):
    html = build_html(deals, today)
    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✔ Saved HTML page to {HTML_FILE}")

# ── EMAIL ─────────────────────────────────────────────────────────────────────

def build_email_html(deals, today, gh_pages_url):
    by_cat = {}
    for d in deals:
        by_cat.setdefault(d["category"], []).append(d)

    sections = ""
    for cat in CAT_ORDER:
        if cat not in by_cat:
            continue
        items = sorted(by_cat[cat], key=lambda x: x["discount_pct"], reverse=True)
        rows = ""
        for d in items:
            badge = (
                f'<span style="background:#2d8a4e;color:#fff;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:bold;">-{d["discount_pct"]}%</span>'
                if d["discount_pct"] > 0 else
                '<span style="color:#999;font-size:11px;">sale</span>'
            )
            rows += f"""<tr>
              <td style="padding:7px 8px;border-bottom:1px solid #f0f0f0;font-size:12px;color:#888;">{d['store']}</td>
              <td style="padding:7px 8px;border-bottom:1px solid #f0f0f0;font-size:13px;">
                <a href="{d['url']}" target="_blank" style="color:#1a6bcc;text-decoration:none;">{d['product']}</a>
              </td>
              <td style="padding:7px 8px;border-bottom:1px solid #f0f0f0;font-weight:bold;font-size:13px;white-space:nowrap;color:#2d8a4e;">{d['price']}</td>
              <td style="padding:7px 8px;border-bottom:1px solid #f0f0f0;color:#bbb;text-decoration:line-through;font-size:12px;white-space:nowrap;">{d['was']}</td>
              <td style="padding:7px 8px;border-bottom:1px solid #f0f0f0;text-align:center;">{badge}</td>
            </tr>"""

        sections += f"""
        <h3 style="margin:20px 0 6px;font-size:14px;color:#333;">{cat}
          <span style="font-weight:normal;color:#999;font-size:12px;">({len(items)})</span>
        </h3>
        <table style="width:100%;border-collapse:collapse;">
          <thead><tr style="background:#f8f8f8;">
            <th style="padding:5px 8px;font-size:11px;color:#aaa;text-align:left;">Store</th>
            <th style="padding:5px 8px;font-size:11px;color:#aaa;text-align:left;">Product</th>
            <th style="padding:5px 8px;font-size:11px;color:#aaa;">Price</th>
            <th style="padding:5px 8px;font-size:11px;color:#aaa;">Was</th>
            <th style="padding:5px 8px;font-size:11px;color:#aaa;">Save</th>
          </tr></thead>
          <tbody>{rows}</tbody>
        </table>"""

    view_btn = f'<a href="{gh_pages_url}" target="_blank" style="display:inline-block;background:#1a1a2e;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:bold;font-size:14px;">🧗 View Full Page with Images →</a>'

    store_counts = {}
    for d in deals:
        store_counts[d["store"]] = store_counts.get(d["store"], 0) + 1
    summary = " · ".join(f"{s}: {n}" for s, n in sorted(store_counts.items()))

    return f"""<html><body style="font-family:Arial,sans-serif;max-width:800px;margin:auto;color:#222;padding:16px;">
      <h2 style="color:#1a1a2e;margin-bottom:4px;">🧗 Climbing Deals — {today}</h2>
      <p style="color:#666;margin:0 0 8px;">{len(deals)} deals found · prices inc. VAT</p>
      <p style="color:#999;font-size:12px;margin:0 0 16px;">{summary}</p>
      <p style="margin-bottom:20px;">{view_btn}</p>
      {sections}
      <p style="margin-top:24px;color:#ccc;font-size:11px;">All prices include UK VAT</p>
    </body></html>"""

def send_email(deals, today, gh_pages_url):
    subject = f"🧗 Climbing Deals {today} — {len(deals)} found"
    html    = build_email_html(deals, today, gh_pages_url)
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
    gh_pages_url = os.environ.get("GH_PAGES_URL", "#")
    print(f"\n🧗 Climbing Deals Scraper — {today}\n")

    all_deals = []
    for store in STORES:
        deals = get_deals(store)
        print(f"  → {len(deals)} deals at {store['name']}")
        all_deals.extend(deals)

    all_deals.sort(key=lambda x: x["discount_pct"], reverse=True)
    print(f"\nTotal: {len(all_deals)} deals")

    log_deals(all_deals)
    save_html(all_deals, today)
    send_email(all_deals, today, gh_pages_url)
    print("\nDone ✔\n")

if __name__ == "__main__":
    main()
