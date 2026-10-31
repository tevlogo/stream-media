"""Stream Media for the Flutter UI (the Python twin of ui.js).

Home / Movies / TV Shows tabs with a featured title, rows (trending, top rated, coming soon, genres), Categories,
streaming-service filters, ratings on every poster, a detail page with trailer, cast, director / creator, networks,
where to watch, seasons and episodes, and Play: the plugin's own release search (stream_search.py, which reads your
sites from release_search.py) finds the best stream and PEK plays it.

TMDb comes from this plugin's own worker (PROXY below), or straight from TMDb with a personal key.
Data: TMDb. Streaming availability: JustWatch (via TMDb). Trailers: YouTube.
"""
import json
import random
import re
import time
import unicodedata
from urllib.parse import quote

import pek_host as h
import pek_ui as ui
import release_search as rs
import stream_search as ss

API = "https://api.themoviedb.org/3"                                   # only used with a personal key
PROXY = "https://snake-skin-tmdb.aquariusibeats.workers.dev"          # the plugin's own TMDb worker (holds its key)
IMG = "https://image.tmdb.org/t/p/w342"
IMG_WIDE = "https://image.tmdb.org/t/p/w780"          # backdrops (kept on items; cards are portrait now)
IMG_THUMB = "https://image.tmdb.org/t/p/w92"          # the small picture beside a search suggestion
IMG_PERSON = "https://image.tmdb.org/t/p/w185"
IMG_LOGO = "https://image.tmdb.org/t/p/w92"
IMG_STILL = "https://image.tmdb.org/t/p/w300"             # episode stills (16:9)
MAX_PAGES = 500          # TMDb does not serve pages past 500
SETTINGS = "settings.json"
LIBRARY = "library.json"

MOVIE_GENRES = [(28, "Action"), (12, "Adventure"), (16, "Animation"), (35, "Comedy"), (80, "Crime"),
                (99, "Documentary"), (18, "Drama"), (10751, "Family"), (14, "Fantasy"), (36, "History"),
                (27, "Horror"), (10402, "Music"), (9648, "Mystery"), (10749, "Romance"), (878, "Sci-Fi"),
                (53, "Thriller"), (10752, "War"), (37, "Western")]
TV_GENRES = [(10759, "Action & Adventure"), (16, "Animation"), (35, "Comedy"), (80, "Crime"), (99, "Documentary"),
             (18, "Drama"), (10751, "Family"), (10762, "Kids"), (9648, "Mystery"), (10764, "Reality"),
             (10765, "Sci-Fi & Fantasy"), (10766, "Soap"), (10768, "War & Politics"), (37, "Western")]
MOVIE_GENRE_ROWS = [28, 35, 18, 878, 27, 16]       # shown as rows on the Movies tab
TV_GENRE_ROWS = [10759, 18, 35, 10765, 80, 16]     # shown as rows on the TV tab
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

PREFERRED = ["netflix", "hulu", "disney plus", "max", "hbo max", "amazon prime video", "prime video",
             "apple tv plus", "apple tv+", "paramount plus", "paramount+", "peacock", "peacock premium",
             "crunchyroll", "tubi tv", "pluto tv", "youtube"]
LABELS = {"disney plus": "Disney+", "apple tv plus": "Apple TV+", "paramount plus": "Paramount+",
          "amazon prime video": "Prime Video", "peacock premium": "Peacock", "tubi tv": "Tubi",
          "pluto tv": "Pluto TV"}

# ---------------------------------------------------------------- state
S = {
    "ready": False,
    "key": "", "key_draft": "", "key_msg": "",
    "region": "", "region_draft": "",
    "autoplay": True,        # play the trailer when a detail page opens
    "sound": True,           # trailer sound
    "compact": True,         # prefer smaller releases: they start sooner and scrub smoother
    "fit": True,             # rank releases for the device when PEK reports what it can decode
    "pick": False,           # True = show the release list and let me choose
    "tab": "home",           # 'home' | 'movie' | 'tv' | 'settings'
    "provider": 0,           # TMDb provider id, 0 = all services
    "providers": {"movie": None, "tv": None},
    "prov_fail": {"movie": False, "tv": False},
    "pages": {},             # page key -> {"loading"} | {"items", "total"} | {"error"}
    "list": None,            # None | {"src", "title", "page", "total", "search"}
    "detail": None,          # None | {"item", "loading", "info", "error", "play"}
    "hist": [],
    "query": "",
    "sug": [],               # search suggestions for what is typed (items), shown under the search box
    "sug_cache": {},         # typed text (lower case) -> suggestion items
    "show_cats": False,
    "hero_pick": {},
    "inflight": 0,           # browse pages being fetched (lazy rows wait their turn)
    "lib": {"movies": {}, "shows": {}, "n_movies": 0, "n_shows": 0, "loaded": False},
    "auth_error": False,
    "favs": {}, "favs_seen": None, "fav_msg": "",
    "trailer_open": "",
}


# ---------------------------------------------------------------- layout
def tv_mode():
    return bool(ui.ctx().get("tv"))


def lay():
    if tv_mode():
        return {"per_row": 20, "genre_rows": 6, "col": 150, "hero": 170, "text": 400, "cast": 20, "related": 20,
                "eps": 50, "facts": 4, "cast_col": 120}
    return {"per_row": 12, "genre_rows": 3, "col": 140, "hero": 120, "text": 140, "cast": 12, "related": 12,
            "eps": 25, "facts": 2, "cast_col": 110}


# ---------------------------------------------------------------- helpers
def lang():
    return str(ui.ctx().get("lang") or "en-US")


def device_region():
    r = str(ui.ctx().get("region") or "US").upper()
    return r if re.match(r"^[A-Z]{2}$", r) else "US"


def region():
    return S["region"] or device_region()


