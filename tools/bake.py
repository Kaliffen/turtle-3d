#!/usr/bin/env python3
"""Bake a city into data/<city>/*.js so index.html can load it straight from file://.
   (Script tags + base64: file:// pages can't fetch(), and WebGL rejects file:// images.)

   python tools/bake.py <paris|newyork|berlin|aarhus|galten>

   Denmark needs DATAFORSYNINGEN_TOKEN and DATAFORDELER_API_KEY in the environment. Keys are added to
   the request only at the last moment: they never reach cache file names, logs or output files.
   Re-runnable: every download is cached in .cache/<city>/."""
import base64, io, json, math, os, re, struct, sys, time, urllib.parse, urllib.request
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parent.parent
UA = {'User-Agent': 'turtle-3d-prototype/0.1'}
R = 6378137.0
CHUNK_PX = 4096

CITIES = {
    # chunk_m sets the sharpness: 2500 m over 4096 px is 0.61 m/px
    'paris':   dict(lat=48.864, lon=2.322, cols=4, rows=3, chunk_m=2500, far=44000, photo='ign', far_photo='ign', buildings='ign', water='ign', trees='paris'),
    'newyork': dict(lat=40.741, lon=-73.990, cols=3, rows=5, chunk_m=2500, far=30000, photo='naip', far_photo='naip', buildings='nyc', water='nyc', trees='nyc'),
    'berlin':  dict(lat=52.505, lon=13.395, cols=4, rows=3, chunk_m=2500, far=30000, photo='berlin', far_photo='berlin', buildings='berlin', water='berlin', trees='berlin'),
    'aarhus':  dict(lat=56.150, lon=10.205, cols=4, rows=3, chunk_m=2000, far=16000, photo='dk', far_photo='dk', buildings='dk', water='dk', trees='dk', dem_zoom=14),
    'galten':  dict(lat=56.1565, lon=9.9090, cols=4, rows=3, chunk_m=1200, far=10000, photo='dk', far_photo='dk', buildings='dk', water='dk', trees='dk', dem_zoom=14),
}

name = sys.argv[1] if len(sys.argv) > 1 else ''
if name not in CITIES:
    raise SystemExit(f'usage: bake.py <{"|".join(CITIES)}>')
C = CITIES[name]
LAT0, LON0, COLS, ROWS, FAR_M = C['lat'], C['lon'], C['cols'], C['rows'], C['far']
W_M, H_M = COLS*C['chunk_m'], ROWS*C['chunk_m']
CACHE, OUT = ROOT/'.cache'/name, ROOT/'data'/name
CACHE.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)
K = math.cos(math.radians(LAT0))           # mercator -> ground metres


def merc(lon, lat):
    return R*math.radians(lon), R*math.log(math.tan(math.pi/4+math.radians(lat)/2))


CX, CY = merc(LON0, LAT0)


def world(lon, lat):
    mx, my = merc(lon, lat)
    return (mx-CX)*K, -(my-CY)*K           # x east, z south, in ground metres


def lonlat(x, z):
    mx, my = x/K+CX, -z/K+CY
    return math.degrees(mx/R), math.degrees(2*math.atan(math.exp(my/R))-math.pi/2)


def bbox_lonlat(margin=0):
    lon0, lat0 = lonlat(-W_M/2-margin, H_M/2+margin)
    lon1, lat1 = lonlat(W_M/2+margin, -H_M/2-margin)
    return lon0, lat0, lon1, lat1


def get(url, cache_name, secret=None, tries=5):
    """secret: (param, env var) appended only for the actual request. Errors print the cache name, never the URL."""
    p = CACHE/cache_name
    if p.exists() and p.stat().st_size:
        return p.read_bytes()
    p.parent.mkdir(parents=True, exist_ok=True)
    full = url
    if secret:
        full += ('&' if '?' in url else '?')+urllib.parse.urlencode({secret[0]: os.environ[secret[1]].strip()})
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(full, headers=UA), timeout=240) as r:
                b = r.read()
            if secret:             # some servers echo the key back in pagination links
                key = os.environ[secret[1]].strip()
                for form in {key, urllib.parse.quote(key, safe=''), urllib.parse.quote_plus(key)}:
                    b = b.replace(form.encode(), b'***')
            p.write_bytes(b)
            return b
        except urllib.error.HTTPError as e:
            print(f'  retry {cache_name}: HTTP {e.code}', flush=True)
        except Exception as e:
            print(f'  retry {cache_name}: {type(e).__name__}', flush=True)
        time.sleep(4*(i+1))
    raise SystemExit(f'failed: {cache_name}')


