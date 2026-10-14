#!/usr/bin/env python3
"""
Scrape 80/20 T-slot profile specs into a CSV that pd.read_csv can load directly.

    pip install requests beautifulsoup4        (or: uv add requests beautifulsoup4)

    python scrape_8020.py                          # all 272 profiles -> 8020_profiles.csv
    python scrape_8020.py --limit 3                # quick test on the first 3 products
    python scrape_8020.py --product https://8020.net/1515.html
    python scrape_8020.py --url "https://8020.net/framing-options/t-slotted-profiles.html?cat=9"   # metric only
    python scrape_8020.py --refresh                # re-scrape parts already in the CSV (appends new rows)
    python scrape_8020.py --from-html saved_pages/    # parse product pages you saved from your own browser
                                                      # (Ctrl+S on each page; files or folders)
    python scrape_8020.py --from-json 8020_raw.json   # parse pages collected by 8020_console_export.js
                                                   # in your own browser (use this if the site blocks scripts)
    python scrape_8020.py --browser                # fetch with a real Chromium if plain HTTP gets 403
    python scrape_8020.py --browser --headed       # visible window: if the site shows a human-check
                                                   # page, complete it once; the profile remembers it
        (one-time: pip install playwright ; playwright install chromium)

    import pandas as pd
    df = pd.read_csv("8020_profiles.csv")

APPEND BEHAVIOR
    * If the CSV exists, new rows are appended; existing rows are never dropped.
    * Part numbers already in the CSV are skipped (so you can stop and resume),
      unless --refresh is given, in which case a new row is appended with a new
      `scraped_at` (handy for price history; keep the latest per part_number).
    * If a page has a spec label the CSV has not seen before, the file is rewritten
      once with the extra column added (old rows get an empty value there).

COLUMNS
    Derived, in SI units (blank when the page doesn't give the value):
        part_number, url, subtitle, description, image_url, scraped_at
        price_unit              unit the site prices by ("inch" or "millimeter")
        price_per_unit_usd      price per that unit
        price_per_m_usd         cost per metre
        price_per_in_usd        cost per inch
        cut_charge_usd          one-off charge per cut
        standard_lengths        pipe-separated stock lengths, e.g. 12"|36"|72"|89"
        max_length_in, max_length_m
        width_m, height_m       parsed from the subtitle ("1.50" X 3.00"")
        a_m2                    cross-section area
        ix_m4, iy_m4            the site's "Moment of Inertia - IX / IY"
        iz_m4, j_m4             only filled if the page ever lists them (they didn't on
                                the pages checked)
        weight_kg_per_m
        rho_kg_m3, rho_kn_m3    DERIVED = weight per length / area (not listed on site)
        fy_mpa, e_mpa           yield strength, modulus of elasticity
        parse_notes             which key fields were missing on that page
    Raw: every row of the "Product Details" table is also kept verbatim in a
        spec_<label> column (spec_grade, spec_finish, spec_series, spec_color,
        spec_yield_strength, ...), so nothing on the page is lost.
"""
from __future__ import annotations

import argparse
import atexit
import csv
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

try:  # optional: pip install curl_cffi  -> sends a real Chrome TLS fingerprint
    from curl_cffi import requests as cc_requests
except ImportError:
    cc_requests = None

LISTING_URL = "https://8020.net/framing-options/t-slotted-profiles.html"
HOME_URL = "https://8020.net/"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",  # no 'br': requests can't decode it without brotli
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

IN = 0.0254               # m per inch
LB = 0.45359237           # kg per lb
PSI_TO_MPA = 0.00689475729
G = 9.80665               # m/s^2

CORE_COLUMNS = [
    "part_number", "url", "subtitle", "description", "image_url", "scraped_at",
    "price_unit", "price_per_unit_usd", "price_per_m_usd", "price_per_in_usd",
    "cut_charge_usd", "standard_lengths", "max_length_in", "max_length_m",
    "width_m", "height_m",
    "a_m2", "ix_m4", "iy_m4", "iz_m4", "j_m4",
    "weight_kg_per_m", "rho_kg_m3", "rho_kn_m3", "fy_mpa", "e_mpa",
    "parse_notes",
]


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, status_code: int, text: str):
        self.status_code, self.text = status_code, text


