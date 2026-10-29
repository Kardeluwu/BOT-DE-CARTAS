#!/usr/bin/env python3
"""Mi Card Pulse: revisa tiendas TCG, agrupa los sellados bajo una ficha comun
(juego + set + tipo + idioma) y avisa por Discord. Solo usa la libreria estandar."""
import json, os, re, sys, time, unicodedata, urllib.request, urllib.error
from datetime import datetime, timezone
from html import unescape
from xml.etree import ElementTree as ET

ROOT = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
SETS = json.load(open(os.path.join(ROOT, "sets.json"), encoding="utf-8"))
STATE_PATH = os.path.join(ROOT, "data", "state.json")
SITE_DATA = os.path.join(ROOT, "docs", "data.json")
UNKNOWN_PATH = os.path.join(ROOT, "data", "sin_set.txt")
UA = "MiCardPulse/1.0 (monitor personal de precios)"
NOW = time.time()


# ---------------------------------------------------------------- red
def get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json,text/html;q=0.9,*/*;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def get_json(url):
    return json.loads(get(url))


# ---------------------------------------------------------------- lectores por plataforma
def out_of_time(st):
    """Cada tienda tiene un tope de tiempo por corrida; si se pasa, sigue la proxima vez."""
    return time.time() > st.get("_deadline", float("inf"))


def resume_page(state, base):
    return state["resume"].get(base, 1)


def finish(state, base, st, start, page, done):
    """Guarda en que pagina seguir. Solo es lectura completa si partio en 1 y llego al final."""
    state["resume"][base] = 1 if done else page + 1
    st["_partial"] = not (done and start == 1)
    st["_cycle_done"] = done  # termino una vuelta completa (aunque sea en varias pasadas)


def read_shopify(base, st, state):
    items = []
    start = resume_page(state, base)
    page, done = start, False
    for page in range(start, 200):
        data = get_json(f"{base}/products.json?limit=250&page={page}")
        prods = data.get("products", [])
        for p in prods:
            vs = p.get("variants") or []
            prices = [float(v["price"]) for v in vs if v.get("price")]
            if not prices:
                continue
            imgs = p.get("images") or []
            items.append({
                "name": p.get("title", ""),
                "url": f"{base}/products/{p.get('handle')}",
                "price": min(prices),
                "stock": any(v.get("available") for v in vs),
                "img": imgs[0].get("src") if imgs else None,
            })
        if len(prods) < 250:
            done = True
            break
        if out_of_time(st):
            break
        time.sleep(0.5)
    finish(state, base, st, start, page, done)
    return items


def read_woo(base, st, state):
    items = []
    start = resume_page(state, base)
    page, done = start, False
    for page in range(start, 400):
        try:
            prods = get_json(f"{base}/wp-json/wc/store/v1/products?per_page=100&page={page}")
        except urllib.error.HTTPError as e:
            if e.code == 400:  # pagina fuera de rango
                done = True
                break
            raise
        if not prods:
            done = True
            break
        for p in prods:
            pr = p.get("prices") or {}
            try:
                price = int(pr.get("price")) / 10 ** int(pr.get("currency_minor_unit", 0))
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            imgs = p.get("images") or []
            items.append({
                "name": unescape(p.get("name", "")),
                "url": p.get("permalink"),
                "price": price,
                "stock": bool(p.get("is_in_stock")),
                "img": imgs[0].get("src") if imgs else None,
            })
        if len(prods) < 100:
            done = True
            break
        if out_of_time(st):
            break
        time.sleep(0.5)
    finish(state, base, st, start, page, done)
    return items


SLUG_HINT = re.compile(r"etb|elite|booster|bundle|blister|box|display|tin|lata|collection|coleccion|"
                       r"deck|sobre|pack|caja|premium|upc|preventa|starter|mazo", re.I)
SKIP_SITEMAP = re.compile(r"image|blog|post|categor|page|tag|author|brand|marca", re.I)
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def sitemap_entries(base):
    out, seen = {}, set()

    def walk(url, depth):
        if url in seen or len(seen) > 25:
            return
        seen.add(url)
        root = ET.fromstring(get(url).encode("utf-8"))
        if root.tag.endswith("sitemapindex"):
            for sm in root.findall(NS + "sitemap"):
                loc = (sm.findtext(NS + "loc") or "").strip()
                if loc and depth < 2 and not SKIP_SITEMAP.search(loc.rsplit("/", 1)[-1]):
                    walk(loc, depth + 1)
        else:
            for u in root.findall(NS + "url"):
                loc = (u.findtext(NS + "loc") or "").strip()
                if loc and SLUG_HINT.search(loc.rstrip("/").rsplit("/", 1)[-1]):
                    out[loc] = (u.findtext(NS + "lastmod") or "").strip()

    walk(f"{base}/sitemap.xml", 0)
    return out


def parse_jsonld_product(html):
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        stack = [data]
        while stack:
            d = stack.pop()
            if isinstance(d, list):
                stack.extend(d)
                continue
            if not isinstance(d, dict):
                continue
            if "@graph" in d:
                stack.extend(d["@graph"] if isinstance(d["@graph"], list) else [d["@graph"]])
            t = d.get("@type")
            if t == "Product" or (isinstance(t, list) and "Product" in t):
                offers = d.get("offers") or {}
                offers = offers if isinstance(offers, list) else [offers]
                prices, stock = [], False
                for o in offers:
                    p = o.get("price", o.get("lowPrice"))
                    try:
                        prices.append(float(str(p).replace(",", ".")))
                    except (TypeError, ValueError):
                        pass
                    av = str(o.get("availability", ""))
                    stock = stock or "InStock" in av or "PreOrder" in av
                if not prices:
                    return None
                img = d.get("image")
                if isinstance(img, list):
                    img = img[0] if img else None
                if isinstance(img, dict):
                    img = img.get("url")
                return {"name": unescape(str(d.get("name", ""))), "price": min(prices),
                        "stock": stock, "img": img}
    return None


def read_sitemap(base, st, state):
    """Para tiendas sin API publica (ej. Jumpseller): lee el sitemap y solo vuelve a abrir
    las paginas nuevas, cambiadas o que no revisa hace rato. Asi gasta pocas visitas."""
    cache = state.setdefault("pages", {}).setdefault(base, {})
    entries = sitemap_entries(base)
    refresh = CFG.get("refresh_hours", 6) * 3600
    todo = []
    for url, lastmod in entries.items():
        c = cache.get(url)
        if c is None:
            todo.append((0, url))
        elif c.get("lastmod") != lastmod:
            todo.append((1, url))
        elif c.get("item") and NOW - c.get("checked", 0) > refresh:
            todo.append((2, url))
    todo.sort()
    pending = sum(1 for t in todo if t[0] < 2)  # nuevas o cambiadas
    done_n = 0
    for prio, url in todo[:CFG.get("max_pages_per_run", 120)]:
        if out_of_time(st):
            break
        done_n += prio < 2
        try:
            item = parse_jsonld_product(get(url))
        except Exception:
            continue
        cache[url] = {"lastmod": entries[url], "checked": NOW, "item": item}
        time.sleep(0.4)
    st["_partial"] = done_n < pending
    for url in list(cache):
        if url not in entries:
            del cache[url]
    return [dict(c["item"], url=u) for u, c in cache.items() if c.get("item")]


def detect_platform(base):
    try:
        if "products" in get_json(f"{base}/products.json?limit=1"):
            return "shopify"
    except Exception:
        pass
    try:
        if isinstance(get_json(f"{base}/wp-json/wc/store/v1/products?per_page=1"), list):
            return "woo"
    except Exception:
        pass
    return "sitemap"


READERS = {"shopify": read_shopify, "woo": read_woo, "sitemap": read_sitemap}


def fetch_store(st, state):
    base = st["url"].rstrip("/")
    plat = st.get("platform", "auto")
    if plat == "auto":
        known = state.setdefault("platforms", {})
        plat = known.get(base) or detect_platform(base)
        known[base] = plat
    return READERS[plat](base, st, state)


# ---------------------------------------------------------------- clasificacion
def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9&]+", " ", s)
    return f" {s.strip()} "


ALIASES = [(re.compile(a), b) for a, b in CFG.get("aliases", [])]
EXCLUDE = re.compile(r" (acrilico|acrylic|protector(es)?|sleeves?|fundas?|playmat|tapete|deck ?box|"
                     r"portamazos?|carpeta|psa|cgc|bgs|graded|gradead[ao]|nm|near mint|lp|mp|"
                     r"carta suelta|singles?|proxy|holo|reverse|foil|alt art|manga|anime|peluche|figura) ")
PREORDER = re.compile(r"pre ?ve?w?nta|pre ?order")
TYPES = [
    ("UPC", r" ultra premium| upc "),
    ("Premium Collection", r" premium collection| coleccion premium"),
    ("ETB", r" elite trainer| etb | caja de entrenador"),
    ("Build & Battle", r" build (& |and |y )?battle"),
    ("Battle Deck", r" battle deck| mazo de combate"),
    ("Starter Deck", r" starter deck| mazo inicial| deck inicial| st \d"),
    ("Booster Bundle", r" bundle"),
    ("Booster Box", r" booster box| display | caja de sobres| booster display| box de sobres"),
    ("Blister 3-pack", r" 3 ?pack| tri ?pack"),
    ("Blister", r" blister| checklane"),
    ("Tin", r" tin | lata | latas | mini tin"),
    ("Booster Pack", r" booster pack| sobres? | sleeved booster"),
    ("Coleccion", r" collection| coleccion| box | caja "),
]
TYPES = [(n, re.compile(p)) for n, p in TYPES]
VARIANT_TYPES = {"Coleccion", "Premium Collection", "Tin", "Battle Deck"}
LANGS = [("ES", re.compile(r" (espanol|esp|castellano|spanish|es) ")),
         ("EN", re.compile(r" (ingles|ing|english|eng|en) ")),
         ("JP", re.compile(r" (japones|jp|jap|japanese|japon|jpn) "))]
OP_CODE = re.compile(r" (op|eb|prb|st) ?(\d{1,2}) ")
STOP = set("""pokemon pkm tcg one piece card game juego de cartas the of del de la el los las y and con x
booster box bundle elite trainer etb blister pack packs tin lata latas collection coleccion premium ultra upc
display caja sobre sobres deck starter battle build mazo preventa prevewnta pre venta order preorder
diseno al azar random unidad unidades nuevo original sellado sellada entrega entregas espanol esp ingles ing
english eng japones jp jap spanish castellano es en mini tri checklane sleeved""".split())

SET_INDEX = []  # (alias_normalizado, juego, nombre_set)
for game, sets in SETS.items():
    if game.startswith("_"):
        continue
    for name, aliases in sets.items():
        for a in [name] + aliases:
            SET_INDEX.append((norm(a), game, name))
SET_INDEX.sort(key=lambda t: -len(t[0]))
SERIES = set(SETS.get("_series", []))


def classify(raw_name):
    n = norm(raw_name)
    for rx, rep in ALIASES:
        n = rx.sub(rep, n)
    if EXCLUDE.search(n):
        return None
    ptype = next((name for name, rx in TYPES if rx.search(n)), None)
    if not ptype:
        return None

    # set y juego
    found = [(a, g, s) for a, g, s in SET_INDEX if a in n]
    specific = [f for f in found if f[2] not in SERIES]
    game, set_name, rest = None, None, n
    m = OP_CODE.search(n)
    if m and (m.group(1) != "st" or " one piece " in n):
        game, set_name = "one-piece", f"{m.group(1).upper()}-{int(m.group(2)):02d}"
        rest = rest.replace(m.group(0), " ")
    elif specific or found:
        a, game, set_name = (specific or found)[0]
        rest = rest.replace(a, " ")
    if not game:
        if " one piece " in n:
            game = "one-piece"
        elif " pokemon " in n or " pkm " in n:
            game = "pokemon"
    if game not in CFG.get("games", ["pokemon", "one-piece"]):
        return None

    lang = next((code for code, rx in LANGS if rx.search(n)), "?")
    # palabras que sobran, sin lo que va entre parentesis/corchetes
    clean = norm(re.sub(r"[\(\[].*?[\)\]]", " ", raw_name))
    for rx, rep in ALIASES:
        clean = rx.sub(rep, clean)
    for a, _, _ in found:
        clean = clean.replace(a, " ")
    if m:
        clean = OP_CODE.sub(" ", clean)
    words = [w for w in clean.split() if w not in STOP and not re.fullmatch(r"\d{1,2}", w)]
    variant = ""
    if ptype in VARIANT_TYPES or not set_name:
        variant = " ".join(words[:4])
    if not set_name:
        set_name = "Sin set"
    key = "|".join([game, set_name.lower(), ptype.lower(), lang, variant])
    label = f"{set_name} · {ptype}" + (f" · {variant.title()}" if variant else "")
    return {"key": key, "label": label, "game": game, "set": set_name, "type": ptype,
            "lang": lang, "variant": variant, "preorder": bool(PREORDER.search(n))}


# ---------------------------------------------------------------- avisos
def clp(x):
    return "$" + f"{x:,.0f}".replace(",", ".")


EVENT_STYLE = {"nuevo": ("🆕 Producto nuevo", 0x5865F2), "tienda": ("🏪 Otra tienda lo tiene", 0x3BA55C),
               "repuesto": ("🔄 Volvió el stock", 0xFAA61A), "baja": ("📉 Bajó de precio", 0xED4245)}
LANG_NAME = {"ES": "Español", "EN": "Inglés", "JP": "Japonés", "?": "Idioma ?"}


WATCH = [norm(w).strip() for w in CFG.get("watch", []) if w.strip()]


def watched(l):
    """True si el nombre o la ficha contiene alguna palabra de la lista 'watch'."""
    text = norm(l["name"] + " " + l["label"])
    compact = text.replace(" ", "")
    return any(f" {w} " in text or (re.search(r"\d", w) and w.replace(" ", "") in compact)
               for w in WATCH)


def diff(old, new, groups):
    want = set(CFG.get("alert_types", EVENT_STYLE.keys()))
    only_watch = CFG.get("only_watch", False)
    min_drop = CFG.get("min_drop_pct", 5) / 100
    old_groups = {l["key"] for l in old.values()}
    events = []
    for url, l in new.items():
        o = old.get(url)
        w = watched(l)
        if only_watch and not w:
            continue
        if o is None:
            if not l["stock"] and not w:  # con palabra clave avisa aunque no tenga stock
                continue
            kind = "tienda" if l["key"] in old_groups else "nuevo"
        elif l["stock"] and not o["stock"]:
            kind = "repuesto"
        elif l["stock"] and l["price"] <= o["price"] * (1 - min_drop):
            kind = "baja"
        else:
            continue
        if kind in want or w:
            events.append((kind, dict(l, watch=w), o))
    events.sort(key=lambda e: not e[1]["watch"])  # primero lo que buscas
    return events


def send_discord(events, groups):
    hook = os.environ.get("DISCORD_WEBHOOK", "").strip()
    limit = CFG.get("max_alerts_per_run", 40)
    extra = max(0, len(events) - limit)
    embeds = []
    for kind, l, o in events[:limit]:
        title, color = EVENT_STYLE[kind]
        if l.get("watch"):
            title, color = "⭐ " + title, 0xFEE75C
        g = groups[l["key"]]
        best = g["offers"][0] if g["offers"] else None
        desc = f"**{l['store']}** · {clp(l['price'])}" + ("" if l["stock"] else " · sin stock aún")
        if kind == "baja":
            desc += f" (antes {clp(o['price'])})"
        if l.get("preorder"):
            desc += " · preventa"
        desc += f"\n[{l['name'][:120]}]({l['url']})"
        if best and best["url"] != l["url"]:
            desc += f"\nMás barato ahora: **{best['store']}** {clp(best['price'])} · {g['stores_in_stock']} tiendas con stock"
        e = {"title": f"{title}: {l['label']}"[:250], "description": desc, "color": color,
             "footer": {"text": LANG_NAME.get(l["lang"], l["lang"])}}
        if l.get("img"):
            e["thumbnail"] = {"url": l["img"]}
        embeds.append(e)
    if not hook:
        for e in embeds:
            print("[sin webhook]", e["title"], "|", e["description"].replace("\n", " | "))
        return
    chunks = [embeds[i:i + 10] for i in range(0, len(embeds), 10)]
    if extra:
        site = CFG.get("site_url", "https://kardeluwu.github.io/BOT-DE-CARTAS/")
        chunks.append([{"description": f"…y {extra} avisos más. [Ver todo en la página]({site})", "color": 0x99AAB5}])
    ping = CFG.get("watch_ping", "@here")
    for i, chunk in enumerate(chunks):
        msg = {"username": CFG.get("bot_name") or "Mi Card Pulse", "embeds": chunk}
        if ping and any(e.get("title", "").startswith("⭐") for e in chunk):
            msg["content"] = f"{ping} apareció algo que estás buscando"
            msg["allowed_mentions"] = {"parse": ["everyone", "users", "roles"]}
        body = json.dumps(msg).encode()
        for _ in range(3):
            req = urllib.request.Request(hook, data=body, headers={"Content-Type": "application/json",
                                                                   "User-Agent": UA})
            try:
                urllib.request.urlopen(req, timeout=20)
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(float(json.loads(e.read() or b"{}").get("retry_after", 2)) + 0.5)
                    continue
                print("Discord error", e.code, e.read()[:200], file=sys.stderr)
                break
        time.sleep(1)


# ---------------------------------------------------------------- principal
def build_groups(listings):
    groups = {}
    for l in listings.values():
        g = groups.setdefault(l["key"], {k: l[k] for k in ("key", "label", "game", "set", "type", "lang", "variant")}
                              | {"offers": [], "preorder": False})
        g["offers"].append({k: l.get(k) for k in ("store", "name", "url", "price", "stock", "img", "preorder", "seen")})
        g["preorder"] = g["preorder"] or l.get("preorder", False)
    for g in groups.values():
        g["offers"].sort(key=lambda o: (not o["stock"], o["price"]))
        stocked = [o for o in g["offers"] if o["stock"]]
        g["stores_in_stock"] = len({o["store"] for o in stocked})
        g["min_price"] = stocked[0]["price"] if stocked else None
        g["img"] = next((o["img"] for o in g["offers"] if o.get("img")), None)
        g["seen"] = max((o.get("seen") or 0 for o in g["offers"]), default=0)
    return groups


def main():
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    state = json.load(open(STATE_PATH, encoding="utf-8")) if os.path.exists(STATE_PATH) else {}
    old = state.get("listings", {})
    new, failed, unknown, report, partial = {}, set(), [], [], set()
    meta = state.setdefault("store_meta", {})
    seeded = state.setdefault("seeded", {})
    unseeded = {st["name"] for st in CFG["stores"] if not seeded.get(st["url"])}
    state.setdefault("resume", {})
    big_n = CFG.get("big_store_products", 3000)
    big_every = CFG.get("big_store_every_min", 60) * 60
    skipped, todo = set(), []
    for st in CFG["stores"]:
        m = meta.get(st["url"], {})
        # tiendas gigantes (casi todo singles) se revisan menos seguido
        mid_pass = state["resume"].get(st["url"].rstrip("/"), 1) != 1  # lectura a medias: sigue ya
        if not mid_pass and m.get("n", 0) > big_n and NOW - m.get("last", 0) < big_every:
            skipped.add(st["name"])
        else:
            todo.append(st)

    budget = CFG.get("store_budget_sec", 240)
    state.setdefault("resume", {})
    state.setdefault("pages", {})
    state.setdefault("platforms", {})

    def job(st):
        t0 = time.time()
        st["_deadline"], st["_partial"], st["_cycle_done"] = t0 + budget, False, False
        try:
            return st, fetch_store(st, state), None, time.time() - t0
        except Exception as e:
            return st, None, e, time.time() - t0

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(16, CFG.get("parallel", 16))) as pool:
        results = list(pool.map(job, todo))

    for st, items, err, secs in results:
        if err is not None:
            failed.add(st["name"])
            report.append(f"✗ {st['name']}: {type(err).__name__} {err}"[:200])
            continue
        if st["_partial"]:
            partial.add(st["name"])
        if not st["_partial"] or st.get("_cycle_done"):
            seeded[st["url"]] = True  # ya se leyo completa al menos una vez
        prev_n = meta.get(st["url"], {}).get("n", 0)
        meta[st["url"]] = {"n": max(len(items), prev_n) if st["_partial"] else len(items), "last": NOW}
        kept = 0
        for it in items:
            if not it.get("url") or not it.get("name"):
                continue
            c = classify(it["name"])
            if not c:
                continue
            if c["set"] == "Sin set":
                unknown.append(f"{st['name']}: {it['name']}")
            prev = old.get(it["url"])
            # fecha en que aparecio: se conserva; 0 = ya estaba antes de existir este dato
            seen = prev.get("seen", 0) if prev else (0 if st["name"] in unseeded or not old else int(NOW))
            new[it["url"]] = {"store": st["name"], "name": it["name"], "url": it["url"],
                              "price": it["price"], "stock": it["stock"], "img": it.get("img"),
                              "seen": seen} | c
            kept += 1
        report.append(f"✓ {st['name']}: {len(items)} productos, {kept} sellados ({secs:.0f}s)"
                      + (" · parcial, sigue la proxima vez" if st["_partial"] else ""))
    if skipped:
        report.append(f"· {len(skipped)} tiendas grandes esperan su turno (cada {big_every // 60} min)")
    # si una tienda fallo o no le tocaba, se mantienen sus datos anteriores para no inventar avisos
    for url, l in old.items():
        if (l["store"] in failed or l["store"] in skipped or l["store"] in partial) and url not in new:
            new[url] = l

    groups = build_groups(new)
    events = [e for e in diff(old, new, groups) if e[1]["store"] not in unseeded] if old else []
    waiting = sorted(unseeded - failed - skipped)
    if waiting and old:
        report.append(f"· {len(waiting)} tiendas en primera lectura (sin avisos hasta completarla)")
    print("\n".join(report))
    print(f"{len(new)} publicaciones en {len(groups)} fichas · {len(events)} avisos"
          + (" (primera corrida: solo se guarda, sin avisos)" if not old else ""))
    if events:
        try:
            send_discord(events, groups)
        except Exception as e:  # un error de Discord nunca debe impedir guardar los datos
            print("Error enviando a Discord:", type(e).__name__, e, file=sys.stderr)

    # historial: precio minimo con stock de cada ficha, uno por dia (ultimos N dias)
    hist = state.setdefault("hist", {})
    from zoneinfo import ZoneInfo
    from datetime import timedelta
    now_cl = datetime.now(ZoneInfo("America/Santiago"))
    today = now_cl.strftime("%Y-%m-%d")
    keep_days = CFG.get("history_days", 90)
    cutoff = (now_cl - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    for k, g in groups.items():
        if g["min_price"] is None:
            continue
        h = hist.setdefault(k, [])
        if h and h[-1][0] == today:
            h[-1][1] = min(h[-1][1], g["min_price"])
        else:
            h.append([today, g["min_price"]])
        del h[:-keep_days]
    for k in list(hist):
        if k not in groups and (not hist[k] or hist[k][-1][0] < cutoff):
            del hist[k]  # fichas que ya no existen en ninguna tienda
    for k, g in groups.items():
        g["hist"] = hist.get(k, [])

    state["listings"] = new
    state["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    json.dump(state, open(STATE_PATH, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    os.makedirs(os.path.dirname(SITE_DATA), exist_ok=True)
    site = sorted(groups.values(), key=lambda g: (g["min_price"] is None, g["label"]))
    json.dump({"updated": state["updated"], "site_name": CFG.get("bot_name") or "Mi Card Pulse",
               "stores": [s["name"] for s in CFG["stores"]],
               "failed": sorted(failed), "groups": site},
              open(SITE_DATA, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    with open(UNKNOWN_PATH, "w", encoding="utf-8") as f:
        f.write("# Productos sin set reconocido. Agrega alias en sets.json para agruparlos mejor.\n")
        f.write("\n".join(sorted(set(unknown))[:500]))


if __name__ == "__main__":
    main()