# ---------------------------------------------------------------- photos
def merc_bbox(x0, z0, x1, z1):
    return x0/K+CX, -z1/K+CY, x1/K+CX, -z0/K+CY


def wms(base, layer, box, w, h):
    a, b, c, d = box
    q = dict(SERVICE='WMS', VERSION='1.3.0', REQUEST='GetMap', LAYERS=layer, STYLES='', CRS='EPSG:3857',
             BBOX=f'{a},{b},{c},{d}', WIDTH=w, HEIGHT=h, FORMAT='image/jpeg')
    return base+urllib.parse.urlencode(q)


def arcgis(base, box, w, h):
    a, b, c, d = box
    return base+'?'+urllib.parse.urlencode(dict(bbox=f'{a},{b},{c},{d}', bboxSR=3857, imageSR=3857, size=f'{w},{h}', format='jpg', f='image'))


def photo(source, box, w, h, cache_name):
    if source == 'ign':
        b = get(wms('https://data.geopf.fr/wms-r/wms?', 'ORTHOIMAGERY.ORTHOPHOTOS', box, w, h), cache_name)
    elif source == 'nys':
        b = get(arcgis('https://orthos.its.ny.gov/arcgis/rest/services/wms/Latest/MapServer/export', box, w, h), cache_name)
    elif source == 'naip':
        b = get(arcgis('https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage', box, w, h), cache_name)
    elif source == 'berlin':
        b = get(wms('https://gdi.berlin.de/services/wms/truedop_2024?', 'truedop_2024', box, w, h), cache_name)
    elif source == 'dk':
        b = get(wms('https://api.dataforsyningen.dk/orto_foraar_DAF?', 'orto_foraar', box, w, h), cache_name, secret=('token', 'DATAFORSYNINGEN_TOKEN'))
    else:
        raise SystemExit('unknown photo source '+source)
    if not b.startswith(b'\xff\xd8'):
        (CACHE/cache_name).unlink()
        raise SystemExit(f'not a jpeg: {cache_name}: {b[:200]!r}')
    return Image.open(io.BytesIO(b)).convert('RGB')


def b64(b):
    return base64.b64encode(b).decode()


def write_js(file, key, payload):
    p = OUT/f'{file}.js'
    p.write_text(f'(window.T3=window.T3||{{}})[{json.dumps(key)}]={json.dumps(payload, separators=(",", ":"))};')
    print(f'  {file}.js {p.stat().st_size/1e6:.1f} MB', flush=True)


def ortho():
    print('ortho', flush=True)
    tile = CHUNK_PX//2
    cm = C['chunk_m']
    for r in range(ROWS):
        for c in range(COLS):
            if (OUT/f'g{r}{c}.js').exists():
                continue
            img = Image.new('RGB', (CHUNK_PX, CHUNK_PX))
            x0, z0 = -W_M/2+c*cm, -H_M/2+r*cm
            for tr in range(2):
                for tc in range(2):
                    box = merc_bbox(x0+tc*cm/2, z0+tr*cm/2, x0+(tc+1)*cm/2, z0+(tr+1)*cm/2)
                    img.paste(photo(C['photo'], box, tile, tile, f'o/{r}{c}{tr}{tc}.jpg'), (tc*tile, tr*tile))
            buf = io.BytesIO()
            img.save(buf, 'JPEG', quality=84, subsampling=2, optimize=True)
            write_js(f'g{r}{c}', f'g{r}{c}', 'data:image/jpeg;base64,'+b64(buf.getvalue()))
    img = Image.new('RGB', (4096, 4096))           # wide low-res ring so the edge of the detail area never shows
    s = FAR_M/2
    for tr in range(2):
        for tc in range(2):
            box = merc_bbox(-FAR_M/2+tc*s, -FAR_M/2+tr*s, -FAR_M/2+(tc+1)*s, -FAR_M/2+(tr+1)*s)
            img.paste(photo(C['far_photo'], box, 2048, 2048, f'o/far{tr}{tc}.jpg'), (tc*2048, tr*2048))
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=80, optimize=True)
    write_js('far', 'far', 'data:image/jpeg;base64,'+b64(buf.getvalue()))


