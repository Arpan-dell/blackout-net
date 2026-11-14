"""City mesh plan: put a BLACKOUT NET node at every site (for example the tall flag masts across Delhi) and see
whether every site can reach an HQ, in how many radio hops, before anything is built.

  python tools/city_plan.py                                   1 km grid over Delhi's bounding box (a sketch)
  python tools/city_plan.py --sites flags.csv                 real sites: CSV with name,lat,lon[,hq] (hq = 1)
  python tools/city_plan.py --range 1500 --ttl 3 --hq-every 7 change the assumptions
  python tools/city_plan.py --tiles http://localhost:8765/tiles/streets/{z}/{x}/{y}   map from the GCS cache
  python tools/city_plan.py --selftest

Writes city_plan.html (one self-contained file, open it in any browser) and prints the numbers.
Every number depends on --range, the distance one link really covers between two masts: measure it first.
"""
import argparse, collections, csv, json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DELHI_BOX = (28.40, 76.84, 28.88, 77.35)  # south, west, north, east: NCT of Delhi fits inside, with its neighbours
M_PER_DEG = 111195.0


def grid_sites(box, spacing_m, hq_every):
    """A site every spacing_m metres over the box; every hq_every-th site in both directions is an HQ."""
    s, w, n, e = box
    dlat, dlon = spacing_m / M_PER_DEG, spacing_m / (M_PER_DEG * math.cos(math.radians((s + n) / 2)))
    rows, cols = int((n - s) / dlat + 1e-9) + 1, int((e - w) / dlon + 1e-9) + 1
    off = hq_every // 2  # HQs sit in the middle of their block, not on its edge
    return [{"name": f"G{r}-{c}", "lat": s + r * dlat, "lon": w + c * dlon,
             "hq": r % hq_every == off and c % hq_every == off} for r in range(rows) for c in range(cols)]


def read_sites(path):
    with open(path, newline="", encoding="utf-8") as f:
        sites = [{"name": r.get("name") or f"S{i}", "lat": float(r["lat"]), "lon": float(r["lon"]),
                  "hq": str(r.get("hq", "")).strip() in ("1", "yes", "true")} for i, r in enumerate(csv.DictReader(f))]
    if not any(s["hq"] for s in sites):
        raise SystemExit("Mark at least one site as an HQ: a column 'hq' with 1 on that row.")
    return sites


