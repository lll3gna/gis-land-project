#!/usr/bin/env python3
"""Prepare VOK-104 imagery while preserving georeferencing.

GeoTIFF input is reprojected to a configurable metric CRS, normalized using
percentile clipping, resized with a matching affine transform, and written
both as a georeferenced GeoTIFF and a PNG for segmentation. A JSON manifest
and PNG world file preserve the spatial contract.

Prompt reference: prompts/gis_prompts.md, section 2 (updated to require
georeferencing, nodata, percentile normalization and explicit band mapping).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import ColorInterp, Resampling
from rasterio.transform import Affine
from rasterio.warp import calculate_default_transform, reproject

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_PATH = PROJECT_ROOT / "data" / "samples" / "vok104_imagery.tif"
INPUT_PATH = Path(os.getenv("IMAGERY_INPUT_PATH", str(DEFAULT_INPUT_PATH)))
TARGET_CRS = os.getenv("IMAGERY_WORKING_CRS", "EPSG:6933")
EXCHANGE_CRS = "EPSG:4326"
MAX_IMAGE_SIZE = int(os.getenv("IMAGERY_MAX_SIZE", "2048"))
LOW_PERCENTILE = float(os.getenv("IMAGERY_LOW_PERCENTILE", "2"))
HIGH_PERCENTILE = float(os.getenv("IMAGERY_HIGH_PERCENTILE", "98"))
IMAGE_DATE = os.getenv("IMAGERY_DATE", date.today().isoformat())
BAND_MAPPING = os.getenv("IMAGERY_BANDS")
DEFAULT_STEM = f"{IMAGE_DATE}_vok104_cadastre"
OUTPUT_DIR = Path(os.getenv("IMAGERY_OUTPUT_DIR", str(PROJECT_ROOT / "data" / "samples")))
OUTPUT_TIFF = OUTPUT_DIR / f"{DEFAULT_STEM}.tif"
OUTPUT_PNG = OUTPUT_DIR / f"{DEFAULT_STEM}.png"
OUTPUT_MASK = OUTPUT_DIR / f"{DEFAULT_STEM}_nodata_mask.png"
OUTPUT_MANIFEST = OUTPUT_DIR / f"{DEFAULT_STEM}.json"


def log(message: str) -> None:
    print(f"[imagery] {message}")


def validate_input_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Входной файл не найден: {path}")
    if path.suffix.lower() not in {".tif", ".tiff", ".png", ".jpg", ".jpeg"}:
        raise ValueError(f"Неподдерживаемый формат: {path.suffix}")


def parse_band_mapping(count: int, colorinterp: tuple[ColorInterp, ...]) -> list[int]:
    if count == 1:
        return [1]
    if BAND_MAPPING:
        try:
            bands = [int(x.strip()) for x in BAND_MAPPING.split(",")]
        except ValueError as exc:
            raise ValueError("IMAGERY_BANDS должен иметь вид 3,2,1.") from exc
        if len(bands) != 3 or any(b < 1 or b > count for b in bands):
            raise ValueError(f"Некорректный IMAGERY_BANDS={BAND_MAPPING!r}.")
        return bands

    wanted = {ColorInterp.red: None, ColorInterp.green: None, ColorInterp.blue: None}
    for i, interp in enumerate(colorinterp, start=1):
        if interp in wanted:
            wanted[interp] = i
    if all(wanted.values()):
        return [wanted[ColorInterp.red], wanted[ColorInterp.green], wanted[ColorInterp.blue]]

    raise ValueError(
        "Нельзя безопасно определить RGB-каналы. "
        "Укажите IMAGERY_BANDS=R,G,B (например 3,2,1)."
    )


def percentile_normalize(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Normalize a band with robust low/high percentile clipping."""
    result = np.zeros(values.shape, dtype=np.uint8)
    finite = np.isfinite(values) & valid
    if not finite.any():
        return result

    sample = values[finite].astype(np.float32)
    lo, hi = np.percentile(sample, [LOW_PERCENTILE, HIGH_PERCENTILE])
    if hi <= lo:
        result[finite] = 0
        return result

    scaled = (values.astype(np.float32) - lo) / (hi - lo) * 255.0
    result[finite] = np.clip(scaled[finite], 0, 255).astype(np.uint8)
    return result


def resize_array_and_transform(
    rgb: np.ndarray,
    valid: np.ndarray,
    transform: Affine,
) -> tuple[np.ndarray, np.ndarray, Affine]:
    height, width = valid.shape
    largest = max(width, height)
    if largest <= MAX_IMAGE_SIZE:
        return rgb, valid, transform

    scale = MAX_IMAGE_SIZE / largest
    new_width = max(1, round(width * scale))
    new_height = max(1, round(height * scale))
    image = Image.fromarray(np.transpose(rgb, (1, 2, 0)), mode="RGB")
    image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    mask = Image.fromarray((valid.astype(np.uint8) * 255), mode="L")
    mask = mask.resize((new_width, new_height), Image.Resampling.NEAREST)

    # Pixel size changes with the resize; the origin remains unchanged.
    new_transform = transform * Affine.scale(width / new_width, height / new_height)
    return (
        np.transpose(np.asarray(image), (2, 0, 1)),
        np.asarray(mask) > 0,
        new_transform,
    )


