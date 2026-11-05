# Turtle 3D

A Wordle-style city guessing game. You're looking down from a plane; name the city. Every wrong guess, the plane descends.

**Play:** https://kaliffen.github.io/turtle-3d/

**Run it locally:** double-click `index.html`. No server. It needs internet only for three.js (CDN); all geodata is local in `data/`.

Cities: Paris, New York, Berlin, Aarhus, Galten. One per day in rotation, or pick with `?city=galten`.

After a round the plane hands over to you: **WASD** move, **mouse** look (click to capture), **Shift** fast, **E/Q** up/down, **wheel** speed, **Esc** release.

**F2** toggles the FPS readout. `?u=0.33&alt=1100` starts at a given route position and altitude.

## Layout

- `index.html`: renderer, game and per-city settings (`CITY_DEFS`), all in one file
- `data/<city>/`: baked city data, loaded with script tags because `file://` pages can't `fetch()` local files
- `tools/bake.py <city>`: rebuilds a city (needs Pillow and numpy); downloads are cached in `.cache/<city>/`
- `tools/check.mjs`: runs the page in Chrome on the real GPU for frame timing, screenshots and a playthrough. `CITY=berlin` picks the city, `JUMP=lat,lon,alt` adds a close-up, `HEADED=1` shows the window.

Baking Aarhus or Galten needs `DATAFORSYNINGEN_TOKEN` and `DATAFORDELER_API_KEY` in the environment. Keys are never written to cache names, logs or output.

## Data sources

| City | Photos | Buildings | Heights | Trees |
|---|---|---|---|---|
| Paris | IGN BD ORTHO | IGN BD TOPO | measured | Ville de Paris |
| New York | USGS NAIP | NYC Open Data | measured | NYC street tree census |
| Berlin | Geoportal Berlin true orthophoto | ALKIS | floor count × 3.5 m | Geoportal Berlin |
| Aarhus, Galten | SDFI GeoDanmark Ortofoto | GeoDanmark | roof elevation minus terrain | GeoDanmark |

Elevation everywhere: Terrarium tiles (AWS Open Data / Mapzen). Hand-built models: Eiffel Tower, Berlin TV Tower, ARoS rainbow.

Credits only appear on the end screen, because the source names give away the answer.