def links(sites, range_m):
    """Pairs of sites within range_m of each other. Buckets of range_m, so it stays fast for thousands of sites."""
    lat0 = math.radians(sum(s["lat"] for s in sites) / len(sites))
    xy = [(s["lon"] * M_PER_DEG * math.cos(lat0), s["lat"] * M_PER_DEG) for s in sites]  # flat: fine across a city
    cells = collections.defaultdict(list)
    for i, (x, y) in enumerate(xy):
        cells[int(x // range_m), int(y // range_m)].append(i)
    out = []
    for (cx, cy), members in cells.items():
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i in members:
                    for j in cells.get((cx + dx, cy + dy), ()):
                        if i < j and math.dist(xy[i], xy[j]) <= range_m:
                            out.append((i, j))
    return out


def hops_to_hq(sites, pairs):
    """Fewest radio hops from each site to its nearest HQ (0 for an HQ), None if no path at all."""
    nb = collections.defaultdict(list)
    for i, j in pairs:
        nb[i].append(j)
        nb[j].append(i)
    hops = [0 if s["hq"] else None for s in sites]
    queue = collections.deque(i for i, s in enumerate(sites) if s["hq"])
    while queue:
        i = queue.popleft()
        for j in nb[i]:
            if hops[j] is None:
                hops[j] = hops[i] + 1
                queue.append(j)
    return hops


def summary(sites, hops, pairs, ttl):
    hist = collections.Counter(h for h in hops if h is not None)
    return {"sites": len(sites), "hqs": sum(s["hq"] for s in sites), "links": len(pairs),
            "unreachable": sum(h is None for h in hops), "beyond_ttl": sum(h is not None and h > ttl for h in hops),
            "max_hops": max(hist) if hist else None, "hist": dict(sorted(hist.items()))}


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>BLACKOUT NET city plan</title><style>%(css)s
:root { color-scheme: light dark; --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink2: #52514e; --border: rgba(11,11,11,.12); }
@media (prefers-color-scheme: dark) { :root { --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink2: #c3c2b7; --border: rgba(255,255,255,.12); } }
body { margin: 0; background: var(--page); color: var(--ink); font: 15px/1.45 system-ui, sans-serif; }
#map { position: absolute; inset: 0; } .panel { position: absolute; z-index: 1000; top: 12px; right: 12px; max-width: 360px;
background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; box-shadow: 0 2px 10px rgba(0,0,0,.25); }
h1 { font-size: 18px; margin: 0 0 6px; } .big { font-size: 26px; font-weight: 700; } .row { display: flex; gap: 16px; flex-wrap: wrap; }
.k { color: var(--ink2); font-size: 12px; } .sw { display: inline-block; width: 12px; height: 12px; border-radius: 50%%; margin-right: 6px; vertical-align: -1px; }
.note { color: var(--ink2); font-size: 12px; margin-top: 8px; } ul { list-style: none; padding: 0; margin: 8px 0 0; } li { font-size: 13px; }
@media (max-width: 600px) { .panel { left: 12px; right: 12px; max-width: none; } }
</style></head><body><div id="map"></div><div class="panel"><h1>BLACKOUT NET across the city</h1>
<div class="row"><div><div class="big">%(sites)s</div><div class="k">nodes</div></div><div><div class="big">%(hqs)s</div><div class="k">HQs</div></div>
<div><div class="big">%(reach)s</div><div class="k">reach an HQ in %(ttl)s hops or fewer</div></div></div>
<ul id="legend"></ul><div class="note">%(note)s</div></div>
<script>%(leaflet)s</script><script>
const D = %(data)s;
const map = L.map("map", { preferCanvas: true });
L.tileLayer(D.tiles, { maxZoom: 19, attribution: D.attribution }).addTo(map);
const COL = h => h === null ? "#898781" : h === 0 ? "#0b0b0b" : h > D.ttl ? "#d03b3b" : ["#9ec5f0", "#5a9be3", "#2a78d6", "#1b4f8f"][Math.min(h, 4) - 1];
for (const [i, j] of D.links) L.polyline([[D.lat[i], D.lon[i]], [D.lat[j], D.lon[j]]], { color: "#5a9be3", weight: 1, opacity: .35, interactive: false }).addTo(map);
D.lat.forEach((la, i) => {
  const h = D.hops[i], hq = h === 0;
  L.circleMarker([la, D.lon[i]], { radius: hq ? 7 : 4, color: hq ? "#fff" : COL(h), weight: hq ? 2 : 1, fillColor: COL(h), fillOpacity: 1 })
   .bindTooltip(D.name[i] + (hq ? " · HQ" : h === null ? " · cannot reach any HQ" : " · " + h + " hop" + (h === 1 ? "" : "s") + " to the nearest HQ")).addTo(map);
});
map.fitBounds(L.latLngBounds(D.lat.map((la, i) => [la, D.lon[i]])).pad(0.05));
const items = [[0, "HQ (control room)"], [1, "1 hop"], [2, "2 hops"], [3, "3 hops"], [4, "4 or more hops (within the hop limit)"], [D.ttl + 1, "beyond the hop limit of " + D.ttl], [null, "no path to any HQ"]]
  .filter(([h], k) => k < 4 || (k === 4 && D.ttl >= 4) || k > 4);
document.getElementById("legend").innerHTML = items.map(([h, t]) => `<li><span class="sw" style="background:${COL(h)}"></span>${t}</li>`).join("");
</script></body></html>"""


def write_page(path, sites, hops, pairs, s, a, sketch):
    with open(os.path.join(HERE, "vendor", "leaflet.js"), encoding="utf-8") as f:
        leaflet = f.read()
    with open(os.path.join(HERE, "vendor", "leaflet.css"), encoding="utf-8") as f:
        css = f.read()
    note = (f"Assumes one link covers {a.range:g} m between masts; measure that before trusting this map. "
            f"Messages go up to {a.ttl} hops (the firmware's DATA_TTL). ")
    if sketch:
        note += (f"Sites are a regular {a.spacing:g} m grid over Delhi's bounding box, not the real flag positions; "
                 "give those with --sites. ")
    note += ("Today the nodes relay by flooding, which suits a few dozen nodes. A whole city needs each node to "
             "forward towards its nearest HQ only; that routing is not built yet.")
    data = {"lat": [round(x["lat"], 6) for x in sites], "lon": [round(x["lon"], 6) for x in sites],
            "name": [x["name"] for x in sites], "hops": hops, "links": pairs, "ttl": a.ttl, "tiles": a.tiles,
            "attribution": "© OpenStreetMap contributors" if "openstreetmap" in a.tiles else "Map tiles via the GCS"}
    reach = s["sites"] - s["unreachable"] - s["beyond_ttl"]
    html = PAGE % {"css": css, "leaflet": leaflet, "data": json.dumps(data, separators=(",", ":")),
                   "sites": f"{s['sites']:,}", "hqs": s["hqs"], "ttl": a.ttl,
                   "reach": f"{100 * reach / s['sites']:.0f} %", "note": note}
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def selftest():
    n = 28.60 + 6000 / M_PER_DEG
    e = 77.20 + 6000 / (M_PER_DEG * math.cos(math.radians((28.60 + n) / 2)))
    sites = grid_sites((28.60, 77.20, n, e), 1000, 7)  # 7 x 7 sites, the HQ in the middle
    assert len(sites) == 49 and [i for i, s in enumerate(sites) if s["hq"]] == [24]
    pairs = links(sites, 1500)
    brute = [(i, j) for i in range(len(sites)) for j in range(i + 1, len(sites))
             if math.dist(*[(p["lon"] * M_PER_DEG * math.cos(math.radians(28.63)), p["lat"] * M_PER_DEG)
                            for p in (sites[i], sites[j])]) <= 1500]
    assert sorted(pairs) == sorted(brute), (len(pairs), len(brute))  # the buckets miss nothing
    hops = hops_to_hq(sites, pairs)
    assert max(h for h in hops if h is not None) == 3 and None not in hops  # HQ in the middle of a 7 x 7 block: 3 hops
    lone = sites + [{"name": "far", "lat": 10.0, "lon": 10.0, "hq": False}]
    h2 = hops_to_hq(lone, links(lone, 1500))
    s = summary(lone, h2, [], 2)
    assert h2[-1] is None and s["unreachable"] == 1 and s["beyond_ttl"] > 0
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sites", help="CSV with name,lat,lon[,hq]; without it, a grid over Delhi")
    ap.add_argument("--spacing", type=float, default=1000, help="grid spacing in metres (without --sites)")
    ap.add_argument("--hq-every", type=int, default=7, help="grid: one HQ every this many sites each way")
    ap.add_argument("--range", type=float, default=1500, help="metres one link covers between two masts (measure it)")
    ap.add_argument("--ttl", type=int, default=3, help="most hops a message may take (DATA_TTL in config.h)")
    ap.add_argument("--tiles", default="https://tile.openstreetmap.org/{z}/{x}/{y}.png", help="map tile URL template")
    ap.add_argument("--out", default="city_plan.html")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    sites = read_sites(a.sites) if a.sites else grid_sites(DELHI_BOX, a.spacing, a.hq_every)
    pairs = links(sites, a.range)
    hops = hops_to_hq(sites, pairs)
    s = summary(sites, hops, pairs, a.ttl)
    print(f"{s['sites']} sites, {s['hqs']} HQs, {s['links']} links of {a.range:g} m or less")
    print("hops to the nearest HQ: " + ", ".join(f"{h}: {n}" for h, n in s["hist"].items()))
    print(f"beyond the {a.ttl}-hop limit: {s['beyond_ttl']}   no path to any HQ: {s['unreachable']}")
    write_page(a.out, sites, hops, pairs, s, a, not a.sites)
    print(f"Map: {os.path.abspath(a.out)}")


if __name__ == "__main__":
    main()