class PlaywrightSession:
    """Drop-in for the .get() calls below, driven by a real Chromium."""

    CHALLENGE_WAIT_S = 180

    def __init__(self, headed: bool = False, profile_dir: str = ".8020_browser_profile"):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise SystemExit("--browser needs Playwright:\n"
                             "  pip install playwright\n  playwright install chromium")
        self._headed = headed
        self._announced = False
        self._pw = sync_playwright().start()
        # Persistent profile: once you pass the site's human check in the window,
        # the cookie it sets is kept for later pages and later runs.
        self._ctx = self._pw.chromium.launch_persistent_context(
            profile_dir, headless=not headed, locale="en-US",
            viewport={"width": 1366, "height": 900})
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

    def _challenged(self) -> bool:
        title = (self._page.title() or "").lower()
        return "just a moment" in title or "checking your browser" in title

    def get(self, url: str, **_ignored) -> _Resp:
        resp = self._page.goto(url, wait_until="domcontentloaded", timeout=45000)
        status = resp.status if resp else 0
        if self._challenged():
            if not self._headed:
                return _Resp(403, self._page.content())  # caller shows the block-page text
            if not self._announced:
                self._announced = True
                print("\n>>> The site is showing a human-verification page. Complete it in the "
                      f"browser window (waiting up to {self.CHALLENGE_WAIT_S}s)...\n", file=sys.stderr)
            for _ in range(self.CHALLENGE_WAIT_S):
                if not self._challenged():
                    break
                time.sleep(1)
            else:
                return _Resp(403, self._page.content())
            self._page.wait_for_load_state("domcontentloaded")
            status = 200
        return _Resp(status, self._page.content())

    def close(self) -> None:
        try:
            self._ctx.close()
            self._pw.stop()
        except Exception:
            pass


def make_session(browser: bool = False, headed: bool = False,
                 profile_dir: str = ".8020_browser_profile"):
    """Real Chromium if asked; else curl_cffi (Chrome impersonation) if installed; else requests."""
    if browser:
        sess = PlaywrightSession(headed=headed, profile_dir=profile_dir)
        atexit.register(sess.close)
        return sess
    if cc_requests is not None:
        return cc_requests.Session(impersonate="chrome")
    return requests.Session()


def warm_up(session) -> None:
    """Hit the home page first so the session carries normal cookies."""
    try:
        session.get(HOME_URL, headers=None if cc_requests and not isinstance(session, requests.Session)
                    else HEADERS, timeout=30)
    except Exception:
        pass


def get_html(session, url: str, retries: int = 3, delay: float = 1.0) -> str:
    # curl_cffi sets headers matching its Chrome fingerprint; don't override them.
    kwargs = {} if cc_requests and not isinstance(session, requests.Session) else {"headers": HEADERS}
    last = "unknown error"
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=30, **kwargs)
            if r.status_code == 200:
                return r.text
            last = f"HTTP {r.status_code}"
            if r.status_code in (403, 404):
                if r.status_code == 403:
                    snippet = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text or ""))[:200].strip()
                    last += f" | block page says: {snippet!r}" if snippet else " | empty body"
                    last += (" | try: --browser --headed (complete the check once in the window)")
                break
        except Exception as e:  # requests or curl_cffi errors
            last = str(e)
        time.sleep(delay * (attempt + 1) * 2)
    raise RuntimeError(f"{url}: {last}")


# --------------------------------------------------------------------------- #
# Listing pages -> product URLs
# --------------------------------------------------------------------------- #
def with_page(url: str, page: int) -> str:
    parts = urlparse(url)
    q = parse_qs(parts.query)
    q["p"] = [str(page)]
    return urlunparse(parts._replace(query=urlencode(q, doseq=True)))


def _is_product_url(url: str) -> bool:
    """Product pages look like https://8020.net/1515.html (one path segment, no query).
    Category pages are deeper (/framing-options/...) and are excluded."""
    p = urlparse(url)
    return (p.netloc.endswith("8020.net") and not p.query
            and re.fullmatch(r"/[^/]+\.html", p.path) is not None)