# ---------------------------------------------------------------- vectors
def wfs(base, layer, tag, sort, margin=0, version_params=None, secret=None, n=5000, cql=None):
    lon0, lat0, lon1, lat1 = bbox_lonlat(margin)
    feats, start = [], 0
    while True:
        q = dict(SERVICE='WFS', VERSION='2.0.0', REQUEST='GetFeature', TYPENAMES=layer, SRSNAME='CRS:84',
                 OUTPUTFORMAT='application/json', COUNT=n, STARTINDEX=start)
        if sort:
            q['SORTBY'] = sort
        if cql:
            q['CQL_FILTER'] = cql.format(bbox=f'{lon0},{lat0},{lon1},{lat1}')
        else:
            q['BBOX'] = f'{lon0},{lat0},{lon1},{lat1},CRS:84'
        fs = json.loads(get(base+'?'+urllib.parse.urlencode(q), f'wfs/{tag}_{start}.json', secret=secret))['features']
        feats += fs
        print(f'  {tag} {len(feats)}', flush=True)
        if len(fs) < n:
            return feats
        start += n


def polys(feats, geom=lambda f: f.get('geometry')):
    for f in feats:
        g = geom(f)
        if not g:
            continue
        parts = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']] if g['type'] == 'Polygon' else []
        for poly in parts:
            rings = []
            for i, ring in enumerate(poly):
                pts = ring[:-1] if ring[0][:2] == ring[-1][:2] else ring
                rings.append([world(p[0], p[1]) for p in pts])
            yield f, rings, poly


def area(r):
    return abs(sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(r, r[1:]+r[:1])))/2


def pack(items):
    rc, pts, xy, h = [], [], [], []       # rings-per-poly, points-per-ring, coords, height
    for height, rings in items:
        rc.append(len(rings))
        h.append(height)
        for ring in rings:
            pts.append(len(ring))
            for x, z in ring:
                xy += [x, z]
    return dict(n=len(rc), rc=b64(struct.pack(f'<{len(rc)}H', *rc)), pts=b64(struct.pack(f'<{len(pts)}H', *pts)),
                xy=b64(struct.pack(f'<{len(xy)}f', *xy)), h=b64(struct.pack(f'<{len(h)}f', *h)))


def num(v):
    try:
        v = float(v)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


DK_WFS = 'https://wfs.datafordeler.dk/GEODKV/GEODKV_WFS/1.0.0/WFS'
DK_KEY = ('apikey', 'DATAFORDELER_API_KEY')
BE = 'https://gdi.berlin.de/services/wfs/'
IGN_WFS = 'https://data.geopf.fr/wfs/ows'


def socrata(dataset, tag, select, where, n=20000):
    rows, off = [], 0
    while True:
        q = {'$select': select, '$where': where, '$limit': n, '$offset': off, '$order': ':id'}
        fs = json.loads(get(f'https://data.cityofnewyork.us/resource/{dataset}.json?'+urllib.parse.urlencode(q), f'nyc/{tag}_{off}.json'))
        rows += fs
        print(f'  {tag} {len(rows)}', flush=True)
        if len(fs) < n:
            return rows
        off += n


def buildings(ground):
    print('buildings', flush=True)
    src, items = C['buildings'], []

    def add(rings, h):
        if rings and len(rings[0]) >= 3 and area(rings[0]) >= 15:
            items.append((h, [r for r in rings if len(r) >= 3 and (r is rings[0] or area(r) > 4)]))

    if src == 'ign':
        for f, rings, _ in polys(wfs(IGN_WFS, 'BDTOPO_V3:batiment', 'batiment', 'cleabs')):
            h = f['properties'].get('hauteur')
            add(rings, float(h) if h and h > 0 else 7.0)
    elif src == 'nyc':
        lon0, lat0, lon1, lat1 = bbox_lonlat()
        rows = socrata('5zhs-2jue', 'footprints', 'the_geom,height_roof', f'within_box(the_geom,{lat1},{lon0},{lat0},{lon1})')
        for f, rings, _ in polys(rows, lambda f: f.get('the_geom')):
            h = num(f.get('height_roof'))
            add(rings, h*.3048 if h and h > 0 else 7.0)        # dataset is in feet
    elif src == 'berlin':
        feats = wfs(BE+'alkis_gebaeude', 'alkis_gebaeude:gebaeude', 'gebaeude', 'uuid',
                    cql="bezeich='AX_Gebaeude' AND BBOX(geom,{bbox},'CRS:84')")
        for f, rings, _ in polys(feats):
            p = f['properties']
            floors = num(p.get('aog'))
            add(rings, min(floors, 42)*3.5 if floors else 8.0)     # Berlin publishes floor counts here, not heights
    elif src == 'dk':
        for f, rings, poly in polys(wfs(DK_WFS, 'geodkv_v001:bygning_current', 'bygning', None, secret=DK_KEY)):
            zs = [p[2] for p in poly[0] if len(p) > 2 and p[2] > -100]     # roofs carry real elevations; -999 means unmeasured
            if not zs or not rings or not rings[0]:
                continue
            x, z = rings[0][0]
            add(rings, min(150.0, max(3.0, sum(zs)/len(zs)-ground(x, z))))  # mean height sits halfway up a pitched roof
    print(' kept', len(items), 'max h', round(max(i[0] for i in items)), flush=True)
    write_js('buildings', 'buildings', pack(items))