def write_world_file(path: Path, transform: Affine) -> None:
    """Write a PNG world file (.pgw) from the final affine transform."""
    x_size = transform.a
    y_size = transform.e
    x_origin = transform.c + transform.a / 2 + transform.b / 2
    y_origin = transform.f + transform.d / 2 + transform.e / 2
    path.write_text(
        f"{x_size:.15f}\n{transform.d:.15f}\n{transform.b:.15f}\n"
        f"{y_size:.15f}\n{x_origin:.15f}\n{y_origin:.15f}\n",
        encoding="ascii",
    )


def process_geotiff(path: Path) -> tuple[np.ndarray, np.ndarray, Affine, str, dict]:
    with rasterio.open(path) as src:
        if src.crs is None:
            raise ValueError("GeoTIFF не содержит CRS.")
        bands = parse_band_mapping(src.count, src.colorinterp)
        transform, width, height = calculate_default_transform(
            src.crs, TARGET_CRS, src.width, src.height, *src.bounds
        )
        data = np.zeros((len(bands), height, width), dtype=np.float32)
        valid = np.ones((height, width), dtype=bool)

        for i, band in enumerate(bands):
            src_data = src.read(band)
            src_valid = src.read_masks(band) > 0
            if src.nodata is not None:
                src_valid &= src_data != src.nodata

            dst = np.zeros((height, width), dtype=np.float32)
            dst_valid = np.zeros((height, width), dtype=np.uint8)
            reproject(
                source=src_data,
                destination=dst,
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=src.nodata,
                dst_transform=transform,
                dst_crs=TARGET_CRS,
                dst_nodata=0,
                resampling=Resampling.bilinear,
            )
            reproject(
                source=src_valid.astype(np.uint8),
                destination=dst_valid,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=transform,
                dst_crs=TARGET_CRS,
                dst_nodata=0,
                resampling=Resampling.nearest,
            )
            data[i] = dst
            valid &= dst_valid.astype(bool)

        rgb = np.stack(
            [percentile_normalize(data[i], valid) for i in range(len(bands))]
        )
        rgb, valid, transform = resize_array_and_transform(rgb, valid, transform)
        manifest = {
            "source_crs": str(src.crs),
            "working_crs": TARGET_CRS,
            "exchange_crs": EXCHANGE_CRS,
            "bands": bands,
            "source_nodata": src.nodata,
            "normalization": {
                "method": "percentile_clip",
                "low": LOW_PERCENTILE,
                "high": HIGH_PERCENTILE,
            },
        }
        return rgb, valid, transform, TARGET_CRS, manifest


def process_regular_image(path: Path) -> tuple[np.ndarray, np.ndarray, Affine | None, str | None, dict]:
    with Image.open(path) as image:
        image = image.convert("RGB")
        image = image.copy()
    if max(image.size) > MAX_IMAGE_SIZE:
        scale = MAX_IMAGE_SIZE / max(image.size)
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
    rgb = np.transpose(np.asarray(image), (2, 0, 1))
    valid = np.ones((image.height, image.width), dtype=bool)
    return rgb, valid, None, None, {
        "source_crs": None,
        "working_crs": None,
        "exchange_crs": None,
        "bands": [1, 2, 3],
        "normalization": None,
        "georeferenced": False,
    }


def save_outputs(
    rgb: np.ndarray,
    valid: np.ndarray,
    transform: Affine | None,
    crs: str | None,
    manifest: dict,
) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Invalid pixels are explicitly masked in the sidecar mask rather than
    # silently treated as real black imagery.
    image = Image.fromarray(np.transpose(rgb, (1, 2, 0)), mode="RGB")
    image.save(OUTPUT_PNG, format="PNG")
    Image.fromarray((~valid * 255).astype(np.uint8), mode="L").save(OUTPUT_MASK)

    if transform is not None and crs is not None:
        profile = {
            "driver": "GTiff",
            "height": rgb.shape[1],
            "width": rgb.shape[2],
            "count": 3,
            "dtype": "uint8",
            "crs": crs,
            "transform": transform,
            "nodata": 0,
            "compress": "deflate",
        }
        with rasterio.open(OUTPUT_TIFF, "w", **profile) as dst:
            dst.write(rgb)
            dst.colorinterp = (ColorInterp.red, ColorInterp.green, ColorInterp.blue)
        write_world_file(OUTPUT_PNG.with_suffix(".pgw"), transform)
        manifest["georeferenced"] = True
        manifest["transform"] = list(transform)
        manifest["crs"] = crs
    else:
        manifest["georeferenced"] = False
        manifest["transform"] = None
        manifest["crs"] = None

    manifest.update({
        "schema_version": "1.0",
        "png": OUTPUT_PNG.name,
        "geotiff": OUTPUT_TIFF.name if transform is not None else None,
        "nodata_mask": OUTPUT_MASK.name,
        "width": int(rgb.shape[2]),
        "height": int(rgb.shape[1]),
    })
    OUTPUT_MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def process_imagery(input_path: Path = INPUT_PATH) -> None:
    validate_input_file(input_path)
    log(f"Вход: {input_path}")

    if input_path.suffix.lower() in {".tif", ".tiff"}:
        rgb, valid, transform, crs, manifest = process_geotiff(input_path)
    else:
        rgb, valid, transform, crs, manifest = process_regular_image(input_path)

    save_outputs(rgb, valid, transform, crs, manifest)
    log(f"PNG: {OUTPUT_PNG}")
    log(f"Manifest: {OUTPUT_MANIFEST}")
    if transform is not None:
        log(f"GeoTIFF: {OUTPUT_TIFF}")
        log(f"CRS: {crs}")


def main() -> int:
    try:
        process_imagery()
        return 0
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"[imagery][ERROR] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[imagery][ERROR] Непредвиденная ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