def listing_links(html: str, base: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    # 1) Magento's usual class, 2) product-item containers, 3) product names are headings
    anchors = soup.select("a.product-item-link")
    if not anchors:
        anchors = soup.select(".product-item-name a[href], li.product-item a[href], "
                              ".product-item-info a[href]")
    if not anchors:
        anchors = soup.select("h2 a[href], h3 a[href], h4 a[href]")
    out, seen = [], set()
    for a in anchors:
        href = a.get("href")
        if not href:
            continue
        full = urljoin(base, href.split("#")[0])
        if full not in seen and _is_product_url(full):
            seen.add(full)
            out.append(full)
    return out


def collect_product_urls(session, listing_url: str, delay: float, max_pages: int = 60) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        html = get_html(session, with_page(listing_url, page), delay=delay)
        new = [u for u in listing_links(html, listing_url) if u not in seen]
        if page == 1 and not new:
            dbg = Path("debug_listing.html")
            dbg.write_text(html, encoding="utf-8")
            title = BeautifulSoup(html, "html.parser").title
            raise RuntimeError(
                f"No products found on listing page 1 (page title: "
                f"{title.get_text(strip=True) if title else '(none)'!r}, {len(html)} bytes). "
                f"Raw HTML saved to {dbg.resolve()} - open it to see what the site returned.")
        if not new:  # Magento repeats the last page past the end
            break
        seen.update(new)
        urls.extend(new)
        print(f"  listing page {page}: +{len(new)} (total {len(urls)})", file=sys.stderr)
        time.sleep(delay)
    return urls


# --------------------------------------------------------------------------- #
# Number / unit helpers
# --------------------------------------------------------------------------- #
def to_float(text: str) -> float | None:
    """First number in text. Handles '25,000', '242.000000' and the site's
    malformed '68.947.6' (meaning 68,947.6)."""
    # second alternative keeps values written without a leading zero: ".786" -> 0.786, not 786
    m = re.search(r"\d[\d,.]*|\.\d+", text or "")
    if not m:
        return None
    s = m.group(0).rstrip(".,").replace(",", "")
    if s.count(".") > 1:
        head, _, tail = s.rpartition(".")
        s = head.replace(".", "") + "." + tail
    try:
        return float(s)
    except ValueError:
        return None


def inertia_to_m4(text: str) -> float | None:
    v = to_float(text)
    if v is None:
        return None
    t = text.lower()
    if "mm" in t:
        return v * 1e-12
    if "cm" in t:
        return v * 1e-8
    # inch mark can be ASCII ", curly ” “, or prime ″; or the words in / inch / inches
    if re.search("[\"”“″]|\\bin(?:ch(?:es)?)?\\b", t):
        return v * IN ** 4
    return None


def area_to_m2(text: str) -> float | None:
    """'1.152 Sq. In.', '8.742 Sq cm', '5.082 cm²', '5.082 cm^2', '120 mm2' -> m^2."""
    v = to_float(text)
    if v is None:
        return None
    t = text.lower().replace("²", "^2")
    m = re.search(r"sq\.?\s*(mm|cm|in|m)\b|\b(mm|cm|in|m)\s*\^?2\b", t)
    if not m:
        return None
    unit = m.group(1) or m.group(2)
    return v * {"mm": 1e-6, "cm": 1e-4, "in": IN ** 2, "m": 1.0}[unit]


def stress_to_mpa(text: str) -> float | None:
    v = to_float(text)
    if v is None:
        return None
    t = text.lower()
    if "ksi" in t:
        return v * 1000 * PSI_TO_MPA
    if "psi" in t or re.search(r"lbs?\.?\s*/\s*sq\.?\s*in", t):
        return v * PSI_TO_MPA
    if "gpa" in t:
        return v * 1000
    if "mpa" in t or re.search(r"n\s*/\s*sq\.?\s*mm", t) or "n/mm" in t:
        return v
    return None


def length_to_m(text: str, default_unit: str = "in") -> float | None:
    v = to_float(text)
    if v is None:
        return None
    t = text.lower()
    if "mm" in t:
        return v / 1000
    if "cm" in t:
        return v / 100
    if "inch" in t or '"' in t or "in" in t:
        return v * IN
    return v * IN if default_unit == "in" else v


def weight_to_kg_per_m(label: str, value: str) -> float | None:
    v = to_float(value)
    if v is None:
        return None
    lab, val = label.lower(), value.lower()
    if ("lb" in lab or "lb" in val) and ("inch" in val or "/ in" in val or "per in" in val):
        return v * LB / IN
    if ("lb" in lab or "lb" in val) and ("ft" in val or "foot" in val):
        return v * LB / 0.3048
    if "kg" in val and ("m" in val):
        return v
    return None


def slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def find_spec(specs: dict[str, str], pattern: str) -> tuple[str, str] | None:
    rx = re.compile(pattern, re.I)
    for label, value in specs.items():
        if rx.search(label):
            return label, value
    return None


# --------------------------------------------------------------------------- #
# Product page parsing
# --------------------------------------------------------------------------- #
def meta(soup: BeautifulSoup, key: str) -> str:
    tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    return (tag.get("content") or "").strip() if tag else ""


def parse_specs(soup: BeautifulSoup) -> dict[str, str]:
    """Rows of the 'Product Details' table, label -> value, verbatim."""
    keys = ("yield strength", "moment of inertia", "max length", "modulus", "surface area")
    for table in soup.find_all("table"):
        if not any(k in table.get_text(" ", strip=True).lower() for k in keys):
            continue
        specs: dict[str, str] = {}
        for tr in table.find_all("tr"):
            cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
            if len(cells) >= 2 and cells[0]:
                specs.setdefault(cells[0], cells[1])
        if specs:
            return specs
    return {}


def parse_standard_lengths(text: str) -> list[str]:
    # bounded window: an unbounded lazy match can crawl on a huge page with no "Custom Length"
    m = re.search(r"Select\s+Length(.{0,3000}?)Custom\s+Length", text, re.S | re.I)
    if not m:
        return []
    return [re.sub(r"\s+", "", s) for s in
            re.findall(r"\d+(?:\.\d+)?\s*(?:\"|”|mm\b|cm\b|ft\b|in\b|m\b|')", m.group(1))]


def parse_dims(subtitle: str) -> tuple[float | None, float | None]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:mm|”|\")?\s*[xX]\s*(\d+(?:\.\d+)?)", subtitle)
    if not m:
        return None, None
    scale = 0.001 if "mm" in subtitle.lower() else IN
    return float(m.group(1)) * scale, float(m.group(2)) * scale


