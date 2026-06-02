"""
SGCarMart Car Alert Script
===========================
Scrapes SGCarMart for used cars matching your criteria and sends
a formatted email summary. Run this every 3 days via GitHub Actions
or any scheduler.

Setup instructions at the bottom of this file.
"""

import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import json
import os
import time
from datetime import datetime

# ──────────────────────────────────────────────
# YOUR CRITERIA — edit these if needed
# ──────────────────────────────────────────────
CRITERIA = {
    "models": [
        "BMW 3 Series 320",
        "BMW 3 Series 330",
        "BMW 5 Series 520",
        "BMW 5 Series 530",
        "Lexus ES 300h",
        "Volvo S90",
        "Volvo S60",
    ],
    "min_price": 80000,
    "max_price": 130000,
    "max_mileage": 100000,       # km
    "max_owners": 1,
    "reg_year_min": 2019,
    "reg_year_max": 2022,
}

# ──────────────────────────────────────────────
# EMAIL CONFIG — fill these in
# ──────────────────────────────────────────────
EMAIL_SENDER    = "gopinathtamotharan@gmail.com"       # Gmail address you send FROM
EMAIL_PASSWORD  = "zgrwfecrbmrkwawd"     # Gmail App Password (not your login password)
EMAIL_RECIPIENT = "gopinathtamotharan@gmail.com"     # Where to receive alerts

# ──────────────────────────────────────────────
# SEEN LISTINGS CACHE
# Tracks listings already sent so you don't get repeats
# ──────────────────────────────────────────────
CACHE_FILE = "seen_listings.json"

def load_seen():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(CACHE_FILE, "w") as f:
        json.dump(list(seen), f)

# ──────────────────────────────────────────────
# SCRAPER
# ──────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# SGCarMart search URL template
# We search by price range; filtering by model is done after scraping
SEARCH_URL = (
    "https://www.sgcarmart.com/used_cars/listing.php"
    "?BRSR={offset}&RPG=20"
    "&PRF={min_price}&PRT={max_price}"
    "&YRF={year_min}&YRT={year_max}"
    "&MLG=0&MLT={max_mileage}"
    "&OWN=1"           # single owner
    "&VEH=0"           # all vehicle types
    "&status=1"        # used cars
)

def build_url(offset=0):
    return SEARCH_URL.format(
        offset=offset,
        min_price=CRITERIA["min_price"],
        max_price=CRITERIA["max_price"],
        year_min=CRITERIA["reg_year_min"],
        year_max=CRITERIA["reg_year_max"],
        max_mileage=CRITERIA["max_mileage"],
    )

def parse_price(text):
    """Extract integer price from strings like '$98,800'"""
    cleaned = text.replace("$", "").replace(",", "").strip()
    try:
        return int(cleaned)
    except ValueError:
        return None

def parse_mileage(text):
    """Extract integer km from strings like '45,000 km'"""
    cleaned = text.lower().replace("km", "").replace(",", "").strip()
    try:
        return int(cleaned)
    except ValueError:
        return None

def parse_year(text):
    """Extract 4-digit year from registration strings"""
    import re
    match = re.search(r"(20\d{2})", text)
    return int(match.group(1)) if match else None

def matches_model(title):
    """Check if listing title contains one of our target models."""
    title_lower = title.lower()
    model_keywords = {
        "BMW 3 Series 320": ["bmw", "320"],
        "BMW 3 Series 330": ["bmw", "330"],
        "BMW 5 Series 520": ["bmw", "520"],
        "BMW 5 Series 530": ["bmw", "530"],
        "Lexus ES 300h":    ["lexus", "es", "300h"],
        "Volvo S90":        ["volvo", "s90"],
        "Volvo S60":        ["volvo", "s60"],
    }
    for model, keywords in model_keywords.items():
        if all(kw in title_lower for kw in keywords):
            return model
    return None