def water_mask(sea_below, land=(), water=(), all_water_east_of=None):
    """Image mask, for shorelines with no polygon: low ground is water, known land and lakes are then drawn on top."""
    w, h = 4096, round(4096*H_M/W_M)
    g = np.zeros((257, round(257*H_M/W_M)), dtype=np.float32)
    grid = [[RAW(-W_M/2+W_M*i/256, -H_M/2+H_M*j/(g.shape[1]-1)) for i in range(257)] for j in range(g.shape[1])]
    arr = np.array(grid, dtype=np.float32)
    im = Image.fromarray(arr, 'F').resize((w, h), Image.BICUBIC)
    a = (np.asarray(im) < sea_below).astype(np.uint8)*255
    im = Image.fromarray(a, 'L')
    d = ImageDraw.Draw(im)
    sx, sz = w/W_M, h/H_M
    conv = lambda r: [((x+W_M/2)*sx, (z+H_M/2)*sz) for x, z in r]
    if all_water_east_of:          # where every shore has an exact land polygon, the noisy elevation test isn't needed
        line = [world(lo, la) for la, lo in all_water_east_of]
        d.polygon(conv(line)+[(w, conv(line)[-1][1]), (w, conv(line)[0][1])], fill=255)
    for rings in land:
        d.polygon(conv(rings[0]), fill=0)
    for rings in water:
        d.polygon(conv(rings[0]), fill=255)
    im = im.filter(ImageFilter.GaussianBlur(1.2))
    buf = io.BytesIO()
    im.save(buf, 'PNG', optimize=True)
    write_js('water', 'watermask', 'data:image/png;base64,'+b64(buf.getvalue()))


def water():
    print('water', flush=True)
    src = C['water']
    if src == 'ign':
        feats = wfs(IGN_WFS, 'BDTOPO_V3:surface_hydrographique', 'hydro', 'cleabs', margin=500)
        write_js('water', 'water', pack([(0.0, rings) for f, rings, _ in polys(feats) if rings and area(rings[0]) > 400]))
    elif src == 'berlin':
        feats = wfs(BE+'gewaesserkarte', 'gewaesserkarte:e_gew_gewaesser_fl', 'hydro', None, margin=500)
        write_js('water', 'water', pack([(0.0, rings) for f, rings, _ in polys(feats) if rings and area(rings[0]) > 200]))
    elif src == 'nyc':
        rows = json.loads(get('https://data.cityofnewyork.us/resource/gthc-hcne.json?$limit=10', 'boroughs.json'))
        water_mask(4.0, land=[rings for _, rings, _ in polys(rows, lambda f: f.get('the_geom'))],
                   all_water_east_of=[(40.60, -74.075), (40.70, -74.030), (40.74, -74.022), (40.80, -73.985), (40.90, -73.925)])  # mid-Hudson: NJ has no polygons here
    elif src == 'dk':
        lakes = wfs(DK_WFS, 'geodkv_v001:soe_current', 'soe', None, margin=300, secret=DK_KEY)
        water_mask(0.8, water=[rings for _, rings, _ in polys(lakes)])