def canonical_url(html: str, fallback: str) -> str:
    """URL of a saved page, from its <link rel=canonical> / og:url (head only, no full parse)."""
    head = html[:200_000]
    for tag in re.findall(r"<link\b[^>]*>", head, re.I):
        if re.search(r"rel\s*=\s*[\"']?canonical", tag, re.I):
            m = re.search(r"href\s*=\s*[\"']([^\"']+)", tag, re.I)
            if m:
                return m.group(1)
    for tag in re.findall(r"<meta\b[^>]*>", head, re.I):
        if re.search(r"property\s*=\s*[\"']og:url", tag, re.I):
            m = re.search(r"content\s*=\s*[\"']([^\"']+)", tag, re.I)
            if m:
                return m.group(1)
    return fallback


def _load_saved(path: Path) -> tuple[str, str]:
    html = path.read_text(encoding="utf-8", errors="replace")
    return canonical_url(html, path.name), html


def progress_bar(i: int, total: int, width: int = 20) -> str:
    filled = int(width * i / total) if total else width
    return "[" + "#" * filled + "-" * (width - filled) + f"] {i}/{total}"


def parse_product(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.title.get_text(strip=True) if soup.title else meta(soup, "og:title")
    subtitle = title_tag.split("|", 1)[1].strip() if "|" in title_tag else meta(soup, "og:description")

    h1 = soup.find("h1")
    part_number = h1.get_text(strip=True) if h1 else urlparse(url).path.strip("/").removesuffix(".html")

    desc_node = soup.select_one("div.product.attribute.description .value, #description")
    description = (re.sub(r"\s+", " ", desc_node.get_text(" ", strip=True)) if desc_node
                   else meta(soup, "description"))

    specs = parse_specs(soup)

    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    text = soup.get_text("\n", strip=True)

    row: dict = {
        "part_number": part_number,
        "url": url,
        "subtitle": subtitle,
        "description": description,
        "image_url": meta(soup, "og:image"),
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    # --- price -------------------------------------------------------------
    price_unit, ppu = "", None
    m = re.search(r"Price\s+Per\s+(\w+)\s*:?\s*\$\s*([\d,]*\.?\d+)", text, re.I)
    if m:
        price_unit, ppu = m.group(1).lower(), float(m.group(2).replace(",", ""))
    else:
        amt = meta(soup, "product:price:amount")
        ppu = float(amt) if amt else None
    per_m = None
    if ppu is not None:
        per_m = {"inch": ppu / IN, "millimeter": ppu * 1000, "mm": ppu * 1000,
                 "foot": ppu / 0.3048, "meter": ppu, "metre": ppu}.get(price_unit)
    row.update({
        "price_unit": price_unit,
        "price_per_unit_usd": ppu,
        "price_per_m_usd": per_m,
        "price_per_in_usd": per_m * IN if per_m is not None else None,
    })
    m = re.search(r"cut\s+charge\s+of\s+\$\s*([\d,]*\.?\d+)", text, re.I)
    row["cut_charge_usd"] = float(m.group(1).replace(",", "")) if m else None
    row["standard_lengths"] = "|".join(parse_standard_lengths(text))

    # --- geometry ----------------------------------------------------------
    hit = find_spec(specs, r"^max length")
    row["max_length_m"] = length_to_m(hit[1] + " in", "in") if hit and "mm" not in hit[0].lower() else None
    row["max_length_in"] = row["max_length_m"] / IN if row["max_length_m"] is not None else None
    row["width_m"], row["height_m"] = parse_dims(subtitle)

    hit = find_spec(specs, r"surface area|^area|cross.?section")
    row["a_m2"] = area_to_m2(hit[1]) if hit else None

    for col, pat in (("ix_m4", r"inertia.*\bix\b|^ix\b"), ("iy_m4", r"inertia.*\biy\b|^iy\b"),
                     ("iz_m4", r"inertia.*\biz\b|^iz\b"),
                     ("j_m4", r"inertia.*\bj\b|polar|torsion")):
        hit = find_spec(specs, pat)
        row[col] = inertia_to_m4(hit[1]) if hit else None

    # --- geometry sanity: a section can't exceed its bounding box -----------
    geom_notes: list[str] = []
    w, h = row["width_m"], row["height_m"]
    if w and h:
        if row["a_m2"] is not None and row["a_m2"] > w * h * 1.001:
            geom_notes.append(f"area_exceeds_bounding_box(a={row['a_m2']:.3g}m2>{w * h:.3g}m2; see spec_surface_area)")
            row["a_m2"] = None
        i_max = max(w * h ** 3, h * w ** 3) / 12  # solid rectangle: upper bound for either axis
        for col in ("ix_m4", "iy_m4"):
            if row[col] is not None and row[col] > i_max * 1.001:
                geom_notes.append(f"{col[:2]}_exceeds_bounding_box({row[col]:.3g}m4>{i_max:.3g}m4)")
                row[col] = None

    # --- mass / density (derived) -----------------------------------------
    kg_m = None
    hit = find_spec(specs, r"^weight\s*lbs?|^weight.*per")
    if hit:
        kg_m = weight_to_kg_per_m(*hit)
    rho = kg_m / row["a_m2"] if kg_m and row["a_m2"] else None
    weight_note = ""
    if rho is not None and not (1000 <= rho <= 3500):
        # Aluminum is ~2700 kg/m^3 and FRP ~2000; anything far outside means the site's
        # weight (or area) is wrong or in different units. Don't pass it downstream.
        weight_note = f"weight_implausible(implied_rho={rho:.0f}kg/m3; see spec_weight_lbs)"
        kg_m = rho = None
    row["weight_kg_per_m"] = kg_m
    row["rho_kg_m3"] = rho
    row["rho_kn_m3"] = rho * G / 1000 if rho else None

    # --- strength / stiffness ---------------------------------------------
    hit = find_spec(specs, r"yield")
    row["fy_mpa"] = stress_to_mpa(hit[1]) if hit else None
    hit = find_spec(specs, r"modulus")
    row["e_mpa"] = stress_to_mpa(hit[1]) if hit else None

    # --- raw spec table, verbatim -----------------------------------------
    for label, value in specs.items():
        row["spec_" + slug(label)] = value

    missing = [k for k in ("a_m2", "ix_m4", "iy_m4", "fy_mpa", "e_mpa", "max_length_m",
                           "price_per_m_usd") if row.get(k) is None]
    if not specs:
        missing.insert(0, "NO_SPEC_TABLE")
    notes = [("missing: " + ",".join(missing)) if missing else "", weight_note, *geom_notes]
    row["parse_notes"] = "; ".join(n for n in notes if n)
    return row


# --------------------------------------------------------------------------- #
# CSV (append, with column growth)
# --------------------------------------------------------------------------- #
def ordered_fields(keys: set[str]) -> list[str]:
    core = [c for c in CORE_COLUMNS if c in keys]
    extra = sorted(k for k in keys if k not in CORE_COLUMNS)
    return core + extra


def existing_part_numbers(path: Path) -> set[str]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {(r.get("part_number") or "").lower() for r in csv.DictReader(f)}


def append_rows(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    new_keys = set().union(*(r.keys() for r in rows))
    if not path.exists() or path.stat().st_size == 0:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=ordered_fields(new_keys), restval="")
            w.writeheader()
            w.writerows(rows)
        return

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        old_fields = list(reader.fieldnames or [])
        if new_keys <= set(old_fields):
            pass  # plain append below
        else:
            old_rows = list(reader)
            fields = old_fields + sorted(new_keys - set(old_fields))
            fd, tmp = tempfile.mkstemp(suffix=".csv", dir=str(path.parent))
            with os.fdopen(fd, "w", newline="", encoding="utf-8") as out:
                w = csv.DictWriter(out, fieldnames=fields, restval="")
                w.writeheader()
                w.writerows(old_rows)
                w.writerows(rows)
            os.replace(tmp, path)
            return
    with path.open("a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=old_fields, restval="").writerows(rows)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="8020_profiles.csv", help="CSV to append to (created if missing)")
    ap.add_argument("--url", default=LISTING_URL, help="listing URL (filters like ?cat=9 work)")
    ap.add_argument("--product", action="append", help="scrape just this product URL (repeatable)")
    ap.add_argument("--limit", type=int, help="only scrape the first N products")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default 1.0)")
    ap.add_argument("--refresh", action="store_true", help="re-scrape parts already in the CSV")
    ap.add_argument("--browser", action="store_true",
                    help="fetch with a real Chromium (pip install playwright; playwright install chromium)")
    ap.add_argument("--headed", action="store_true",
                    help="with --browser, show the window so you can complete a human-verification page")
    ap.add_argument("--profile-dir", default=".8020_browser_profile",
                    help="browser profile kept between runs (holds the cookie from passing the check)")
    ap.add_argument("--from-json", metavar="FILE",
                    help="parse 8020_raw.json produced by 8020_console_export.js instead of fetching")
    ap.add_argument("--from-html", nargs="+", metavar="PATH",
                    help="parse product pages you saved from your browser (files and/or folders of .html)")
    args = ap.parse_args()

    out = Path(args.out)

    if args.from_json or args.from_html:  # no network: parse pages you collected yourself
        # Lazy jobs: (label, loader). Nothing is read until its turn, so progress shows at once.
        jobs: list[tuple[str, Callable[[], tuple[str, str]]]] = []
        if args.from_json:
            for it in json.loads(Path(args.from_json).read_text(encoding="utf-8")):
                jobs.append((it["url"], lambda it=it: (it["url"], it["html"])))
        for p in args.from_html or []:
            path = Path(p)
            if not path.exists():
                print(f"Path not found: {path}", file=sys.stderr)
                return 2
            files = (sorted({*path.glob("*.htm"), *path.glob("*.html")}) if path.is_dir() else [path])
            print(f"Looking in {path} ... {len(files)} .html file(s)", file=sys.stderr, flush=True)
            for f in files:
                jobs.append((f.name, lambda f=f: _load_saved(f)))
        jobs = jobs[: args.limit or None]
        if not jobs:
            print("Nothing to parse (no .html files found).", file=sys.stderr)
            return 1

        done = set() if args.refresh else existing_part_numbers(out)
        batch: list[dict] = []
        parsed = skipped = errors = 0
        t_start = time.time()
        try:
            for i, (label, load) in enumerate(jobs, 1):
                # print the name BEFORE working on it, so a slow/stuck file is identifiable
                print(f"{progress_bar(i, len(jobs))}  {label[:55]} ...", end=" ", file=sys.stderr, flush=True)
                t0 = time.time()
                try:
                    url, html = load()
                    row = parse_product(html, url)
                except Exception as e:
                    errors += 1
                    print(f"ERROR: {e}", file=sys.stderr, flush=True)
                    continue
                if "NO_SPEC_TABLE" in row["parse_notes"]:
                    errors += 1
                    print("SKIPPED: no spec table found (cut-off save, or not a product page?)",
                          file=sys.stderr, flush=True)
                    continue
                if row["part_number"].lower() in done:
                    skipped += 1
                    print("skipped (already in CSV)", file=sys.stderr, flush=True)
                    continue
                done.add(row["part_number"].lower())
                batch.append(row)
                parsed += 1
                note = f"  ({row['parse_notes']})" if row["parse_notes"] else ""
                print(f"{row['part_number']} ok {time.time() - t0:.1f}s{note}", file=sys.stderr, flush=True)
                if len(batch) >= 20:
                    append_rows(out, batch)
                    batch.clear()
        finally:
            append_rows(out, batch)  # also runs on Ctrl+C, so nothing parsed is lost
        print(f"\nDone in {time.time() - t_start:.1f}s: {parsed} added, {skipped} skipped "
              f"(already in CSV), {errors} errors -> {out}", file=sys.stderr)
        return 1 if errors else 0

    session = make_session(args.browser, args.headed, args.profile_dir)
    warm_up(session)

    if args.product:
        urls = args.product
    else:
        print("Collecting product URLs...", file=sys.stderr)
        urls = collect_product_urls(session, args.url, args.delay)
    if args.limit:
        urls = urls[: args.limit]

    done = set() if args.refresh else existing_part_numbers(out)
    batch: list[dict] = []
    failed: list[str] = []
    scraped = skipped = 0

    try:
        for i, url in enumerate(urls, 1):
            slug_pn = urlparse(url).path.strip("/").removesuffix(".html")
            if slug_pn.lower() in done:
                skipped += 1
                continue
            try:
                row = parse_product(get_html(session, url, delay=args.delay), url)
            except Exception as e:  # keep going; report at the end
                print(f"[{i}/{len(urls)}] FAILED {url}: {e}", file=sys.stderr)
                failed.append(url)
                continue
            if "NO_SPEC_TABLE" in row["parse_notes"]:  # e.g. a bot-check page that returned 200
                print(f"[{i}/{len(urls)}] SKIPPED {url}: no spec table in the page", file=sys.stderr)
                failed.append(url)
                continue
            if row["part_number"].lower() in done:
                skipped += 1
                continue
            batch.append(row)
            scraped += 1
            note = f"  ({row['parse_notes']})" if row["parse_notes"] else ""
            print(f"[{i}/{len(urls)}] {row['part_number']}{note}", file=sys.stderr)
            if len(batch) >= 20:
                append_rows(out, batch)
                batch.clear()
            time.sleep(args.delay)
    finally:
        append_rows(out, batch)  # also runs on Ctrl+C

    print(f"\nDone: {scraped} scraped, {skipped} skipped (already in CSV), {len(failed)} failed -> {out}",
          file=sys.stderr)
    for u in failed:
        print("  failed:", u, file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())