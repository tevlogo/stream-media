"""Release search for Stream Media (runs inside Hesper's plugin guard: no requests / bs4).

Add search sites in the SITES list below (or run add_site.py). Each entry is a search address
with {q} where the search words go. The page may be JSON or a web page that shows magnet links.
Remember: every site's host must also be listed under "network" in plugin.json.
"""
import html
import json
import math
import re
import unicodedata
from urllib.parse import quote, quote_plus, unquote_plus

import hesper_host as h

SITES = [
    # SITES-START
    "https://bt4gprx.com/search?q={q}&orderby=seeders&category=all&page=rss",
    "https://apibay.org/q.php?q={q}&cat=200",
    "https://yify.mobi/search/?q={q}",
    "https://1337x.to/search/{q}/1/",
    "https://thepiratebay.party/search/{q}/1/99/0",
    "https://bitsearch.eu/search?q={q}",
    # SITES-END
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.tracker.cl:1337/announce",
    "udp://tracker.torrent.eu.org:451/announce",
]


# --------------------------------------------------------------------------- query
def normalize(text):
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    t = t.lower().replace("&", " and ")
    t = re.sub(r"['`]", "", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def build_query(title, season=0, episode=0, year=0):
    """'The Office', 2, 5 -> 'the office S02E05'; a movie -> 'dune 2021'."""
    parts = [normalize(title)]
    if season and episode:
        parts.append("S%02dE%02d" % (int(season), int(episode)))
    elif year:
        parts.append(str(int(year)))
    return " ".join(p for p in parts if p)


# --------------------------------------------------------------------------- reading a page
def _num(text):
    digits = re.sub(r"\D", "", str(text if text is not None else ""))
    return int(digits) if digits else 0


def _first(obj, keys):
    for k in keys:
        if obj.get(k) not in (None, ""):
            return obj.get(k)
    return ""


def _magnet(hash_, name):
    return "magnet:?xt=urn:btih:%s&dn=%s%s" % (
        hash_, quote(name), "".join("&tr=" + quote(t, safe="") for t in TRACKERS))


def _find_items(node, depth=0):
    if depth > 3:
        return None
    if isinstance(node, list):
        if node and all(isinstance(x, dict) for x in node) and any(
                _first(x, ["name", "title", "torrent_name", "release"]) for x in node):
            return node
        return None
    if isinstance(node, dict):
        for v in node.values():
            found = _find_items(v, depth + 1)
            if found:
                return found
    return None


def _from_json(data):
    out = []
    for o in _find_items(data) or []:
        title = str(_first(o, ["name", "title", "torrent_name", "release"]))
        magnet = str(_first(o, ["magnet", "magnet_link", "magnetLink", "magnet_uri", "magnetUri"]))
        hash_ = str(_first(o, ["info_hash", "infohash", "infoHash", "hash", "btih"]))
        seeders = _num(_first(o, ["seeders", "seeds", "seed", "se"]))
        ident = str(o.get("identifier") or "")
        if not magnet.lower().startswith("magnet:?"):
            if re.fullmatch(r"[0-9a-fA-F]{40}", hash_):
                magnet = _magnet(hash_, title)
            elif re.fullmatch(r"[A-Za-z0-9._-]+", ident):      # archive.org item: its .torrent file
                magnet = "https://archive.org/download/%s/%s_archive.torrent" % (ident, ident)
                seeders = _num(o.get("downloads"))              # popularity stands in for seeders
            else:
                magnet = ""
        if title and magnet:
            out.append({"title": title, "source": magnet, "seeders": seeders,
                        "size": _num(_first(o, ["size", "size_bytes", "bytes", "item_size", "total_size"]))})
    return out


def _size_from_text(text):
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(KiB|MiB|GiB|TiB|KB|MB|GB|TB)\b", text, re.I)
    if not m:
        return 0
    mult = {"k": 1024, "m": 1048576, "g": 1073741824, "t": 1099511627776}[m.group(2)[0].lower()]
    return int(float(m.group(1).replace(",", ".")) * mult)


def _from_html(text):
    out, seen = [], set()
    for m in re.finditer(r"""href\s*=\s*["'](magnet:\?[^"']+)["']""", text, re.I):
        href = html.unescape(m.group(1))
        hm = re.search(r"btih:([0-9a-z]{32,40})", href, re.I)
        if not hm or hm.group(1).lower() in seen:
            continue
        seen.add(hm.group(1).lower())
        start = text.rfind("<tr", 0, m.start())
        if start < 0 or m.start() - start > 4000:
            start = max(0, m.start() - 800)
        end = text.find("</tr>", m.end())
        if end < 0 or end - m.end() > 4000:
            end = min(len(text), m.end() + 800)
        row = text[start:end]
        title = ""
        dn = re.search(r"[?&]dn=([^&]+)", href)
        if dn:
            title = re.sub(r"\+", " ", dn.group(1))
            title = re.sub(r"%([0-9A-Fa-f]{2})", lambda x: chr(int(x.group(1), 16)), title)
        if len(title) < 6:
            for link in re.finditer(r"<a\b[^>]*>(.*?)</a>", row, re.S | re.I):
                t = html.unescape(re.sub(r"<[^>]+>", "", link.group(1))).strip()
                if len(t) > len(title):
                    title = t
        seeders = -1
        sm = re.search(r"""class\s*=\s*["'][^"']*seed[^"']*["'][^>]*>\s*(?:<[^>]+>\s*)*(\d[\d,]*)""", row, re.I)
        if sm:
            seeders = _num(sm.group(1))
        else:
            cells = re.findall(r"<td[^>]*>\s*(\d[\d,]*)\s*</td>", row, re.I)
            if len(cells) >= 2:
                seeders = _num(cells[0])
        out.append({"title": title, "source": href, "seeders": seeders, "size": _size_from_text(row)})
    return out


def _from_rss(text):
    """RSS / XML feeds (BT4G): one <item> per release; the info-hash sits in the link / guid / description."""
    def dec(x):
        x = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", str(x or ""), flags=re.S)
        return html.unescape(x)
    out, seen = [], set()
    for raw in re.findall(r"<item[\s>].*?</item>", text, re.S | re.I):
        item = dec(raw)
        tm = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
        title = re.sub(r"<[^>]+>", "", dec(tm.group(1))).strip() if tm else ""
        hm = re.search(r"btih:([0-9a-f]{40})", item, re.I) or re.search(r"(?<![0-9a-f])([0-9a-f]{40})(?![0-9a-f])", item, re.I)
        if not title or not hm or hm.group(1).lower() in seen:
            continue
        seen.add(hm.group(1).lower())
        sm = re.search(r"(?:seeders?|seeds?)\D{0,12}(\d[\d,]*)", item, re.I)
        out.append({"title": title, "source": _magnet(hm.group(1), title),
                    "seeders": _num(sm.group(1)) if sm else -1, "size": _size_from_text(item)})
    return out


def parse_body(text):
    t = str(text or "").strip()
    if t[:1] in ("{", "["):
        try:
            return _from_json(json.loads(t))
        except ValueError:
            pass
    if t[:1] == "<" and re.search(r"<item[\s>]", t, re.I):
        rss = _from_rss(t)
        if rss:
            return rss
    return _from_html(t)


# --------------------------------------------------------------------------- scoring
def _episode_match(name, season, episode):
    n = name.lower()
    s, e = int(season), int(episode)
    if re.search(r"s0*%d[ ._-]?e0*%d(?!\d)" % (s, e), n) or re.search(r"(?<!\d)%dx0*%d(?!\d)" % (s, e), n):
        return "episode"
    if re.search(r"s0*%d(?!\d|e)" % s, n) or re.search(r"season[ ._-]*0*%d(?!\d)" % s, n):
        return "pack"
    return None


def _quality(name):
    n = normalize(name)
    if re.search(r"\b(2160p|4k|uhd)\b", n):
        return 2160
    for q in (1080, 720, 480):
        if "%dp" % q in n:
            return q
    return 0


# --------------------------------------------------------------------------- what a release is, what a device can play
def traits(name):
    """What a release is made of, read from its name (HDR, Dolby Vision, codec, 10-bit, remux)."""
    n = normalize(name)
    ql = _quality(name)
    dv = bool(re.search(r"\b(dv|dovi|dolby vision)\b", n))
    hdr_word = bool(re.search(r"\b(hdr10|hdr|hlg)\b", n)) and not re.search(r"\bsdr\b", n)
    hevc = bool(re.search(r"\b(x265|h265|h 265|hevc)\b", n))
    hdr = hdr_word or dv
    return {
        "q": ql, "hdr": hdr, "hdr_word": hdr_word, "dv": dv, "hevc": hevc,
        "av1": bool(re.search(r"\bav1\b", n)),
        "avc": bool(re.search(r"\b(x264|h264|h 264|avc)\b", n)),
        "bit10": hdr or bool(re.search(r"\b(10 ?bit|hi10p?)\b", n)) or (hevc and ql == 2160),   # HDR and 4K HEVC are 10-bit
        "remux": bool(re.search(r"\b(remux|bdremux)\b", n)),
    }


def tag_text(t):
    tags = []
    if t["dv"]:
        tags.append("Dolby Vision")
    if t["hdr_word"]:
        tags.append("HDR")
    if t["av1"]:
        tags.append("AV1")
    elif t["hevc"]:
        tags.append("HEVC")
    elif t["avc"]:
        tags.append("H.264")
    if t["remux"]:
        tags.append("Remux")
    return " \u00b7 ".join(tags)


_STEPS = [480, 720, 1080, 2160]


def read_device(p):
    """Hesper's device profile (pek.device.profile()) -> what the ranking needs.
    None = nothing known (not the Android app, or the check failed): nothing changes then."""
    if not isinstance(p, dict) or p.get("unknown") or p.get("v") != 1:
        return None
    avc, hevc = int(p.get("h264") or 0), int(p.get("hevc") or 0)
    hevc10, av1 = int(p.get("hevc10") or 0), int(p.get("av1") or 0)
    if not avc and not hevc:
        return None                                   # no hardware decoder reported at all: do not trust it
    short, tv, hdr_screen = int(p.get("screenShort") or 0), p.get("tv") is True, p.get("hdr") is True
    # The tallest picture worth sending to this screen. A 1080p phone gets 4K only when it can show HDR10
    # AND decode 10-bit HEVC in hardware; a small / low-resolution screen gains nothing from more than 720p.
    if tv or short >= 1440:
        screen_cap = 2160
    elif short >= 1080:
        screen_cap = 2160 if (hdr_screen and hevc10 >= 2160) else 1080
    elif short >= 1000:
        screen_cap = 1080
    else:
        screen_cap = 720 if short > 0 else 2160
    target = min(max(avc, hevc), screen_cap)
    return {"avc": avc, "hevc": hevc, "hevc10": hevc10, "av1": av1, "hdr_screen": hdr_screen,
            "dv": p.get("dv") is True, "tv": tv, "short": short, "target": target,
            "big": target >= 2160 and hevc10 >= 2160}


def _decode_height(t, dev):
    """Tallest picture this device's hardware decodes for a release of this make (0 = software decoding)."""
    if t["av1"]:
        return dev["av1"]
    if t["avc"] and t["bit10"] and not t["hevc"]:
        return 0                                      # 10-bit H.264 (Hi10P): no phone / TV decodes it in hardware
    if t["hevc"] or (t["bit10"] and not t["avc"]):
        return dev["hevc10"] if t["bit10"] else dev["hevc"]
    return dev["avc"]                                 # H.264, or a name that does not say


def device_fit(t, dev):
    """(points to add or take off, will it probably stutter) for this device."""
    adj, heavy, dh = 0, False, _decode_height(t, dev)
    if dh == 0 or (t["q"] and dh < t["q"]):
        adj -= 60                                     # beyond the hardware decoder: software decoding, stutters
        heavy = True
    elif t["hdr"]:
        adj += 10 if dev["hdr_screen"] else -8        # HDR screen: shown as made. SDR screen: tone-mapped (more GPU work)
        if t["dv"] and not t["hdr_word"] and not dev["dv"]:
            adj -= 12                                 # Dolby Vision only: no HDR10 layer to fall back on
    if t["q"] == 2160 and not dev["tv"] and 0 < dev["short"] < 1000:
        adj -= 10                                     # 4K on a small screen: nothing to see
    return adj, heavy


def _quality_points(ql, dev):
    if not ql:
        return 0
    if not dev:
        return {2160: 12, 1080: 15, 720: 8, 480: 2}.get(ql, 0)       # as always
    # A device that can play 4K HDR10 weighs resolution more: top quality should beat a slightly better-seeded 1080p.
    step, d = (12 if dev["big"] else 6), abs(_STEPS.index(ql) - _STEPS.index(dev["target"]))
    return max(0, (30 if dev["big"] else 18) - step * d)


def _size_text(b):
    if not b or b < 2:
        return "size unknown"
    units, i, v = ["B", "KB", "MB", "GB", "TB"], 0, float(b)
    while v >= 1024 and i < len(units) - 1:
        v /= 1024
        i += 1
    return ("%.2f %s" if i >= 3 else "%.0f %s") % (v, units[i])


def score(item, title, season=0, episode=0, year=0, dev=None):
    """A number, or None when the result should be dropped. dev = read_device(...) ranks for that device.
    Returns (score, tags, heavy) through score_full(); score() keeps returning just the number."""
    r = score_full(item, title, season, episode, year, dev)
    return None if r is None else r[0]


def _is_blocked(item):
    """True when the release is a program or archive, not video: its name (or the magnet's dn=) ends in .exe, .msi, .bat, .scr or .zip."""
    names = [str(item.get("title") or "")]
    dn = re.search(r"[?&]dn=([^&]+)", str(item.get("source") or ""))
    if dn:
        names.append(unquote_plus(dn.group(1)))
    return any(re.search(r"\.(?:exe|msi|bat|scr|zip)[\s\"')\]]*$", n.strip(), re.I) for n in names)


def score_full(item, title, season=0, episode=0, year=0, dev=None):
    """(score, tags, heavy), or None when the result should be dropped."""
    if _is_blocked(item):
        return None
    name = item["title"]
    norm = normalize(name)
    padded = " " + norm + " "
    if item["seeders"] == 0:
        return None
    # The title must appear as a phrase ("breaking bad"), not as loose words:
    # "The Bad Guys: Breaking In" has both words but is a different title.
    words = normalize(title).split()
    if words and (" %s " % " ".join(words)) not in padded:
        return None
    total = 0.0
    if season and episode:
        kind = _episode_match(name, season, episode)
        if kind is None:
            return None
        total += 60 if kind == "episode" else 15
    elif year:
        if re.search(r"(?<!\d)%d(?!\d)" % int(year), name):
            total += 25
        elif re.search(r"(?<!\d)(19|20)\d\d(?!\d)", name):
            return None
    # Not a full movie/episode: trailers, commercials, clips and tiny files.
    if re.search(r"\b(trailer|teaser|commercial|promo|featurette|behind the scenes|review|reaction|clips?|sample|soundtrack|ost)\b", norm):
        return None
    if item["size"] > 1 and item["size"] < (40 if (season and episode) else 350) * 1048576:
        return None
    t = traits(name)
    q = t["q"]
    total += _quality_points(q, dev)
    adj, heavy = device_fit(t, dev) if dev else (0, False)
    total += adj
    if re.search(r"\b(cam|camrip|hdcam|ts|hdts|telesync|tc)\b", norm):
        return None
    if item["seeders"] > 0:
        total += min(math.log10(item["seeders"] + 1) * 20, 60)
    # Streaming needs the download to stay ahead of the picture: prefer comfortable sizes, avoid remux / 4K.
    gb = item["size"] / 1073741824.0 if item["size"] > 1 else 0
    is_ep = bool(season and episode)
    # A device that can really play 4K HDR10 gets a much roomier size allowance, and 4K / remux are not marked down.
    big = bool(dev and dev["big"])
    if gb and not (is_ep and _episode_match(name, season, episode) == "pack"):
        sweet, per = ((5, 12) if big else (1.6, 12)) if is_ep else ((14, 6) if big else (3.5, 6))
        if gb > sweet:
            total -= min(25, (gb - sweet) * per)
    if not big:
        if re.search(r"\b(remux|bdremux|uhd bluray|complete bluray|bluray disc)\b", norm):
            total -= 20
        if q == 2160:
            total -= 10
    return total, tag_text(t), heavy


# --------------------------------------------------------------------------- public entry
def find_releases(title, season=0, episode=0, year=0, sites=None, dev=None):
    """Query every site, parse, drop bad results, score. Best first.
    dev = read_device(profile): rank for what that device can decode / show (None = the usual ranking)."""
    variants = [build_query(title, season, episode, year)]
    if year and not (season and episode):
        variants.append(normalize(title))          # some sites do better without the year
    items, last_error = [], None
    for words in variants:
        for tmpl in (sites if sites is not None else SITES):
            try:
                body = h.fetch_text(tmpl.replace("{q}", quote_plus(words)),
                                    headers={"User-Agent": USER_AGENT}, timeout=8, max_bytes=1000000)
                items.extend(parse_body(body))
            except Exception as err:  # one broken site must not stop the others
                last_error = err
        if items:
            break
    if not items and last_error is not None:
        raise last_error
    ranked, seen = [], set()
    for it in items:
        full = score_full(it, title, season, episode, year, dev)
        key = it["source"].lower()
        if full is None or key in seen:
            continue
        seen.add(key)
        ranked.append((full[0], it, full[1], full[2]))
    ranked.sort(key=lambda p: p[0], reverse=True)
    return [{
        "title": it["title"], "source": it["source"], "seeders": max(0, it["seeders"]),
        "size": it["size"], "size_text": _size_text(it["size"]), "quality": _quality(it["title"]),
        "pack": bool(season and episode and _episode_match(it["title"], season, episode) == "pack"),
        "score": round(sc, 1), "tags": tags, "heavy": heavy,
    } for sc, it, tags, heavy in ranked][:25]


def find_best_release(title, season=0, episode=0, year=0, sites=None, dev=None):
    found = find_releases(title, season, episode, year, sites, dev)
    return found[0] if found else None