def norm(s):
    """Lower case, no accents, no punctuation, no (1999) suffix, '&' = 'and', leading the/a/an dropped."""
    raw = str(s or "")
    t = unicodedata.normalize("NFKD", raw.lower())
    t = re.sub(r"[\u0300-\u036f]", "", t)
    t = t.replace("&", " and ")
    t = re.sub(r"\(\s*(?:19|20)\d\d\s*\)\s*$", " ", t)
    t = re.sub(r"['\u2019`]", "", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^(?:the|a|an) ", "", t)
    return t or raw.strip().lower()


def year_of(date):
    try:
        y = int(str(date or "")[:4])
    except ValueError:
        return 0
    return y if y > 1800 else 0


def today():
    import datetime
    return datetime.date.today().isoformat()


def fmt_date(d):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", str(d or ""))
    if not m:
        return ""
    return "%s %d, %s" % (MONTHS[int(m.group(2)) - 1], int(m.group(3)), m.group(1))


def fmt_runtime(minutes):
    try:
        n = int(minutes)
    except (TypeError, ValueError):
        return ""
    if n < 1:
        return ""
    hrs, mins = n // 60, n % 60
    if hrs:
        return "%dh%s" % (hrs, " %dm" % mins if mins else "")
    return "%d min" % mins


def thousands(n):
    s = str(int(n or 0))
    while True:
        t = re.sub(r"^(-?\d+)(\d{3})", r"\1,\2", s)
        if t == s:
            return s
        s = t


def clip(s, n):
    t = " ".join(str(s or "").split())
    if len(t) <= n:
        return t
    return re.sub(r"\s+\S*$", "", t[:n - 1]) + "\u2026"


def map_item(r, kind):
    t = r.get("media_type") if r.get("media_type") in ("tv", "movie") else kind
    date = r.get("first_air_date") if t == "tv" else r.get("release_date")
    title = (r.get("name") if t == "tv" else r.get("title")) or r.get("title") or r.get("name") or "Untitled"
    alt = (r.get("original_name") if t == "tv" else r.get("original_title")) or ""
    vote = r.get("vote_average")
    return {
        "id": r.get("id"), "type": t, "title": str(title), "alt": str(alt), "year": year_of(date),
        "date": str(date or ""),
        "poster": IMG + r["poster_path"] if r.get("poster_path") else "",
        "poster_path": r.get("poster_path") or "",
        "backdrop": IMG_WIDE + r["backdrop_path"] if r.get("backdrop_path") else "",
        "overview": str(r.get("overview") or ""),
        "rating": float(vote) if isinstance(vote, (int, float)) else 0.0,
        "votes": r.get("vote_count") or 0,
    }


def stub_item(tmdb_id, kind, title, year):
    return {"id": tmdb_id, "type": kind, "title": title, "alt": "", "year": year, "date": "", "poster": "",
            "poster_path": "", "backdrop": "", "overview": "", "rating": 0.0, "votes": 0}


def owned(item):
    names = [norm(item["title"])]
    if item.get("alt"):
        names.append(norm(item["alt"]))
    if item["type"] == "tv":
        for n in names:
            if n in S["lib"]["shows"]:
                return True
        return False
    for n in names:
        years = S["lib"]["movies"].get(n)
        if not years:
            continue
        if not item["year"]:
            return True
        for y in years:
            if not y or abs(y - item["year"]) <= 1:
                return True
    return False


def not_out_yet(item):
    return bool(item.get("date") and item["date"] > today())


def err_text(msg):
    m = str(msg or "")
    if re.search(r"HTTP (401|403)", m):
        if S["key"]:
            return "TMDb rejected your API key. Check it in Settings."
        return "The built-in TMDb access was refused. Try again later, or add your own key in Settings."
    if re.search(r"HTTP 404", m):
        return "TMDb could not find that (404)."
    if re.search(r"HTTP 429", m):
        return "TMDb is busy right now (429). Try again in a moment."
    if re.search(r"HTTP 5\d\d", m):
        return "TMDb had a problem (" + m.replace("HTTP ", "")[:40] + "). Try again later."
    if re.search(r"larger than", m):
        return "TMDb sent more data than PEK allows."
    if re.search(r"time", m, re.I):
        return "TMDb took too long to answer."
    return "Couldn't reach TMDb. Check your connection."


def is_auth(msg):
    return re.search(r"HTTP (401|403)", str(msg or "")) is not None


def api(path, params=None):
    """Blocking: only call this from inside ui.background()."""
    q = ["language=" + quote(lang(), safe="")]
    if S["key"]:
        q.insert(0, "api_key=" + quote(S["key"], safe=""))
    p = params or {}
    for k in sorted(p.keys()):
        q.append(quote(str(k), safe="") + "=" + quote(str(p[k]), safe=""))
    # Personal key: straight to TMDb. No key: this plugin's own worker (it adds the key).
    url = (API if S["key"] else PROXY) + path + "?" + "&".join(q)
    # A first try that fails is usually a hiccup (the phone just woke up, the proxy was cold, TMDb said 429 / 5xx), and
    # a list that failed used to stay empty (no pictures) until it was refreshed by hand. Try again a couple of times
    # inside this one background job, but never past the 25 second limit a job has.
    t0 = time.monotonic()
    wait = 1.0
    while True:
        try:
            return h.fetch_json(url, timeout=8)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            final = re.search(r"HTTP (401|403|404)", msg) is not None      # a key / not-found answer will not change
            if final or time.monotonic() - t0 > 11:
                raise
            time.sleep(wait)
            wait = min(wait * 2, 3.0)


def fav_key(item):
    return "%s:%s" % (item["type"], item["id"])


def sync_favs():
    cur = tuple(sorted(str(k) for k in (ui.ctx().get("favorites") or [])))
    if cur != S["favs_seen"]:
        S["favs_seen"] = cur
        S["favs"] = dict((k, True) for k in cur)


def merged(a, b):
    o = dict(a)
    o.update(b)
    return o


# ---------------------------------------------------------------- settings and library (data/ folder)
def load_settings():
    try:
        j = h.read_json(SETTINGS)
    except Exception:
        return
    if not isinstance(j, dict):
        return
    k = str(j.get("key") or "")
    if re.match(r"^[0-9a-fA-F]{32}$", k):
        S["key"] = k
    r = str(j.get("region") or "").upper()
    if re.match(r"^[A-Z]{2}$", r):
        S["region"] = r
    S["autoplay"] = j.get("autoplay") is not False
    S["sound"] = j.get("sound") is not False
    S["compact"] = j.get("compact") is not False
    S["fit"] = j.get("fit") is not False
    S["pick"] = j.get("pick") is True


def save_settings():
    data = {}
    if S["key"]:
        data["key"] = S["key"]
    if S["region"]:
        data["region"] = S["region"]
    for name in ("autoplay", "sound", "compact", "fit"):
        if not S[name]:
            data[name] = False
    if S["pick"]:
        data["pick"] = True
    try:
        h.write_json(SETTINGS, data)
        return True
    except Exception:
        return False


def build_library(movie_rows, show_rows):
    movies, shows, nm, ns = {}, {}, 0, 0
    for m in movie_rows:
        k = norm(m.get("title"))
        if not k:
            continue
        try:
            y = int(m.get("year") or 0)
        except (TypeError, ValueError):
            y = 0
        movies.setdefault(k, []).append(y)
        nm += 1
    for sh in show_rows:
        k = norm(sh.get("title"))
        if k:
            shows[k] = True
            ns += 1
    return {"movies": movies, "shows": shows, "n_movies": nm, "n_shows": ns, "loaded": True}


def read_library():
    try:
        j = h.read_json(LIBRARY)
    except Exception:
        return
    S["lib"] = build_library(j.get("movies", []), j.get("shows", []))


def refresh_library():
    def work():
        return h.library_titles()

    def done(rows):
        if not rows:
            return
        S["lib"] = build_library([r for r in rows if r.get("kind") == "movie"],
                                 [r for r in rows if r.get("kind") != "movie"])

    ui.background(work, done, lambda msg: None)


# ---------------------------------------------------------------- numbered pages
def page_key(src, page):
    return src["path"] + "?" + json.dumps(src.get("params") or {}, sort_keys=True) + "#" + str(page)


def extract(src, j):
    if src.get("credits"):             # an actor's films and shows, best known first
        seen, res = {}, []
        for r in j.get("cast", []):
            if r.get("media_type") not in ("movie", "tv"):
                continue
            k = r["media_type"] + str(r.get("id"))
            if k in seen:
                continue
            seen[k] = 1
            res.append(r)
        res.sort(key=lambda r: -(r.get("popularity") or 0))
        return {"items": [map_item(r, r["media_type"]) for r in res[:60]], "total": 1}
    res = j.get("results", [])
    if src.get("multi"):
        res = [r for r in res if r.get("media_type") in ("movie", "tv")]
    return {"items": [map_item(r, src["type"]) for r in res],
            "total": max(1, min(int(j.get("total_pages") or 1), MAX_PAGES))}


def load_page(src, page):
    k = page_key(src, page)
    if k in S["pages"]:
        return
    S["pages"][k] = {"loading": True}
    S["inflight"] += 1
    p = dict(src.get("params") or {})
    if src.get("paged", True):
        p["page"] = page

    def work():
        return api(src["path"], p)

    def done(j):
        S["inflight"] -= 1
        S["pages"][k] = extract(src, j)
        cur = S["list"]
        if cur and cur["page"] == page and page_key(cur["src"], page) == k:
            cur["total"] = S["pages"][k]["total"]
        ensure_loaded()

    def fail(msg):
        S["inflight"] -= 1
        if is_auth(msg):
            S["auth_error"] = True
        S["pages"][k] = {"error": err_text(msg)}
        ensure_loaded()

    ui.background(work, done, fail)


def provider_params():
    return {"with_watch_providers": S["provider"], "watch_region": region(),
            "with_watch_monetization_types": "flatrate", "include_adult": "false"}


def genre_src(kind, gid):
    params = {"with_genres": gid, "sort_by": "popularity.desc", "include_adult": "false", "vote_count.gte": 20}
    if S["provider"] and S["tab"] in ("movie", "tv"):
        params = merged(params, provider_params())
    return {"path": "/discover/" + kind, "type": kind, "params": params}


def genre_name(kind, gid):
    for g in (TV_GENRES if kind == "tv" else MOVIE_GENRES):
        if g[0] == gid:
            return g[1]
    return "Genre"


def genre_title(kind, gid):
    return genre_name(kind, gid) + (" shows" if kind == "tv" else " movies")


def network_src(n):
    return {"path": "/discover/tv", "type": "tv",
            "params": {"with_networks": n["id"], "sort_by": "popularity.desc", "vote_count.gte": 10,
                       "include_adult": "false"}}


def sections_for(kind):
    reg = {"region": region()}
    if kind == "home":
        return [
            {"title": "Trending now", "path": "/trending/all/day", "type": "movie", "multi": True, "params": {}},
            {"title": "Popular movies", "path": "/movie/popular", "type": "movie", "params": reg},
            {"title": "Popular TV shows", "path": "/tv/popular", "type": "tv", "params": {}},
            {"title": "Coming soon", "path": "/movie/upcoming", "type": "movie", "params": reg, "lazy": True},
            {"title": "Top rated movies", "path": "/movie/top_rated", "type": "movie", "params": reg, "lazy": True},
            {"title": "Top rated TV shows", "path": "/tv/top_rated", "type": "tv", "params": {}, "lazy": True},
        ]
    movie = kind == "movie"
    if S["provider"]:
        base = provider_params()
        return [
            {"title": "Popular on this service", "path": "/discover/" + kind, "type": kind,
             "params": merged(base, {"sort_by": "popularity.desc"})},
            {"title": "Top rated on this service", "path": "/discover/" + kind, "type": kind,
             "params": merged(base, {"sort_by": "vote_average.desc", "vote_count.gte": 300})},
        ]
    rows = [
        {"title": "Trending this week", "path": "/trending/" + kind + "/week", "type": kind, "params": {}},
        {"title": "Top rated", "path": "/" + kind + "/top_rated", "type": kind, "params": reg if movie else {}},
        {"title": "Popular", "path": "/" + kind + "/popular", "type": kind, "params": reg if movie else {}},
        ({"title": "Now playing in theaters", "path": "/movie/now_playing", "type": kind, "params": reg}
         if movie else {"title": "On the air", "path": "/tv/on_the_air", "type": kind, "params": {}}),
        ({"title": "Coming soon", "path": "/movie/upcoming", "type": kind, "params": reg, "lazy": True}
         if movie else {"title": "Coming soon", "path": "/discover/tv", "type": kind, "lazy": True,
                        "params": {"first_air_date.gte": today(), "sort_by": "popularity.desc",
                                   "include_adult": "false"}}),
    ]
    for gid in (MOVIE_GENRE_ROWS if movie else TV_GENRE_ROWS)[:lay()["genre_rows"]]:
        g = genre_src(kind, gid)
        g["title"] = genre_title(kind, gid)
        g["lazy"] = True
        rows.append(g)
    return rows


def pick_providers(items, reg):
    rows = []
    for p in items:
        if not p or not p.get("provider_id") or not p.get("provider_name"):
            continue
        if re.search(r"channel|with ads|standard", str(p["provider_name"]), re.I):
            continue
        n = str(p["provider_name"]).lower()
        pr = (p.get("display_priorities") or {}).get(reg)
        rows.append({"id": p["provider_id"], "label": LABELS.get(n, p["provider_name"]),
                     "rank": PREFERRED.index(n) if n in PREFERRED else -1,
                     "prio": pr if isinstance(pr, (int, float)) else 999})
    pref = sorted([r for r in rows if r["rank"] >= 0], key=lambda r: r["rank"])
    rest = sorted([r for r in rows if r["rank"] < 0], key=lambda r: r["prio"])
    seen, out = {}, []
    for r in pref + rest:
        if len(out) < 12 and r["label"] not in seen:
            seen[r["label"]] = 1
            out.append({"id": r["id"], "label": r["label"]})
    return out


def load_providers(kind):
    if S["providers"][kind] is not None:
        return
    S["providers"][kind] = []
    S["prov_fail"][kind] = False
    reg = region()

    def work():
        return api("/watch/providers/" + kind, {"watch_region": reg})

    def done(j):
        S["providers"][kind] = pick_providers(j.get("results", []), reg)

    def fail(msg):
        S["providers"][kind] = []
        S["prov_fail"][kind] = True

    ui.background(work, done, fail)


def ensure_loaded():
    if S["tab"] == "settings":
        return
    cur = S["list"]
    if cur:
        e = S["pages"].get(page_key(cur["src"], cur["page"]))
        if not e:
            load_page(cur["src"], cur["page"])
        elif e.get("total"):
            cur["total"] = e["total"]
        if cur["src"].get("paged", True) and cur["page"] < (cur["total"] or 0):
            load_page(cur["src"], cur["page"] + 1)       # so Next is instant
        return
    if S["tab"] in ("movie", "tv"):
        load_providers(S["tab"])
    for sec in sections_for(S["tab"]):
        if not sec.get("lazy"):
            load_page(sec, 1)
    for sec in sections_for(S["tab"]):          # lazy rows come one at a time, after the first screen
        if sec.get("lazy") and page_key(sec, 1) not in S["pages"]:
            if S["inflight"] < 2:
                load_page(sec, 1)
            break


# ---------------------------------------------------------------- navigation
def push_view():
    if S["detail"] or S["list"]:
        S["hist"].append({"detail": S["detail"], "list": S["list"]})


def back():
    if S["hist"]:
        prev = S["hist"].pop()
        S["detail"] = prev["detail"]
        S["list"] = prev["list"]
    elif S["detail"]:
        S["detail"] = None
    elif S["list"]:
        S["list"] = None
    ensure_loaded()


def reset_views():
    S["detail"] = None
    S["list"] = None
    S["hist"] = []


def reset_data():
    S["pages"] = {}
    S["providers"] = {"movie": None, "tv": None}


def select_tab(tab_id):
    S["tab"] = tab_id
    S["provider"] = 0
    S["show_cats"] = tv_mode() and tab_id in ("movie", "tv")
    reset_views()
    if tab_id == "settings":
        S["key_draft"] = ""
        S["region_draft"] = region()
        S["key_msg"] = ""
    ui.scroll_top()
    ensure_loaded()


def pick_provider(pid):
    S["provider"] = 0 if S["provider"] == pid else pid
    reset_views()
    ensure_loaded()


def all_services():
    S["provider"] = 0
    reset_views()
    ensure_loaded()


def refresh():
    reset_data()
    S["auth_error"] = False
    S["hero_pick"] = {}
    refresh_library()
    ensure_loaded()


def retry_providers():
    S["providers"][S["tab"]] = None
    ensure_loaded()


def retry_page(src, page):
    S["pages"].pop(page_key(src, page), None)
    ensure_loaded()


def open_list(src, title, search=False):
    push_view()
    S["detail"] = None
    S["list"] = {"src": src, "title": title, "page": 1, "total": 0, "search": search}
    ui.scroll_top()
    ensure_loaded()


def open_genre(kind, gid):
    open_list(genre_src(kind, gid), genre_title(kind, gid))


def go_page(n):
    cur = S["list"]
    if not cur:
        return
    cur["page"] = max(1, min(n, cur["total"] or MAX_PAGES))
    ui.scroll_top()
    ensure_loaded()


def set_query(v):
    S["query"] = v


def type_query(text):
    """The search box paused (PEK calls this about 0.3 s after the last key): look up a few titles that match what is typed
    and show them in a drop-down under the box, each with a small poster."""
    q = " ".join(str(text or "").split())
    key = q.lower()
    if len(q) < 2:
        S["sug"] = []
        return
    if key in S["sug_cache"]:
        S["sug"] = S["sug_cache"][key]
        return

    def work():
        return api("/search/multi", {"query": q, "include_adult": "false"})

    def done(j):
        res = [r for r in (j.get("results") or []) if r.get("media_type") in ("movie", "tv")]
        items = [map_item(r, "movie") for r in res]
        items = [i for i in items if i["poster"]] + [i for i in items if not i["poster"]]     # ones with a picture first
        items = items[:6]
        if len(S["sug_cache"]) > 40:
            S["sug_cache"] = {}
        S["sug_cache"][key] = items
        if " ".join(S["query"].split()).lower() == key:       # still what is in the box
            S["sug"] = items

    ui.background(work, done, lambda msg: None)


def pick_suggestion(item):
    S["sug"] = []
    open_detail(item)


def suggestion_rows():
    rows = []
    for it in S["sug"]:
        sub = " \u00b7 ".join([str(x) for x in (it["year"] or "", "TV show" if it["type"] == "tv" else "Movie") if x])
        thumb = IMG_THUMB + it["poster_path"] if it["poster_path"] else ""
        rows.append(ui.suggestion(it["title"], sub, thumb, lambda it=it: pick_suggestion(it)))
    return rows


def search_box():
    """The search pill. With suggestions on a PEK TV that supports them; a plain pill on an older one."""
    try:
        return ui.text_input("", S["query"], set_query, placeholder="Search movies and TV shows",
                             on_submit=do_search, key="snake-search", on_type=type_query, suggestions=suggestion_rows())
    except (TypeError, AttributeError):
        return ui.text_input("", S["query"], set_query, placeholder="Search movies and TV shows",
                             on_submit=do_search, key="snake-search")


def do_search(term=None):
    S["sug"] = []
    if term is not None:
        S["query"] = term
    term = S["query"].strip()
    if not term:
        if S["list"] and S["list"]["search"]:
            S["list"] = None
        return
    S["detail"] = None
    S["hist"] = []
    S["list"] = None
    open_list({"path": "/search/multi", "params": {"query": term, "include_adult": "false"},
               "type": "movie", "multi": True}, "Results for \u201c" + term + "\u201d", True)


def clear_search():
    reset_views()
    S["query"] = ""
    S["sug"] = []


def open_person(c):
    open_list({"path": "/person/%s/combined_credits" % c["id"], "params": {}, "type": "movie",
               "credits": True, "paged": False}, c["name"])


def video_langs():
    code = (lang().split("-")[0] or "en").lower()
    return "en,null" if code == "en" else code + ",en,null"


def new_play():
    return {"season": 0, "episodes": {}, "ep_loading": False, "searching": False, "busy": False,
            "error": "", "notice": "", "none": False, "detail": "", "results": None, "label": "", "ep": 0,
            "q_season": 0, "all_eps": False, "pending": False, "job": 0, "started": ""}


def play_state(d):
    if "play" not in d:
        d["play"] = new_play()
    return d["play"]


def default_season(info):
    lst = [s for s in (info.get("seasons") or []) if (s.get("season_number") or 0) > 0 and (s.get("episode_count") or 0) > 0]
    if not lst:
        return 0
    t, pick = today(), 0
    for s in lst:
        if not pick and s.get("air_date") and s["air_date"] <= t:
            pick = s["season_number"]
    return pick or lst[0]["season_number"]


def open_detail(item, auto_play=False):
    push_view()
    d = {"item": item, "loading": True, "info": None, "error": ""}
    S["detail"] = d
    S["trailer_open"] = ""
    ui.scroll_top()

    def work():
        return api("/%s/%s" % (item["type"], item["id"]), {
            "append_to_response": "watch/providers,videos,credits,recommendations,similar,"
                                  + ("content_ratings" if item["type"] == "tv" else "release_dates"),
            "include_video_language": video_langs()})

    def done(j):
        d["info"] = j
        d["loading"] = False
        # A title opened from Favorites only knew its id: fill in the rest from TMDb's answer.
        name = j.get("name") if item["type"] == "tv" else j.get("title")
        if name and (not item["title"] or item["title"] == "Loading\u2026"):
            item["title"] = str(name)
        if not item["poster_path"] and j.get("poster_path"):
            item["poster_path"] = j["poster_path"]
            item["poster"] = IMG + j["poster_path"]
            if j.get("backdrop_path") and not item.get("backdrop"):
                item["backdrop"] = IMG_WIDE + j["backdrop_path"]
        if not item["rating"]:
            item["rating"] = float(j.get("vote_average") or 0)
            item["votes"] = j.get("vote_count") or 0
        if not item["date"]:
            item["date"] = str(j.get("release_date") or j.get("first_air_date") or "")
        if not item["year"]:
            item["year"] = year_of(item["date"])
        if not item["overview"]:
            item["overview"] = str(j.get("overview") or "")
        if not item["alt"]:
            item["alt"] = str((j.get("original_name") if item["type"] == "tv" else j.get("original_title")) or "")
        if item["type"] == "tv":
            ds = default_season(j)
            if ds:
                load_season(d, ds)
        if auto_play and S["detail"] is d:
            start_play(d)

    def fail(msg):
        if is_auth(msg):
            S["auth_error"] = True
        d["error"] = err_text(msg)
        d["loading"] = False

    ui.background(work, done, fail)


def on_launch(intent):
    """PEK opened this plugin on a title (the Favorites tab, or another plugin's button)."""
    try:
        tmdb_id = int(intent.get("id"))
    except (TypeError, ValueError):
        return
    kind = "tv" if intent.get("type") == "tv" else "movie"
    try:
        yr = int(intent.get("year") or 0)
    except (TypeError, ValueError):
        yr = 0
    S["query"] = ""
    S["sug"] = []
    reset_views()
    open_detail(stub_item(tmdb_id, kind, str(intent.get("title") or "Loading\u2026"), yr))


# ---------------------------------------------------------------- favorites, other plugins
def toggle_fav(item):
    k = fav_key(item)
    S["fav_msg"] = ""
    try:
        if k in S["favs"]:
            ui.favorite_remove(k)
            del S["favs"][k]
        else:
            ui.favorite_add(item["type"], item["id"], item["title"], item["year"], item["poster_path"])
            S["favs"][k] = True
    except Exception:
        S["fav_msg"] = "Could not update your favorites."


def open_with(plugin, item):
    S["fav_msg"] = ""
    try:
        ui.open_plugin(plugin["id"], item["type"], item["id"], item["title"], item["year"])
    except Exception:
        S["fav_msg"] = "Could not open " + plugin["name"] + "."


def release_state(item, info):
    """A title is 'out' when its date has passed and TMDb does not call it planned / in production."""
    info = info or {}
    t = today()
    date = (info.get("first_air_date") if item["type"] == "tv" else info.get("release_date")) or item.get("date") or ""
    status = str(info.get("status") or "")
    future = (not date) or date > t or re.match(r"^(Rumored|Planned|In Production|Post Production)$", status, re.I) is not None
    if item["type"] == "tv" and date and date <= t and re.match(r"^In Production$", status, re.I) and info.get("last_air_date"):
        future = False
    if not future:
        return {"out": True, "text": "", "date": date}
    verb = "premieres" if item["type"] == "tv" else "releases"
    return {"out": False, "date": date, "text": "Not out yet" + (" \u2014 " + verb + " " + fmt_date(date) if date and date > t else "")}


def streamer_buttons(item, info):
    """'Play with another plugin' for every other installed plugin that can play titles."""
    if not release_state(item, info)["out"]:
        return []
    try:
        lst = ui.streamers()
    except Exception:
        return []
    if not lst:
        return []
    return [ui.heading("Play with another plugin"),
            ui.row([ui.button(p["name"], lambda p=p: open_with(p, item)) for p in lst])]


# ---------------------------------------------------------------- settings actions
def set_flag(name, value):
    S[name] = bool(value)
    save_settings()


def set_key_draft(v):
    S["key_draft"] = v


def set_region_draft(v):
    S["region_draft"] = v


def save_key(text=None):
    if text is not None:
        S["key_draft"] = text
    k = S["key_draft"].strip()
    if not k:
        S["key_msg"] = "Paste your TMDb API key first."
        return
    if k.startswith("eyJ") or len(k) > 40:
        S["key_msg"] = "That looks like the long v4 token. Use the shorter \"API Key\" (v3) from your TMDb account."
        return
    if not re.match(r"^[0-9a-fA-F]{32}$", k):
        S["key_msg"] = "A v3 API key is 32 letters and digits. Check for missing characters."
        return
    S["key_msg"] = "Checking the key\u2026"
    previous = S["key"]
    S["key"] = k

    def work():
        return api("/configuration", {})

    def done(j):
        S["key_draft"] = ""
        S["auth_error"] = False
        reset_data()
        if save_settings():
            S["key_msg"] = "Key saved."
        else:
            S["key_msg"] = "The key works, but it could not be saved on this device. You will need to enter it again next time."

    def fail(msg):
        S["key_msg"] = err_text(msg)
        S["key"] = previous

    ui.background(work, done, fail)


def remove_key():
    S["key"] = ""
    S["key_draft"] = ""
    S["key_msg"] = "Key removed. Using the built-in access."
    S["auth_error"] = False
    reset_data()
    reset_views()
    save_settings()


def save_region(text=None):
    if text is not None:
        S["region_draft"] = text
    r = S["region_draft"].strip().upper()
    if not re.match(r"^[A-Z]{2}$", r):
        S["key_msg"] = "Use a 2-letter country code, for example US or GB."
        return
    S["region"] = r
    S["provider"] = 0
    reset_data()
    reset_views()
    S["key_msg"] = "Region set to " + r + "."
    save_settings()


def auto_region():
    S["region"] = ""
    S["region_draft"] = device_region()
    S["provider"] = 0
    reset_data()
    reset_views()
    S["key_msg"] = "Using your device region: " + device_region() + "."
    save_settings()


# ---------------------------------------------------------------- seasons and episodes
def load_season(d, n):
    P = play_state(d)
    P["season"] = n
    P["all_eps"] = False
    if not n or n in P["episodes"]:
        if P["pending"]:
            start_play(d)
        return
    P["ep_loading"] = True

    def work():
        return api("/tv/%s/season/%d" % (d["item"]["id"], n), {})

    def done(j):
        P["episodes"][n] = [{"n": e.get("episode_number"), "name": e.get("name") or "", "air": e.get("air_date") or "",
                             "runtime": e.get("runtime") or 0, "overview": e.get("overview") or "",
                             "still": e.get("still_path") or ""}
                            for e in (j.get("episodes") or [])]
        P["ep_loading"] = False
        if P["pending"] and S["detail"] is d:
            start_play(d)

    def fail(msg):
        P["error"] = err_text(msg)
        P["pending"] = False
        P["ep_loading"] = False

    ui.background(work, done, fail)


def pick_season(d, sid):
    P = play_state(d)
    P["pending"] = False
    try:
        load_season(d, int(sid))
    except ValueError:
        pass


def first_aired(P):
    t = today()
    for e in P["episodes"].get(P["season"], []):
        if e["air"] and e["air"] <= t:
            return e
    return None


# ---------------------------------------------------------------- play
def clear_msgs(P):
    P["error"] = ""
    P["notice"] = ""
    P["none"] = False
    P["detail"] = ""
    P["started"] = ""


def start_stream(d, r, season, episode, label):
    """Hands one release to PEK's player (it shows the loading box, buffers, then plays and keeps Resume Watching)."""
    P = play_state(d)
    it = d["item"]
    clear_msgs(P)
    try:
        ui.play_torrent(r["source"], label, season, episode,
                        "episode" if it["type"] == "tv" else "movie", it["title"],
                        0 if it["type"] == "tv" else it["year"], it["poster_path"])
        P["started"] = "Starting \u201c" + label + "\u201d\u2026"
    except PermissionError:
        P["error"] = "This plugin was installed without the torrent permission. Reinstall it."
    except Exception:
        P["error"] = "This version of PEK cannot start streams from a plugin screen. Update PEK."


def play_release(d, r):
    P = play_state(d)
    if P["searching"]:
        return
    start_stream(d, r, P["q_season"], P["ep"], P["label"])


def site_report(job):
    return " | ".join(job["report"])


def find_and_play(d, season, episode, label):
    P = play_state(d)
    it = d["item"]
    if P["searching"]:
        return
    clear_msgs(P)
    P["searching"] = True
    P["results"] = None
    P["label"] = label
    P["ep"] = episode
    P["q_season"] = season
    P["job"] += 1
    is_tv = it["type"] == "tv"
    attempts = []
    for t in [it["title"]] + ([it["alt"]] if it.get("alt") and it["alt"] != it["title"] else []):
        group = len(attempts)
        attempts.append((t, True, group))
        if not is_tv and it["year"]:
            attempts.append((t, False, group))      # some sites do better without the year
    job = {"id": P["job"], "d": d, "season": season if is_tv else 0, "episode": episode if is_tv else 0,
           "year": 0 if is_tv else it["year"], "attempts": attempts, "ai": 0, "items": [], "report": [],
           "left": 0, "errors": 0, "n_sites": 0, "answered": 0}
    start_attempt(job)


def stale(job):
    return job["d"].get("play", {}).get("job") != job["id"]


def start_attempt(job):
    title, with_year, _group = job["attempts"][job["ai"]]
    words = ss.query_words(title, job["season"], job["episode"], job["year"], with_year)
    templates = ss.sites()
    job["items"], job["report"], job["errors"], job["answered"] = [], [], 0, 0
    job["n_sites"] = len(templates)
    job["left"] = len(templates)
    if not templates:
        finish(job, [], "No search sites. Add one to release_search.py, then reinstall the plugin.")
        return
    for tmpl in templates:
        ui.background(lambda tmpl=tmpl: ss.fetch_site(tmpl, words, title, job["year"]),
                      lambda r: site_done(job, r),
                      lambda m, tmpl=tmpl: site_done(job, {"host": ss.host_of(tmpl), "items": [], "links": [],
                                                            "error": str(m)[:170]}))


def site_done(job, r):
    if stale(job):
        return
    job["answered"] += 1
    job["report"].append(r["host"] + ": " + (r.get("error") or r.get("note") or "no answer"))
    if r.get("error"):
        job["errors"] += 1
    job["items"].extend(r.get("items") or [])
    links = r.get("links") or []
    job["left"] += len(links) - 1
    for link in links:
        ui.background(lambda link=link: ss.fetch_release_page(link), lambda items: page_done(job, items),
                      lambda m: page_done(job, []))
    if job["left"] <= 0:
        attempt_done(job)


def page_done(job, items):
    if stale(job):
        return
    job["items"].extend(items or [])
    job["left"] -= 1
    if job["left"] <= 0:
        attempt_done(job)


def attempt_done(job):
    d = job["d"]
    it = d["item"]
    title, _with_year, group = job["attempts"][job["ai"]]
    raw = job["items"]
    if raw:
        dev = rs.read_device(ui.ctx().get("device")) if S["fit"] else None
        ranked = ss.rank(raw, title, job["season"], job["episode"], job["year"], dev, S["compact"])
        if ranked:
            finish(job, ranked, "")
            return
        skip_group = True
    else:
        skip_group = False
    nxt = job["ai"] + 1
    while nxt < len(job["attempts"]) and skip_group and job["attempts"][nxt][2] == group:
        nxt += 1
    if nxt < len(job["attempts"]):
        job["ai"] = nxt
        start_attempt(job)
        return
    if not raw and job["errors"] >= job["n_sites"] and job["n_sites"]:
        finish(job, [], "Could not get results from any search site. " + site_report(job))
        return
    note = site_report(job)
    if raw:
        note += " | %d found but all filtered out (title / year / seeders / size)" % len(raw)
    finish(job, [], note)


def finish(job, ranked, note):
    if stale(job):
        return
    d = job["d"]
    P = play_state(d)
    P["searching"] = False
    P["results"] = ranked
    if not ranked:
        P["none"] = True
        P["detail"] = note
        return
    if not S["pick"]:
        start_stream(d, ranked[0], P["q_season"], P["ep"], P["label"])


def start_play(d):
    """The Play button: checks 'not out yet', picks the movie or the first aired episode, then searches and streams."""
    it = d["item"]
    info = d["info"] or {}
    P = play_state(d)
    if P["searching"]:
        return
    clear_msgs(P)
    rel = release_state(it, info)
    if not rel["out"]:
        P["notice"] = rel["text"]
        P["pending"] = False
        return
    if it["type"] == "movie":
        P["pending"] = False
        find_and_play(d, 0, 0, it["title"] + (" (%d)" % it["year"] if it["year"] else ""))
        return
    if not P["season"]:
        P["notice"] = "Not out yet"
        return
    if P["season"] not in P["episodes"]:
        P["pending"] = True
        load_season(d, P["season"])
        return
    P["pending"] = False
    ep = first_aired(P)
    if not ep:
        P["notice"] = "Not out yet \u2014 no episode of this season has aired"
        return
    find_and_play(d, P["season"], ep["n"], "%s S%02dE%02d" % (it["title"], P["season"], ep["n"]))


def play_button_label(d):
    P = play_state(d)
    if P["searching"]:
        return "Finding a stream\u2026"
    if d["item"]["type"] == "tv" and P["season"]:
        ep = first_aired(P)
        if ep:
            return "Play S%d E%d" % (P["season"], ep["n"])
    return "Play"


def status_block(d):
    P = play_state(d)
    out = []
    if P["searching"]:
        out.append(ui.spinner("Finding the best stream for " + P["label"] + "\u2026"))
    if P["started"] and not P["searching"]:
        out.append(ui.text(P["started"]))
    if P["notice"]:
        parts = P["notice"].split(" \u2014 ")
        out.append(ui.card("\u23f3  " + parts[0], " \u2014 ".join(parts[1:]) if len(parts) > 1 else "Check back after it is released."))
    if P["none"]:
        out.append(ui.card("No streaming links available",
                           "Nothing playable was found for " + (P["label"] or d["item"]["title"]) + ". Try again later."))
        if P["detail"]:
            out.append(ui.text(P["detail"]))
    if P["error"]:
        out.append(ui.text(P["error"]))
    return out


def episode_rows(d):
    it = d["item"]
    P = play_state(d)
    out = []
    info = d["info"] or {}
    seasons = [s for s in (info.get("seasons") or []) if (s.get("season_number") or 0) > 0 and (s.get("episode_count") or 0) > 0]
    if not seasons:
        return [ui.text("No episodes are listed for this show yet.")]
    out.append(ui.heading("Episodes"))
    out.append(ui.tabs([(str(s["season_number"]), "S%d" % s["season_number"]) for s in seasons],
                       str(P["season"] or ""), lambda sid: pick_season(d, sid)))
    if P["ep_loading"]:
        out.append(ui.spinner("Loading episodes\u2026"))
    eps = P["episodes"].get(P["season"], [])
    t = today()
    shown = eps if P["all_eps"] else eps[:lay()["eps"]]
    for e in shown:
        aired = bool(e["air"]) and e["air"] <= t
        if aired:
            sub = " \u00b7 ".join([x for x in (fmt_date(e["air"]), fmt_runtime(e["runtime"])) if x])
        else:
            sub = "Not out yet \u2014 airs " + fmt_date(e["air"]) if e["air"] else "Not out yet \u2014 not announced"
        etitle = "E%s \u00b7 %s" % (e["n"], e["name"] or "Episode %s" % e["n"])
        go = lambda e=e, aired=aired: play_episode(d, e, aired)
        if hasattr(ui, "episode_row"):      # newer PEK: the episode's picture and description
            out.append(ui.episode_row(etitle, sub, clip(e["overview"], 600), IMG_STILL + e["still"] if e["still"] else "",
                                      dim=not aired, on=go))
        else:                               # older PEK: the plain row
            if e["overview"]:
                sub = (sub + "\n" if sub else "") + clip(e["overview"], 160)
            out.append(ui.list_row(etitle, sub, go))
    if not P["all_eps"] and len(eps) > len(shown):
        out.append(ui.button("Show all %d episodes" % len(eps), lambda: set_all_eps(P)))
    return out


def set_all_eps(P):
    P["all_eps"] = True


def play_episode(d, e, aired):
    P = play_state(d)
    if P["searching"]:
        return
    if not aired:
        clear_msgs(P)
        P["notice"] = "Not out yet \u2014 airs " + fmt_date(e["air"]) if e["air"] else "Not out yet"
        return
    find_and_play(d, P["season"], e["n"], "%s S%02dE%02d" % (d["item"]["title"], P["season"], e["n"]))


def watch_block(d):
    it = d["item"]
    info = d["info"] or {}
    P = play_state(d)
    rel = release_state(it, info)
    kids = []
    if not rel["out"]:
        kids.append(ui.card("\u23f3  Not out yet", ("Premieres " if it["type"] == "tv" else "Releases ") + fmt_date(rel["date"])
                            if rel["date"] and rel["date"] > today() else "No release date announced yet."))
        return kids
    kids.append(ui.button(play_button_label(d), lambda: start_play(d), primary=True, autofocus="play:%s%s" % (it["type"], it["id"])))
    kids.append(ui.text("You will be asked to choose a release." if S["pick"] else "The best available stream is chosen automatically."))
    kids.extend(status_block(d))
    if it["type"] == "tv":
        kids.extend(episode_rows(d))
    if P["results"] and not P["searching"]:
        kids.append(ui.heading("Choose a stream" if S["pick"] else "Other sources"))
        for r in P["results"][:10]:
            kids.append(ui.list_row(ss.label_of(r), r["title"], lambda r=r: play_release(d, r)))
    return kids


# ---------------------------------------------------------------- views: posters and rows
def badge_for(item, mine):
    b = ""
    if not_out_yet(item):
        b = "Not out yet"
    elif item["rating"] > 0 and item["votes"] >= 5:
        b = "%.1f" % item["rating"]
    if mine:
        b = b + " \u00b7 In library" if b else "In library"
    return b


def poster(item, focus_key=""):
    sub = " \u00b7 ".join([str(x) for x in (item["year"] or "", "TV" if item["type"] == "tv" else "Movie") if x])
    mine = owned(item)
    return ui.poster_card(item["title"], sub + " \u00b7 In your library" if mine else sub, item["poster"],
                          lambda: open_detail(item), badge=badge_for(item, mine), autofocus=focus_key)


def poster_row(items, focus_key=""):
    return ui.grid([poster(it, focus_key if i == 0 else "") for i, it in enumerate(items)], min_col=lay()["col"], scroll=True)


def section_row(sec):
    e = S["pages"].get(page_key(sec, 1))
    head = ui.row(ui.heading(sec["title"]), ui.button("See all", lambda: open_list(sec, sec["title"])))
    if not e:
        return ui.column(head, ui.spinner("Waiting\u2026")) if sec.get("lazy") else ui.column(head, ui.spinner("Loading\u2026"))
    if e.get("loading"):
        return ui.column(head, ui.spinner("Loading\u2026"))
    if e.get("error"):
        return ui.column(head, ui.text(e["error"]), ui.button("Try again", lambda: retry_page(sec, 1)))
    if not e["items"]:
        return None
    cards = [poster(it) for it in e["items"][:lay()["per_row"]]]
    cards.append(ui.card("See all", "Browse every page", lambda: open_list(sec, sec["title"])))
    return ui.column(head, ui.grid(cards, min_col=lay()["col"], scroll=True))


def hero_item():
    secs = sections_for(S["tab"])
    if not secs:
        return None
    e = S["pages"].get(page_key(secs[0], 1))
    if not e or not e.get("items"):
        return None
    pool = [i for i in e["items"] if i["poster"] and len(i["overview"]) > 30][:6]
    if not pool:
        return None
    k = "%s:%s" % (S["tab"], S["provider"])
    if k not in S["hero_pick"]:
        S["hero_pick"][k] = random.randrange(len(pool))
    return pool[S["hero_pick"][k] % len(pool)]


def hero():
    it = hero_item()
    if not it:
        return None
    c = lay()
    meta = []
    if it["rating"] > 0 and it["votes"] >= 5:
        meta.append("%.1f" % it["rating"])
    if it["year"]:
        meta.append(str(it["year"]))
    meta.append("TV show" if it["type"] == "tv" else "Movie")
    gone = not_out_yet(it)
    play = (ui.button("Not out yet \u2014 details", lambda: open_detail(it), primary=True, autofocus="hero-play") if gone
            else ui.button("Play", lambda: open_detail(it, True), primary=True, autofocus="hero-play"))
    info_btn = ui.button(("More info" if tv_mode() else "Info"), lambda: open_detail(it))
    text = ui.column(ui.heading(it["title"]),
                     ui.text(" \u00b7 ".join(meta) + (" \u00b7 Not out yet" if gone else "") + (" \u00b7 In your library" if owned(it) else "")),
                     ui.text(clip(it["overview"], c["text"])),
                     ui.row(play, info_btn))
    art = ui.grid([ui.poster_card(it["title"], "", it["poster"], lambda: open_detail(it), badge=badge_for(it, owned(it)))],
                  min_col=c["hero"], scroll=True)
    return ui.column(ui.heading("Featured today" if tv_mode() else "Featured"), ui.row(art, text))


def genre_buttons(kind):
    return ui.row([ui.button(g[1], lambda g=g: open_genre(kind, g[0])) for g in (TV_GENRES if kind == "tv" else MOVIE_GENRES)])


def toggle_cats():
    S["show_cats"] = not S["show_cats"]


def categories():
    op = S["show_cats"]
    tg = ui.button("Categories", toggle_cats, selected=op)
    if not op:
        return tg
    if S["tab"] == "home":
        return ui.column(tg, ui.text("Movies"), genre_buttons("movie"), ui.text("TV shows"), genre_buttons("tv"))
    return ui.column(tg, genre_buttons(S["tab"]))


def chips():
    if S["tab"] not in ("movie", "tv"):
        return None
    lst = S["providers"][S["tab"]]
    if lst is None:
        return None
    if S["prov_fail"][S["tab"]]:
        return ui.row(ui.text("Could not load streaming services."), ui.button("Try again", retry_providers))
    if not lst:
        return ui.text("Streaming service filters are not available for region " + region() + ".")
    allb = ui.button("All services", all_services, selected=S["provider"] == 0)
    btns = [ui.button(p["label"], lambda pid=p["id"]: pick_provider(pid), selected=S["provider"] == p["id"]) for p in lst]
    return ui.column(ui.text("Streaming in " + region()), ui.row(allb, btns))


def attribution():
    return ui.column(
        ui.text("This product uses the TMDB API but is not endorsed or certified by TMDB."),
        ui.text("Streaming availability data provided by JustWatch. Trailers play from YouTube."))


# ---------------------------------------------------------------- views: detail page pieces
def pick_trailer(info):
    vids = [x for x in ((info or {}).get("videos") or {}).get("results", [])
            if x and x.get("site") == "YouTube" and re.match(r"^[A-Za-z0-9_-]{11}$", str(x.get("key") or ""))
            and x.get("type") in ("Trailer", "Teaser")]
    if not vids:
        return None
    want = (lang().split("-")[0] or "en").lower()

    def score(x):
        return (4 if x.get("type") == "Trailer" else 2) + (2 if x.get("official") else 0) + (1 if x.get("iso_639_1") == want else 0)

    vids.sort(key=lambda x: -score(x))
    return vids[0]


def certification(item, info):
    def for_region(lst, reg):
        for e in lst:
            if e.get("iso_3166_1") == reg:
                return e
        return None

    if item["type"] == "tv":
        res = (info.get("content_ratings") or {}).get("results") or []
        c = for_region(res, region()) or for_region(res, "US")
        return str(c["rating"]) if c and c.get("rating") else ""
    res = (info.get("release_dates") or {}).get("results") or []
    c = for_region(res, region()) or for_region(res, "US")
    if not c:
        return ""
    for rd in c.get("release_dates") or []:
        if rd.get("certification"):
            return str(rd["certification"])
    return ""


def names(lst, n):
    return ", ".join([str(p["name"]) for p in (lst or []) if p and p.get("name")][:n])


def cast_row(info):
    cast = [c for c in (info.get("credits") or {}).get("cast", []) if c and c.get("id") and c.get("name")][:lay()["cast"]]
    if not cast:
        return None
    cards = []
    for c in cast:
        label = c["name"] + " \u00b7 " + c["character"] if c.get("character") else c["name"]
        cards.append(ui.poster_card(label, "See their other titles",
                                    IMG_PERSON + c["profile_path"] if c.get("profile_path") else "",
                                    lambda c=c: open_person(c)))
    return ui.column(ui.heading("Cast"), ui.grid(cards, min_col=lay()["cast_col"], scroll=True))


def related_row(item, info):
    rec = (info.get("recommendations") or {}).get("results", [])
    sim = (info.get("similar") or {}).get("results", [])
    lst = [map_item(r, item["type"]) for r in (rec if rec else sim)[:lay()["related"]]]
    if not lst:
        return None
    return ui.column(ui.heading("More like this"), poster_row(lst))


def tag_rows(item, info):
    kids = []
    genres = [g for g in (info.get("genres") or []) if g and g.get("id")]
    if genres:
        kids.append(ui.text("Categories"))
        kids.append(ui.row([ui.button(g["name"], lambda g=g: open_list(
            genre_src(item["type"], g["id"]), g["name"] + (" shows" if item["type"] == "tv" else " movies"))) for g in genres]))
    nets = [n for n in (info.get("networks") or []) if n and n.get("id") and n.get("name")][:6]
    if item["type"] == "tv" and nets:
        kids.append(ui.text("Network"))
        kids.append(ui.row([ui.button(n["name"], lambda n=n: open_list(network_src(n), n["name"])) for n in nets]))
    return kids


def fact_lines(item, info):
    lines = []
    credits = info.get("credits") or {}
    if item["type"] == "tv":
        by = names(info.get("created_by"), 4)
        if by:
            lines.append("Created by: " + by)
    else:
        dn = names([c for c in (credits.get("crew") or []) if c and c.get("job") == "Director"], 3)
        if dn:
            lines.append("Directed by: " + dn)
    stars = names(credits.get("cast"), 5)
    if stars:
        lines.append("Starring: " + stars)
    studios = names(info.get("production_companies"), 3)
    if studios:
        lines.append("Studio: " + studios)
    if info.get("status"):
        lines.append("Status: " + str(info["status"]))
    return lines


def provider_buttons(item, info):
    wp = (((info or {}).get("watch/providers") or {}).get("results") or {}).get(region())
    if not wp:
        return []
    seen = {}

    def uniq(lst):
        out = []
        for p in lst or []:
            if not p or not p.get("provider_id") or not p.get("provider_name") or p["provider_id"] in seen:
                continue
            seen[p["provider_id"]] = 1
            out.append(p)
        return out[:12]

    def btns(lst):
        return ui.row([ui.provider_button(p["provider_name"], IMG_LOGO + p["logo_path"] if p.get("logo_path") else "",
                                          item["title"], item["type"], item["id"], region()) for p in lst])

    stream = uniq((wp.get("flatrate") or []) + (wp.get("free") or []) + (wp.get("ads") or []))
    buy = uniq((wp.get("rent") or []) + (wp.get("buy") or []))
    out = []
    if stream:
        out.append(ui.heading("Watch on"))
        out.append(btns(stream))
    if buy:
        out.append(ui.heading("Rent or buy"))
        out.append(btns(buy))
    return out


def open_trailer_here(key):
    S["trailer_open"] = key


def detail_view():
    d = S["detail"]
    item = d["item"]
    info = d["info"] or {}
    kids = []
    trailer = None if (d["loading"] or d["error"]) else pick_trailer(info)
    if trailer:      # the trailer goes first: PEK pins it to the very top of the page
        tkey = "%s:%s" % (item["type"], item["id"])
        if tv_mode() and not S["autoplay"] and S["trailer_open"] != tkey:
            kids.append(ui.button("Watch trailer", lambda: open_trailer_here(tkey)))
        else:
            kids.append(ui.video(trailer["key"], autoplay=S["autoplay"] or S["trailer_open"] == tkey,
                                 muted=not S["sound"], title=item["title"] + " trailer"))
    back_btn = ui.button("Back", back, autofocus="" if tv_mode() else "detail:%s%s" % (item["type"], item["id"]))
    if d["loading"]:
        kids.append(back_btn)
        kids.append(ui.spinner("Loading\u2026", True))
    else:
        is_fav = fav_key(item) in S["favs"]
        top = [back_btn, ui.button("In your favorites" if is_fav else "Add to favorites",
                                   lambda: toggle_fav(item), selected=is_fav)]
        if trailer:
            top.append(ui.button("Open in YouTube", lambda: ui.open_trailer(trailer["key"])))
        kids.append(ui.row(top))
        if S["fav_msg"]:
            kids.append(ui.text(S["fav_msg"]))
        # Your own 1 to 10 rating: the same one PEK TV shows on its posters and sends to Trakt. Plain number buttons (this plugin
        # keeps symbols out of its buttons).
        kids.append(ui.rating_stars("show" if item["type"] == "tv" else "movie", item["title"], item["year"], plain=True))
    kids.append(ui.heading(item["title"]))
    cert = certification(item, info) if info else ""
    runtime = info.get("runtime") or ((info.get("episode_run_time") or [0])[0] if info.get("episode_run_time") else 0)
    meta = []
    if item["rating"] > 0:
        meta.append("%.1f/10" % item["rating"])
    meta.append(str(item["year"]) if item["year"] else "")
    if cert:
        meta.append(cert)
    if runtime:
        meta.append(fmt_runtime(runtime))
    if info.get("number_of_seasons"):
        n = info["number_of_seasons"]
        meta.append("%s %s" % (n, "season" if n == 1 else "seasons"))
    meta.append("TV show" if item["type"] == "tv" else "Movie")
    kids.append(ui.text(" \u00b7 ".join([m for m in meta if m])))
    if item["rating"] > 0 and item["votes"]:
        kids.append(ui.text("TMDb rating from %s votes" % thousands(item["votes"])))
    if owned(item):
        kids.append(ui.text("In your library"))
    if d["error"]:
        kids.append(ui.text(d["error"]))
    elif not d["loading"]:
        kids.extend(watch_block(d))
    else:
        kids.append(ui.text("Loading\u2026"))
    if info.get("tagline"):
        kids.append(ui.text("\u201c" + str(info["tagline"]) + "\u201d"))
    overview = info.get("overview") or item["overview"]
    kids.append(ui.text(overview or ("Loading\u2026" if d["loading"] else "No description available.")))
    if not d["loading"] and not d["error"]:
        kids.extend(tag_rows(item, info))
        for line in fact_lines(item, info)[:lay()["facts"]]:
            kids.append(ui.text(line))
        kids.extend(provider_buttons(item, info))
        kids.extend(streamer_buttons(item, info))
        c = cast_row(info)
        if c:
            kids.append(c)
        r = related_row(item, info)
        if r:
            kids.append(r)
    kids.append(attribution())
    return ui.column(kids)


def pager(cur):
    total = cur["total"] or 0
    if total <= 1 and cur["page"] <= 1:
        return None
    page = cur["page"]
    kids = []
    if page > 10:
        kids.append(ui.button("-10", lambda: go_page(page - 10)))
    if page > 1:
        kids.append(ui.button("Prev", lambda: go_page(page - 1)))
    kids.append(ui.text("Page %d%s" % (page, " of %d" % total if total else "")))
    if not total or page < total:
        kids.append(ui.button("Next", lambda: go_page(page + 1)))
    if total and page + 10 <= total:
        kids.append(ui.button("+10", lambda: go_page(page + 10)))
    return ui.row(kids)


def list_view():
    cur = S["list"]
    e = S["pages"].get(page_key(cur["src"], cur["page"]))
    if e and e.get("total"):
        cur["total"] = e["total"]
    kids = [ui.row(ui.button("Back", back), ui.heading(cur["title"]))]
    pg = None if cur["src"].get("paged") is False else pager(cur)
    if pg:
        kids.append(pg)
    if not e or e.get("loading"):
        kids.append(ui.spinner("Loading page %d\u2026" % cur["page"], True))
    elif e.get("error"):
        kids.append(ui.text(e["error"]))
        kids.append(ui.button("Try again", lambda: retry_page(cur["src"], cur["page"])))
    elif not e["items"]:
        kids.append(ui.text("Nothing to show here."))
    else:
        fk = "list:%s:%d" % (cur["title"], cur["page"])
        kids.append(ui.grid([poster(it, fk if i == 0 else "") for i, it in enumerate(e["items"])], min_col=lay()["col"]))
        if pg:
            kids.append(pager(cur))
    return ui.column(kids)


def settings_view():
    kids = [ui.heading("TMDb access")]
    if S["key"]:
        kids.append(ui.text("Using your own TMDb key. Remove it to go back to the built-in access."))
    else:
        kids.append(ui.text("Built in: this plugin's own TMDb access is used, so there is nothing to set up. Optional: "
                            "paste your own free v3 API key (themoviedb.org > Settings > API) to use that instead. "
                            "It is stored only inside this plugin on this device."))
    kids.append(ui.text_input("API Key (v3)", S["key_draft"], set_key_draft, placeholder="32-character key",
                              secret=True, on_submit=save_key, key="snake-key"))
    kids.append(ui.row(ui.button("Use my key", save_key, primary=True),
                       ui.button("Remove key", remove_key) if S["key"] else None))
    kids.append(ui.heading("Trailers"))
    kids.append(ui.toggle("Play trailers by themselves", S["autoplay"], lambda v: set_flag("autoplay", v)))
    kids.append(ui.toggle("Trailer sound", S["sound"], lambda v: set_flag("sound", v)))
    kids.append(ui.text("Trailers come from YouTube. If your device blocks sound from starting by itself, turn Trailer sound off."))
    kids.append(ui.heading("Playing"))
    kids.append(ui.toggle("Let me pick the stream myself (otherwise the best one is chosen automatically)", S["pick"],
                          lambda v: set_flag("pick", v)))
    kids.append(ui.toggle("Prefer smaller files (starts sooner and scrubs smoother on slower connections)", S["compact"],
                          lambda v: set_flag("compact", v)))
    if rs.read_device(ui.ctx().get("device")):
        kids.append(ui.toggle("Match releases to this device (4K / HDR10 only where it can play them smoothly)", S["fit"],
                              lambda v: set_flag("fit", v)))
    kids.append(ui.text("Streams are found by this plugin's built-in search (%d sites) and played through PEK." % len(ss.sites())))
    kids.append(ui.heading("Region"))
    kids.append(ui.text("Streaming services and \"now playing\" follow your device region (" + device_region() + "). Using: " + region() + "."))
    kids.append(ui.text_input("Country code", S["region_draft"], set_region_draft, placeholder="US",
                              on_submit=save_region, key="snake-region"))
    kids.append(ui.row(ui.button("Set region", save_region), ui.button("Use device region", auto_region)))
    if S["key_msg"]:
        kids.append(ui.text(S["key_msg"]))
    kids.append(ui.heading("Your library"))
    lib = S["lib"]
    if lib["loaded"]:
        kids.append(ui.text("%d movies and %d shows are marked \"In library\". The list refreshes when PEK starts and when you press Refresh."
                            % (lib["n_movies"], lib["n_shows"])))
    else:
        kids.append(ui.text("Library list not available yet. Add a media folder and let it scan, then press Refresh."))
    kids.append(attribution())
    return ui.column(kids)


def browse_view():
    if S["auth_error"]:
        return ui.column(ui.card(
            "TMDb rejected your API key" if S["key"] else "The built-in TMDb access was refused",
            "Tap to open Settings and check it." if S["key"] else "Tap to open Settings and add your own key instead.",
            lambda: select_tab("settings")))
    kids = [hero(), categories(), chips()]
    for sec in sections_for(S["tab"]):
        kids.append(section_row(sec))
    return ui.column(kids)


# ---------------------------------------------------------------- entry points
def start():
    load_settings()
    read_library()
    refresh_library()
    S["region_draft"] = region()
    S["tab"] = "home"
    S["ready"] = True
    ensure_loaded()


def render():
    sync_favs()
    ui.set_back(back if (S["detail"] or S["list"]) else None)
    if not S["ready"]:
        return ui.column(ui.spinner("Loading\u2026", True))
    if S["detail"]:
        return detail_view()
    kids = []
    if S["tab"] != "settings":
        # One search pill (its arrow submits), then the tabs and Refresh on one line.
        kids.append(search_box())
    in_search = bool(S["list"] and S["list"]["search"])
    if not S["list"]:
        kids.append(ui.row(
            ui.tabs([("home", "Home"), ("movie", "Movies"), ("tv", "TV Shows"), ("settings", "Settings")],
                    S["tab"], select_tab),
            ui.button("Refresh", refresh) if S["tab"] != "settings" else None))
    elif S["tab"] != "settings":
        kids.append(ui.row(ui.button("Clear search", clear_search) if in_search else None,
                           ui.button("Refresh", refresh)))
    if S["tab"] == "settings":
        kids.append(settings_view())
    elif S["auth_error"]:
        kids.append(browse_view())
    elif S["list"]:
        kids.append(list_view())
    else:
        kids.append(browse_view())
    if S["tab"] != "settings":
        kids.append(attribution())
    return ui.column(kids)