def trees():
    print('trees', flush=True)
    src, out = C['trees'], []
    if src == 'paris':
        lon0, lat0, lon1, lat1 = bbox_lonlat()
        q = dict(select='geo_point_2d,hauteurenm,circonferenceencm', limit=-1, where=f"in_bbox(geo_point_2d,{lat0},{lon0},{lat1},{lon1})")
        for t in json.loads(get('https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/les-arbres/exports/json?'+urllib.parse.urlencode(q), 'trees.json')):
            g = t.get('geo_point_2d')
            if not g:
                continue
            x, z = world(g['lon'], g['lat'])
            h = t.get('hauteurenm') or 0
            c = t.get('circonferenceencm') or 0
            if not 3 <= h <= 40:                      # dataset has lots of 0/junk heights
                h = min(28, 6+c*0.09) if 20 < c < 700 else 11
            out += [x, z, h]
    elif src == 'nyc':
        lon0, lat0, lon1, lat1 = bbox_lonlat()
        for t in socrata('uvpi-gqnh', 'trees', 'latitude,longitude,tree_dbh,status', f"status='Alive' AND latitude between '{lat0:.4f}' and '{lat1:.4f}'"):
            la, lo = num(t.get('latitude')), num(t.get('longitude'))
            if la is None or lo is None or not lon0 <= lo <= lon1:      # text columns: longitude can only be filtered here
                continue
            x, z = world(lo, la)
            out += [x, z, min(26.0, 5+(num(t.get('tree_dbh')) or 8)*.6)]      # census gives trunk diameter in inches
    elif src == 'berlin':
        for layer in ('strassenbaeume', 'anlagenbaeume'):
            for f in wfs(BE+'baumbestand', 'baumbestand:'+layer, layer, 'gisid'):
                g = f.get('geometry')
                if not g or g['type'] != 'Point':
                    continue
                x, z = world(*g['coordinates'][:2])
                h = num(f['properties'].get('baumhoehe')) or 0
                out += [x, z, h if 3 <= h <= 40 else 13]
    elif src == 'dk':
        for f in wfs(DK_WFS, 'geodkv_v001:trae_current', 'trae', None, secret=DK_KEY):
            g = f.get('geometry')
            if g and g['type'] == 'Point':
                x, z = world(*g['coordinates'][:2])
                out += [x, z, 11.0]
    print(' trees', len(out)//3, flush=True)
    write_js('trees', 'trees', dict(n=len(out)//3, d=b64(struct.pack(f'<{len(out)}f', *out))))


# ---------------------------------------------------------------- terrain
tiles = {}
DEM_Z = C.get('dem_zoom', 13)


def raw_lonlat(lon, lat):
    n = 2**DEM_Z
    mx, my = merc(lon, lat)
    u, v = (mx/(2*math.pi*R)+.5)*n*256, (.5-my/(2*math.pi*R))*n*256
    key = int(u//256), int(v//256)
    if key not in tiles:
        b = get(f'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{DEM_Z}/{key[0]}/{key[1]}.png', f'dem/{DEM_Z}_{key[0]}_{key[1]}.png')
        tiles[key] = Image.open(io.BytesIO(b)).convert('RGB').load()
    r, g, bl = tiles[key][int(u % 256), int(v % 256)]
    return r*256+g+bl/256-32768


def RAW(x, z):
    return raw_lonlat(*lonlat(x, z))


def terrain():
    print('terrain', flush=True)
    GW, GH = 257, 193
    x0, z0, sx, sz = -W_M/2-200, -H_M/2-200, W_M+400, H_M+400
    H = np.array([[RAW(x0+sx*i/(GW-1), z0+sz*j/(GH-1)) for i in range(GW)] for j in range(GH)], dtype=np.float32)
    kern = np.ones(5)/5                       # the DEM is noisy over a city; keep only the real relief
    for _ in range(3):
        H = np.apply_along_axis(lambda a: np.convolve(np.pad(a, 2, mode='edge'), kern, 'valid'), 0, H)
        H = np.apply_along_axis(lambda a: np.convolve(np.pad(a, 2, mode='edge'), kern, 'valid'), 1, H)
    H = H.astype(np.float32)
    print(f' elev {H.min():.0f}..{H.max():.0f}', flush=True)
    write_js('terrain', 'terrain', dict(w=GW, h=GH, x0=x0, z0=z0, sx=sx, sz=sz, d=b64(H.tobytes())))


if __name__ == '__main__':
    meta = dict(lat0=LAT0, lon0=LON0, W=W_M, H=H_M, cols=COLS, rows=ROWS, far=FAR_M)
    (OUT/'meta.js').write_text('(window.T3=window.T3||{}).meta='+json.dumps(meta)+';')
    terrain()
    water()
    trees()
    buildings(RAW)
    ortho()
    print('DONE', name, flush=True)
