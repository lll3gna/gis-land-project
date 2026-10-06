#!/usr/bin/env python3
"""Generate the synthetic VOK-104 sample data in data/samples/.

Writes two files that describe the SAME place, so the cadastre and imagery
modules can be tested together:

- vok104_boundary.geojson — a ~10-sotka parcel (≈1000 m², MVP size range);
- vok104_imagery.tif      — a 16-bit RGB GeoTIFF in UTM 37N (EPSG:32637),
                            0.5 m/pixel (MVP GSD criterion), covering the
                            parcel with a margin and a nodata=0 frame.

Only the Python standard library is used, so the output is reproducible
without GDAL/pyproj. UTM coordinates use the Krüger series (Karney 2011),
accurate to well under a millimetre.

Run from the repository root:

    python tools/make_sample_data.py
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "samples"

# Parcel corners (WGS 84). 0.0005° lon × 0.000285° lat at 55.75°N ≈ 31.4 × 31.7 m.
LON_MIN, LON_MAX = 37.6000, 37.6005
LAT_MIN, LAT_MAX = 55.7500, 55.750285
DECLARED_AREA_M2 = 1000.0

PIXEL_SIZE = 0.5    # metres per pixel
MARGIN_M = 15.0     # imagery extends this far beyond the parcel on every side
NODATA_FRAME = 6    # pixels of nodata=0 around the image edge

UTM_ZONE = 37
A = 6378137.0
F = 1 / 298.257223563


def lonlat_to_utm(lon: float, lat: float, zone: int = UTM_ZONE) -> tuple[float, float]:
    """WGS 84 lon/lat -> UTM (northern hemisphere) easting/northing in metres."""
    n = F / (2 - F)
    big_a = A / (1 + n) * (1 + n * n / 4 + n ** 4 / 64)
    alpha = (
        None,
        n / 2 - 2 * n * n / 3 + 5 * n ** 3 / 16 + 41 * n ** 4 / 180,
        13 * n * n / 48 - 3 * n ** 3 / 5 + 557 * n ** 4 / 1440,
        61 * n ** 3 / 240 - 103 * n ** 4 / 140,
        49561 * n ** 4 / 161280,
    )
    e = math.sqrt(F * (2 - F))
    phi = math.radians(lat)
    lam = math.radians(lon) - math.radians(zone * 6 - 183)
    t = math.sinh(math.atanh(math.sin(phi)) - e * math.atanh(e * math.sin(phi)))
    xi = math.atan2(t, math.cos(lam))
    eta = math.atanh(math.sin(lam) / math.sqrt(1 + t * t))
    x = eta + sum(alpha[j] * math.cos(2 * j * xi) * math.sinh(2 * j * eta) for j in range(1, 5))
    y = xi + sum(alpha[j] * math.sin(2 * j * xi) * math.cosh(2 * j * eta) for j in range(1, 5))
    return 500000 + 0.9996 * big_a * x, 0.9996 * big_a * y


def write_geojson(path: Path) -> None:
    ring = [
        [LON_MIN, LAT_MIN], [LON_MAX, LAT_MIN], [LON_MAX, LAT_MAX],
        [LON_MIN, LAT_MAX], [LON_MIN, LAT_MIN],
    ]
    data = {
        "type": "FeatureCollection",
        "name": "vok104_boundary_synthetic",
        "features": [{
            "type": "Feature",
            "properties": {
                "cadastral_number": "50:11:0000000:104",
                "area_m2": DECLARED_AREA_M2,
                "area_unit": "m2",
                "land_category": "земли населённых пунктов",
                "permitted_use": "для индивидуального жилищного строительства",
            },
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        }],
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_pixels(width: int, height: int, origin_x: float, origin_y: float,
                parcel: tuple[float, float, float, float]) -> bytes:
    """Interleaved RGB uint16 pixels: grass, a house, a path; nodata frame = 0."""
    pe0, pn0, pe1, pn1 = parcel
    cx, cy = (pe0 + pe1) / 2, (pn0 + pn1) / 2
    out = bytearray()
    for row in range(height):
        for col in range(width):
            if (row < NODATA_FRAME or col < NODATA_FRAME
                    or row >= height - NODATA_FRAME or col >= width - NODATA_FRAME):
                out += struct.pack("<HHH", 0, 0, 0)
                continue
            x = origin_x + (col + 0.5) * PIXEL_SIZE
            y = origin_y - (row + 0.5) * PIXEL_SIZE
            # grass with a gentle gradient; every valid value stays >= 1000
            r, g, b = 9000 + col * 20, 16000 + row * 15, 7000
            if abs(x - cx) < 6 and abs(y - cy) < 5:          # house 12 × 10 m
                r, g, b = 42000, 38000, 36000
            elif abs(x - (pe0 + 4)) < 1.5 and pn0 <= y <= cy:  # 3 m path
                r, g, b = 30000, 29000, 27000
            elif not (pe0 <= x <= pe1 and pn0 <= y <= pn1):    # neighbours: darker
                r, g = r - 3000, g - 4000
            out += struct.pack("<HHH", r, g, b)
    return bytes(out)


def write_geotiff(path: Path) -> None:
    corners = [lonlat_to_utm(lo, la) for lo in (LON_MIN, LON_MAX) for la in (LAT_MIN, LAT_MAX)]
    pe0 = min(c[0] for c in corners); pe1 = max(c[0] for c in corners)
    pn0 = min(c[1] for c in corners); pn1 = max(c[1] for c in corners)

    origin_x = math.floor((pe0 - MARGIN_M) / PIXEL_SIZE) * PIXEL_SIZE
    origin_y = math.ceil((pn1 + MARGIN_M) / PIXEL_SIZE) * PIXEL_SIZE
    width = math.ceil((pe1 + MARGIN_M - origin_x) / PIXEL_SIZE)
    height = math.ceil((origin_y - (pn0 - MARGIN_M)) / PIXEL_SIZE)
    pixels = make_pixels(width, height, origin_x, origin_y, (pe0, pn0, pe1, pn1))

    geo_keys = [
        1, 1, 0, 7,
        1024, 0, 1, 1,          # GTModelType = Projected
        1025, 0, 1, 1,          # GTRasterType = PixelIsArea
        1026, 34737, 22, 0,     # GTCitation
        2049, 34737, 7, 22,     # GeogCitation
        2054, 0, 1, 9102,       # GeogAngularUnits = degree
        3072, 0, 1, 32600 + UTM_ZONE,  # ProjectedCSType = EPSG:32637
        3076, 0, 1, 9001,       # ProjLinearUnits = metre
    ]
    citation = f"WGS 84 / UTM zone {UTM_ZONE}N|WGS 84|\0".encode("ascii")
    gdal_meta = (
        '<GDALMetadata>\n'
        '  <Item name="COLORINTERP" sample="0" role="colorinterp">Red</Item>\n'
        '  <Item name="COLORINTERP" sample="1" role="colorinterp">Green</Item>\n'
        '  <Item name="COLORINTERP" sample="2" role="colorinterp">Blue</Item>\n'
        '</GDALMetadata>\n\0'
    ).encode("ascii")

    # (tag, type, values) — type 2=ASCII(bytes), 3=SHORT, 4=LONG, 12=DOUBLE
    entries = [
        (256, 3, [width]), (257, 3, [height]), (258, 3, [16, 16, 16]),
        (259, 3, [1]), (262, 3, [1]), (273, 4, [0]), (277, 3, [3]),
        (278, 3, [height]), (279, 4, [len(pixels)]), (284, 3, [1]),
        (338, 3, [0, 0]), (339, 3, [1, 1, 1]),
        (33550, 12, [PIXEL_SIZE, PIXEL_SIZE, 0.0]),
        (33922, 12, [0.0, 0.0, 0.0, origin_x, origin_y, 0.0]),
        (34735, 3, geo_keys), (34737, 2, citation),
        (42112, 2, gdal_meta), (42113, 2, b"0\0"),
    ]
    fmt = {3: "H", 4: "I", 12: "d"}
    size = {2: 1, 3: 2, 4: 4, 12: 8}

    ifd_size = 2 + 12 * len(entries) + 4
    extra_start = 8 + ifd_size
    extra = bytearray()
    payloads = []
    for tag, typ, vals in entries:
        raw = vals if typ == 2 else struct.pack("<" + fmt[typ] * len(vals), *vals)
        if len(raw) <= 4:
            payloads.append(raw.ljust(4, b"\0"))
        else:
            if (extra_start + len(extra)) % 2:
                extra += b"\0"
            payloads.append(struct.pack("<I", extra_start + len(extra)))
            extra += raw
    pixel_offset = extra_start + len(extra)
    if pixel_offset % 2:
        extra += b"\0"
        pixel_offset += 1

    ifd = bytearray(struct.pack("<H", len(entries)))
    for (tag, typ, vals), payload in zip(entries, payloads):
        count = len(vals) if typ != 2 else len(vals)
        if tag == 273:
            payload = struct.pack("<I", pixel_offset)
        ifd += struct.pack("<HHI", tag, typ, count) + payload
    ifd += struct.pack("<I", 0)

    path.write_bytes(b"II*\0" + struct.pack("<I", 8) + ifd + extra + pixels)
    print(f"{path.name}: {width}x{height} px, {PIXEL_SIZE} m/px, "
          f"origin E{origin_x} N{origin_y}, parcel E{pe0:.1f}..{pe1:.1f} N{pn0:.1f}..{pn1:.1f}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_geojson(OUT_DIR / "vok104_boundary.geojson")
    write_geotiff(OUT_DIR / "vok104_imagery.tif")


if __name__ == "__main__":
    main()
