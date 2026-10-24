"""Stream search helpers for the Flutter screen (screen.py).

release_search.py (your sites list and the parsing / scoring rules) is used as it is and never edited. This file adds
the three things only ui.js's built-in engine did, so the Flutter screen finds exactly what the web screen finds:

  * one request per site, so screen.py can run all sites at the same time (one site at a time could run past
    the 25 second limit of a background job);
  * "listing pages": a site whose result page shows releases but keeps the magnet link on each release's own page
    (1337x, YTS clones ...) gets its best few release pages read too;
  * the "Prefer smaller files" switch and a short report of what each site answered.

No network call is made here except through pek_host (the plugin's own network list in plugin.json).
"""
import html
import re
from urllib.parse import quote, urljoin, urlsplit

import hesper_host as h
import release_search as rs

MAX_LINKS = 4          # release pages read per site that has no magnet links on its result page


def sites():
    """The search addresses from release_search.py (the SITES-START / SITES-END block), unchanged."""
    return list(rs.SITES)


def host_of(url):
    try:
        return urlsplit(url).hostname or url
    except ValueError:
        return url


def query_words(title, season=0, episode=0, year=0, with_year=True):
    w = rs.normalize(title)
    if season and episode:
        w += " S%02dE%02d" % (int(season), int(episode))
    elif with_year and year:
        w += " " + str(int(year))
    return w


# --------------------------------------------------------------------------- reading result pages
def _num(text):
    digits = re.sub(r"\D", "", str(text if text is not None else ""))
    return int(digits) if digits else 0


def size_of(text):
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(KiB|MiB|GiB|TiB|KB|MB|GB|TB)\b", str(text or ""), re.I)
    if not m:
        return 0
    mult = {"k": 1024, "m": 1048576, "g": 1073741824, "t": 1099511627776}[m.group(2)[0].lower()]
    return int(float(m.group(1).replace(",", ".")) * mult)


def size_text(b):
    if not b or b < 2:
        return "size unknown"
    units, i, v = ["B", "KB", "MB", "GB", "TB"], 0, float(b)
    while v >= 1024 and i < len(units) - 1:
        v /= 1024
        i += 1
    return ("%.2f %s" if i >= 3 else "%.0f %s") % (v, units[i])


def _strip(s):
    return html.unescape(re.sub(r"<[^>]+>", "", str(s or ""))).strip()


def _row_around(text, pos):
    """The table row / list item / article that holds the link at pos (a window when there is none)."""
    best = -1
    for tag in ("<tr", "<li", "<article"):
        i = text.rfind(tag, 0, pos)
        if i > best:
            best = i
    if best < 0 or pos - best > 4000:
        best = max(0, pos - 800)
    end = len(text)
    for tag in ("</tr>", "</li>", "</article>"):
        j = text.find(tag, pos)
        if 0 <= j < end:
            end = j
    if end - pos > 4000:
        end = min(len(text), pos + 800)
    return text[best:end]


def _row_text(row):
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)
    if cells:
        return " | ".join(_strip(c) for c in cells)       # cells kept apart: "120" + "2.1 GB" is not "1202.1 GB"
    return _strip(row)


def _seeders_in(row):
    for m in re.finditer(r"""class\s*=\s*["']([^"']*)["'][^>]*>\s*(?:<[^>]+>\s*)*(\d[\d,]*)""", row, re.I):
        cls = m.group(1).lower()
        if "seed" in cls and "leech" not in cls:
            return _num(m.group(2))
    return -1


def listing_links(text, base_url, title, year=0):
    """Same-site release pages whose text holds every word of the title, best first (the year helps)."""
    toks = rs.normalize(title).split()
    if not toks:
        return []
    try:
        base = urlsplit(base_url)
    except ValueError:
        return []
    out, seen = [], set()
    for m in re.finditer(r"""<a\b[^>]*?href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""", str(text or ""), re.S | re.I):
        raw = html.unescape(m.group(1)).strip()
        if re.match(r"^(magnet:|javascript:|#|mailto:)", raw, re.I):
            continue
        try:
            url = urljoin(base_url, raw)
            parts = urlsplit(url)
        except ValueError:
            continue
        if parts.scheme != "https" or parts.hostname != base.hostname or url == base_url or url in seen:
            continue
        label = _strip(m.group(2))
        padded = " " + rs.normalize(label) + " "
        if any((" " + t + " ") not in padded for t in toks):
            continue
        seen.add(url)
        row = _row_around(str(text), m.start())
        out.append({"url": url, "title": label, "seeders": _seeders_in(row), "size": size_of(_row_text(row)),
                    "y": 1 if (year and str(int(year)) in label) else 0})
    out.sort(key=lambda x: -x["y"])
    return out[:MAX_LINKS]


