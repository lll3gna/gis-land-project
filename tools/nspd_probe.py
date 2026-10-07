#!/usr/bin/env python3
"""Probe NSPD access channels and save raw responses for analysis.

Spike for the question: can we fetch a parcel's boundary from NSPD
by cadastral number, and through which channel?

Run on a computer with a RUSSIAN IP (VPN off), from the repo root:

    python -m pip install requests truststore
    python tools/nspd_probe.py

`truststore` makes Python trust the same certificates as macOS/Windows,
so the Mintsifry root certificate installed in the system keychain is
used and TLS verification stays ON.

Results go to nspd_probe_out/ (one file per request + summary.json).
The script sends a handful of requests with pauses; it does not try to
bypass any protection. Personal data is not requested.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import quote

import truststore

truststore.inject_into_ssl()

import requests  # noqa: E402  (must be imported after truststore injection)

OUT = Path("nspd_probe_out")
PAUSE_S = 2.0
TIMEOUT_S = 25
MAX_BODY = 2_000_000

PARCELS = [
    "50:11:0020104:28236",   # 600 m², boundaries present
    "50:11:0020104:28641",   # 800 m², boundaries present
    "50:11:0050507:130",     # 1000 m², NO boundaries in EGRN
]

CHECKS: list[tuple[str, str]] = [
    ("site_root", "https://nspd.gov.ru/"),
    ("ip_check", "https://ipinfo.io/json"),
    # Official WFS address mentioned in docs/data-sources-comparison.md
    ("wfs_rosreestr_caps",
     "https://nspd.rosreestr.gov.ru/api/wfs/v2?service=WFS&request=GetCapabilities"),
    ("wfs_nspd_caps",
     "https://nspd.gov.ru/api/wfs/v2?service=WFS&request=GetCapabilities"),
]
for num in PARCELS:
    slug = num.replace(":", "-")
    # Search endpoint used by the NSPD web map (not an official public API)
    CHECKS.append((
        f"search_{slug}",
        "https://nspd.gov.ru/api/geoportal/v2/search/geoportal"
        f"?thematicSearchId=1&query={quote(num)}",
    ))


def save(name: str, resp: requests.Response | None, error: str | None, elapsed: float) -> dict:
    record = {"name": name, "elapsed_s": round(elapsed, 2)}
    if resp is None:
        record["error"] = error
        (OUT / f"{name}.error.txt").write_text(error or "", encoding="utf-8")
        return record
    ctype = resp.headers.get("Content-Type", "")
    record.update({
        "status": resp.status_code,
        "content_type": ctype,
        "bytes": len(resp.content),
        "final_url": resp.url,
    })
    ext = "json" if "json" in ctype else ("xml" if "xml" in ctype else "txt")
    body = resp.content[:MAX_BODY]
    (OUT / f"{name}.{ext}").write_bytes(body)
    return record


def main() -> None:
    OUT.mkdir(exist_ok=True)
    session = requests.Session()
    session.headers["Accept"] = "application/json, text/xml, */*"
    summary = []
    for name, url in CHECKS:
        started = time.monotonic()
        try:
            resp = session.get(url, timeout=TIMEOUT_S)
            rec = save(name, resp, None, time.monotonic() - started)
        except requests.RequestException as exc:
            rec = save(name, None, f"{type(exc).__name__}: {exc}", time.monotonic() - started)
        rec["url"] = url
        summary.append(rec)
        status = rec.get("status", rec.get("error", "?"))
        print(f"{name:32} -> {str(status)[:70]}  ({rec['elapsed_s']} s)")
        time.sleep(PAUSE_S)
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nГотово. Результаты в папке {OUT.resolve()}")


if __name__ == "__main__":
    main()
