#!/usr/bin/env python3
"""Check whether the Zemelya API returns parcel boundaries for our parcels.

API docs: https://zemelyabot.ru/api-docs/  (POST /cn_data, Bearer token)

Setup (once), from the repo root:

    python -m pip install requests
    echo 'ZEMELYA_TOKEN=ваш_токен' >> .env      # .env is git-ignored

Run:

    python tools/zemelya_probe.py            # demo number, free
    python tools/zemelya_probe.py --real     # our 3 real parcels (uses quota)

For every parcel the raw response is saved to zemelya_probe_out/, and if a
boundary is returned, a GeoJSON in the project contract format is written
to data/samples/real_<number>.geojson and validated with read_cadastre.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

API_URL = "https://service.zemelyabot.ru/cn_data"
OUT = ROOT / "zemelya_probe_out"
DEMO = ["23:49:0000000:8273"]  # documented demo number, does not use quota
REAL = [
    "50:11:0020104:28236",   # 600 m², boundaries present in NSPD
    "50:11:0020104:28641",   # 800 m², boundaries present in NSPD
    "50:11:0050507:130",     # 1000 m², NO boundaries in EGRN -> expect no_coords
]
PAUSE_S = 7  # documented limit: 10 requests/min


def load_token() -> str:
    token = os.getenv("ZEMELYA_TOKEN")
    env = ROOT / ".env"
    if not token and env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("ZEMELYA_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not token:
        sys.exit("Нет ZEMELYA_TOKEN: добавьте строку ZEMELYA_TOKEN=... в файл .env")
    return token


def find(obj, key):
    """Find the first value for `key` anywhere in a nested JSON structure."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = find(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = find(v, key)
            if found is not None:
                return found
    return None


def to_contract_geojson(num: str, payload: dict) -> dict | None:
    geometry = find(payload, "area_geometry")
    if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        return None
    area = find(payload, "specified_area") or find(payload, "declared_area")
    props = {
        "cadastral_number": num,
        "area_m2": float(area) if area is not None else None,
        "area_unit": "m2",
        "land_category": find(payload, "land_record_category_type"),
        "permitted_use": find(payload, "permitted_use_established_by_document"),
        "source": "zemelya_api",
    }
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": props, "geometry": geometry}],
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true", help="query our 3 real parcels")
    args = parser.parse_args()

    token = load_token()
    numbers = REAL if args.real else DEMO
    OUT.mkdir(exist_ok=True)
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"

    for i, num in enumerate(numbers):
        if i:
            time.sleep(PAUSE_S)
        slug = num.replace(":", "-")
        started = time.monotonic()
        try:
            resp = session.post(API_URL, json={"cad_num": num}, timeout=60)
        except requests.RequestException as exc:
            print(f"{num}: ошибка соединения {type(exc).__name__}: {exc}")
            continue
        elapsed = time.monotonic() - started
        (OUT / f"{slug}.raw.txt").write_text(resp.text, encoding="utf-8")
        print(f"\n{num}: HTTP {resp.status_code}, {elapsed:.1f} с")
        try:
            payload = resp.json()
        except ValueError:
            print("  ответ не JSON — см. файл", OUT / f"{slug}.raw.txt")
            continue

        no_coords = find(payload, "no_coords")
        geo = to_contract_geojson(num, payload)
        print(f"  no_coords = {no_coords}")
        if geo is None:
            status = find(payload, "status") or find(payload, "task_id")
            print(f"  контура нет в ответе (status/task: {status})")
            continue
        geom = geo["features"][0]["geometry"]
        print(f"  контур: {geom['type']}, площадь в ответе: {geo['features'][0]['properties']['area_m2']}")
        if args.real:
            path = ROOT / "data" / "samples" / f"real_{slug}.geojson"
            path.write_text(json.dumps(geo, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                from cadastre.read_cadastre import read_cadastre
                data = read_cadastre(path)
                print(f"  read_cadastre: OK, площадь по геометрии {data['geometry_area_m2']} м², "
                      f"расхождение {data['area_relative_error']:.2%}")
            except Exception as exc:  # report, don't hide
                print(f"  read_cadastre: ОШИБКА {exc}")

    print(f"\nСырые ответы: {OUT}")


if __name__ == "__main__":
    main()