# --------------------------------------------------------------------------- one request (run inside ui.background)
def fetch_site(template, words, title, year=0):
    """Asks one site. Never raises: {"host", "items", "links", "note", "error"}."""
    url = template.replace("{q}", quote(words, safe=""))
    host = host_of(url)
    try:
        body = h.fetch_text(url, headers={"User-Agent": rs.USER_AGENT}, timeout=8, max_bytes=1000000)
    except Exception as err:   # one broken site must not stop the others
        return {"host": host, "items": [], "links": [], "error": " ".join(str(err).split())[:170]}
    items = rs.parse_body(body)
    if items:
        return {"host": host, "items": items, "links": [], "note": "%d parsed" % len(items)}
    links = []
    try:
        links = listing_links(body, url, title, year)
    except Exception:
        links = []
    if not links:
        return {"host": host, "items": [], "links": [], "note": "page loaded but no releases found on it"}
    return {"host": host, "items": [], "links": links, "note": "%d release pages to read" % len(links)}


def fetch_release_page(link):
    """One release page of a listing: its magnet links, filled in with what the listing knew. Never raises."""
    try:
        body = h.fetch_text(link["url"], headers={"User-Agent": rs.USER_AGENT}, timeout=8, max_bytes=1000000)
        items = rs.parse_body(body)
    except Exception:
        return []
    for it in items:
        if it["seeders"] < 0:
            it["seeders"] = link["seeders"]
        if not it["size"]:
            it["size"] = link["size"]
        if len(it["title"]) < 6:
            it["title"] = link["title"]
    return items


# --------------------------------------------------------------------------- ranking
def match_kind(name, season, episode):
    n = name.lower()
    s, e = int(season), int(episode)
    if re.search(r"s0*%d[ ._-]?e0*%d(?!\d)" % (s, e), n) or re.search(r"(?<!\d)%dx0*%d(?!\d)" % (s, e), n):
        return "episode"
    if re.search(r"s0*%d(?!\d|e)" % s, n) or re.search(r"season[ ._-]*0*%d(?!\d)" % s, n):
        return "pack"
    return None


def _compact_penalty(item, season, episode, dev):
    """What rs.score_full takes off for big files, remux and 4K (given back when 'Prefer smaller files' is off)."""
    name = item["title"]
    norm = rs.normalize(name)
    is_ep = bool(season and episode)
    big = bool(dev and dev["big"])
    pen = 0.0
    gb = item["size"] / 1073741824.0 if item["size"] > 1 else 0
    if gb and not (is_ep and match_kind(name, season, episode) == "pack"):
        sweet, per = ((5, 12) if big else (1.6, 12)) if is_ep else ((14, 6) if big else (3.5, 6))
        if gb > sweet:
            pen += min(25, (gb - sweet) * per)
    if not big:
        if re.search(r"\b(remux|bdremux|uhd bluray|complete bluray|bluray disc)\b", norm):
            pen += 20
        if rs.traits(name)["q"] == 2160:
            pen += 10
    return pen


def rank(items, title, season=0, episode=0, year=0, dev=None, compact=True):
    """Drops wrong results, scores the rest, best first (at most 25). Same rules as release_search.find_releases."""
    ranked, seen = [], set()
    for it in items:
        full = rs.score_full(it, title, season, episode, year, dev)
        key = it["source"].lower()
        if full is None or key in seen:
            continue
        seen.add(key)
        sc = full[0] if compact else full[0] + _compact_penalty(it, season, episode, dev)
        ranked.append((sc, it, full[1], full[2]))
    ranked.sort(key=lambda p: -p[0])
    out = []
    for sc, it, tags, heavy in ranked[:25]:
        out.append({
            "title": it["title"], "source": it["source"], "seeders": max(0, it["seeders"]), "size": it["size"],
            "size_text": size_text(it["size"]), "quality": rs.traits(it["title"])["q"],
            "pack": bool(season and episode and match_kind(it["title"], season, episode) == "pack"),
            "tags": tags, "heavy": heavy, "score": round(sc, 1),
        })
    return out


def label_of(r):
    """One line for the release list."""
    parts = [(str(r["quality"]) + "p") if r["quality"] else "Quality not listed"]
    if r["tags"]:
        parts.append(r["tags"])
    parts.append(r["size_text"])
    parts.append("%d seeds" % r["seeders"])
    if r["pack"]:
        parts.append("season pack")
    if r["heavy"]:
        parts.append("may stutter on this device")
    return " \u00b7 ".join(parts)
