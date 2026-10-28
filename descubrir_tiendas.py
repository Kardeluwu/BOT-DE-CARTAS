#!/usr/bin/env python3
"""Busca el sitio web real de cada tienda de tiendas.txt usando sus perfiles en Card Pulse
y las agrega a config.json. Se corre una vez (o cuando agregues tiendas) desde GitHub Actions."""
import json, os, re, time, unicodedata, urllib.parse, urllib.request
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
CP = "https://cardpulsechile.com"
UA = "Mozilla/5.0 (MiCardPulse; descubrir tiendas)"
NOT_STORE = re.compile(r"cardpulse|google|gstatic|instagram|facebook|fb\.|tiktok|youtube|youtu\.be|twitter|x\.com|"
                       r"discord|whatsapp|wa\.me|cloudflare|shopify\.com|jumpseller|wp\.com|wordpress|cdn|"
                       r"jsdelivr|unpkg|schema\.org|w3\.org|hypezone|tcgmatch|mercadolibre|linktr", re.I)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def slug(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def domains(html):
    c = Counter()
    for href in re.findall(r'href="(https?://[^"]+)"', html):
        host = urllib.parse.urlparse(href).netloc.lower()
        if host and not NOT_STORE.search(host):
            c[host] += 1
    return c


def best_domain(html, strict):
    c = domains(html)
    if not c:
        return None
    host, n = c.most_common(1)[0]
    # en una pagina filtrada por tienda casi todos los links son de esa tienda
    if strict and n < 0.8 * sum(c.values()):
        return None
    return host


def main():
    names = [l.strip() for l in open(os.path.join(ROOT, "tiendas.txt"), encoding="utf-8")
             if l.strip() and not l.startswith("#")]
    # links a perfiles desde la pagina de tiendas
    profiles = {}
    try:
        idx = get(f"{CP}/tiendas")
        for href, text in re.findall(r'href="((?:https://cardpulsechile\.com)?/tienda/[^"?#]+)"[^>]*>(.*?)</a>', idx, re.S):
            t = re.sub(r"<[^>]+>", " ", text)
            for n in names:
                if slug(n) and slug(n) in slug(t):
                    profiles.setdefault(n, urllib.parse.urljoin(CP, href))
    except Exception as e:
        print("No pude leer /tiendas:", e)

    cfg_path = os.path.join(ROOT, "config.json")
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    have = {urllib.parse.urlparse(s["url"]).netloc.lower().removeprefix("www.") for s in cfg["stores"]}
    found, missing = 0, []
    for n in names:
        host = None
        tries = [(profiles.get(n), False), (f"{CP}/tienda/{slug(n)}", False),
                 (f"{CP}/productos?tienda={urllib.parse.quote(n)}", True),
                 (f"{CP}/productos?store={urllib.parse.quote(n)}", True)]
        for url, strict in tries:
            if not url:
                continue
            try:
                host = best_domain(get(url), strict)
            except Exception:
                host = None
            time.sleep(0.8)
            if host:
                break
        if not host:
            missing.append(n)
            print("✗", n)
            continue
        bare = host.removeprefix("www.")
        if bare in have:
            continue
        have.add(bare)
        cfg["stores"].append({"name": n, "url": f"https://{host}"})
        found += 1
        print("✓", n, "→", host)

    json.dump(cfg, open(cfg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    with open(os.path.join(ROOT, "data", "tiendas_no_encontradas.txt"), "w", encoding="utf-8") as f:
        f.write("# Agrega estas a mano en config.json (nombre + url)\n" + "\n".join(missing))
    print(f"\n{found} tiendas nuevas agregadas · {len(missing)} sin encontrar (ver data/tiendas_no_encontradas.txt)")


if __name__ == "__main__":
    main()