def scrape_listings():
    """Scrape all pages and return matching listings."""
    results = []
    offset = 0

    while True:
        url = build_url(offset)
        print(f"  Fetching: {url}")
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  Request failed: {e}")
            break

        soup = BeautifulSoup(resp.text, "html.parser")

        # Each listing is in a <tr> with class 'row_bg1' or 'row_bg2'
        rows = soup.select("tr.row_bg1, tr.row_bg2")
        if not rows:
            break

        for row in rows:
            try:
                # Title / link
                title_tag = row.select_one("a.link_regs")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                link  = "https://www.sgcarmart.com" + title_tag["href"]

                # Model check
                matched_model = matches_model(title)
                if not matched_model:
                    continue

                # Price
                price_tag = row.select_one("td.price_box b")
                price = parse_price(price_tag.get_text()) if price_tag else None

                # Details cells (year, mileage, owners)
                detail_cells = row.select("td.font14")
                reg_year, mileage, owners = None, None, None
                for cell in detail_cells:
                    txt = cell.get_text(strip=True)
                    if "km" in txt.lower():
                        mileage = parse_mileage(txt)
                    elif txt.isdigit() and len(txt) == 4:
                        reg_year = int(txt)
                    elif "owner" in txt.lower():
                        try:
                            owners = int(txt.split()[0])
                        except (ValueError, IndexError):
                            pass

                # Apply secondary filters
                if price and not (CRITERIA["min_price"] <= price <= CRITERIA["max_price"]):
                    continue
                if mileage and mileage > CRITERIA["max_mileage"]:
                    continue
                if owners and owners > CRITERIA["max_owners"]:
                    continue
                if reg_year and not (CRITERIA["reg_year_min"] <= reg_year <= CRITERIA["reg_year_max"]):
                    continue

                results.append({
                    "id":       link,
                    "title":    title,
                    "model":    matched_model,
                    "price":    price,
                    "mileage":  mileage,
                    "year":     reg_year,
                    "owners":   owners,
                    "link":     link,
                })

            except Exception as e:
                print(f"  Parse error on row: {e}")
                continue

        # Check if there's a next page
        next_btn = soup.select_one("a[title='Next page']")
        if not next_btn:
            break
        offset += 20
        time.sleep(1.5)   # be polite — don't hammer the server

    return results

# ──────────────────────────────────────────────
# EMAIL BUILDER
# ──────────────────────────────────────────────
def format_sgd(amount):
    return f"${amount:,}" if amount else "N/A"

def format_km(km):
    return f"{km:,} km" if km else "N/A"

def build_email_html(listings):
    rows = ""
    for car in listings:
        rows += f"""
        <tr>
          <td style="padding:10px 12px;border-bottom:1px solid #eee;">
            <a href="{car['link']}" style="color:#1a56db;font-weight:600;text-decoration:none;">
              {car['title']}
            </a><br>
            <span style="color:#888;font-size:12px;">{car['model']}</span>
          </td>
          <td style="padding:10px 12px;border-bottom:1px solid #eee;text-align:center;">
            {car.get('year', 'N/A')}
          </td>
          <td style="padding:10px 12px;border-bottom:1px solid #eee;text-align:right;font-weight:600;color:#16a34a;">
            {format_sgd(car['price'])}
          </td>
          <td style="padding:10px 12px;border-bottom:1px solid #eee;text-align:center;">
            {format_km(car['mileage'])}
          </td>
          <td style="padding:10px 12px;border-bottom:1px solid #eee;text-align:center;">
            {car.get('owners', 'N/A')}
          </td>
        </tr>"""

    return f"""
    <html><body style="font-family:Arial,sans-serif;color:#222;max-width:700px;margin:auto;padding:20px;">
      <h2 style="color:#1a56db;">🚗 SGCarMart Alert — {len(listings)} New Listing(s)</h2>
      <p style="color:#555;">Run on {datetime.now().strftime('%d %b %Y, %I:%M %p')}</p>
      <p><b>Your criteria:</b> BMW 320/330/520/530 · Lexus ES300h · Volvo S90/S60 &nbsp;|&nbsp;
         $80k–$130k &nbsp;|&nbsp; &lt;100,000 km &nbsp;|&nbsp; 1 owner &nbsp;|&nbsp; 2019–2022</p>

      <table width="100%" style="border-collapse:collapse;font-size:14px;margin-top:16px;">
        <thead>
          <tr style="background:#f0f4ff;">
            <th style="padding:10px 12px;text-align:left;">Listing</th>
            <th style="padding:10px 12px;">Year</th>
            <th style="padding:10px 12px;text-align:right;">Price</th>
            <th style="padding:10px 12px;">Mileage</th>
            <th style="padding:10px 12px;">Owners</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>

      <p style="margin-top:24px;color:#888;font-size:12px;">
        You're receiving this because you set up SGCarMart alerts.<br>
        Click any listing to view on SGCarMart.
      </p>
    </body></html>"""

def send_email(listings):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🚗 SGCarMart Alert — {len(listings)} new listing(s) match your criteria"
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_RECIPIENT
    msg.attach(MIMEText(build_email_html(listings), "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())
    print(f"  Email sent to {EMAIL_RECIPIENT}")

# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────
def main():
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Starting SGCarMart scan...")

    seen = load_seen()
    print(f"  {len(seen)} listings already seen previously.")

    all_listings = scrape_listings()
    print(f"  {len(all_listings)} matching listings found.")

    new_listings = [l for l in all_listings if l["id"] not in seen]
    print(f"  {len(new_listings)} are new since last run.")

    if new_listings:
        send_email(new_listings)
        seen.update(l["id"] for l in new_listings)
        save_seen(seen)
    else:
        print("  No new listings — no email sent.")

    print("Done.\n")

if __name__ == "__main__":
    main()
