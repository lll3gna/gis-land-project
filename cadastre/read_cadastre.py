#!/usr/bin/env python3
"""Read, validate and normalize the VOK-104 cadastral parcel.

The module returns a stable project contract and can persist it as JSON.
Exchange CRS is WGS 84 (EPSG:4326); metric area checks use EPSG:6933 unless
overridden with CADASTRE_AREA_CRS.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping
from shapely.geometry.base import BaseGeometry
from shapely.validation import make_valid

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_PATH = PROJECT_ROOT / "data" / "samples" / "vok104_boundary.geojson"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "samples" / "vok104_cadastre.json"
TARGET_CRS = "EPSG:4326"
AREA_CRS = os.getenv("CADASTRE_AREA_CRS", "EPSG:6933")
CADASTRAL_NUMBER = os.getenv("CADASTRAL_NUMBER")
INPUT_PATH = Path(os.getenv("CADASTRE_INPUT_PATH", str(DEFAULT_INPUT_PATH)))
OUTPUT_PATH = Path(os.getenv("CADASTRE_OUTPUT_PATH", str(DEFAULT_OUTPUT_PATH)))
AREA_TOLERANCE = float(os.getenv("CADASTRE_AREA_TOLERANCE", "0.05"))


def find_attribute(row: Any, names: tuple[str, ...]) -> Any:
    """Find a non-empty attribute using exact and case-insensitive aliases."""
    columns = {str(c).strip().lower(): c for c in row.index}
    for name in names:
        actual = name if name in row.index else columns.get(name.lower())
        if actual is None:
            continue
        value = row[actual]
        if value is None:
            continue
        try:
            if value != value:
                continue
        except Exception:
            pass
        if str(value).strip():
            return value
    return None


def normalize_geometry(geometry: BaseGeometry) -> Polygon | MultiPolygon:
    """Repair a geometry and return only Polygon/MultiPolygon."""
    if geometry is None or geometry.is_empty:
        raise ValueError("Геометрия участка отсутствует или пустая.")

    if not geometry.is_valid:
        geometry = make_valid(geometry)

    if isinstance(geometry, Polygon):
        return geometry
    if isinstance(geometry, MultiPolygon):
        return geometry
    if isinstance(geometry, GeometryCollection):
        polygons = [g for g in geometry.geoms if isinstance(g, Polygon)]
        if not polygons:
            raise ValueError("GeometryCollection не содержит Polygon.")
        return MultiPolygon(polygons)

    raise ValueError(
        f"Неподдерживаемый тип геометрии: {geometry.geom_type}. "
        "Ожидался Polygon или MultiPolygon."
    )


def parse_area_m2(row: Any) -> float:
    """Read area and convert supported units to square metres."""
    value = find_attribute(
        row,
        ("area_m2", "area_sq_m", "areaSqM", "площадь_м2", "площадь_м²"),
    )
    unit = find_attribute(row, ("area_unit", "area_units", "единица_площади"))

    if value is None:
        value = find_attribute(row, ("area", "square", "площадь"))
        if value is not None and unit is None:
            raise ValueError(
                "Найдено поле area/площадь без area_unit. "
                "Укажите единицы явно или используйте area_m2."
            )

    if value is None:
        raise ValueError("Не найдена площадь участка.")

    try:
        area = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Некорректное значение площади: {value!r}") from exc

    unit = (str(unit).strip().lower() if unit is not None else "m2")
    factors = {
        "m2": 1.0, "м2": 1.0, "м²": 1.0, "sqm": 1.0,
        "ha": 10000.0, "га": 10000.0,
    }
    if unit not in factors:
        raise ValueError(f"Неподдерживаемая единица площади: {unit!r}")
    area_m2 = area * factors[unit]
    if area_m2 < 0:
        raise ValueError("Площадь участка не может быть отрицательной.")
    return area_m2


def select_feature(gdf: gpd.GeoDataFrame) -> Any:
    """Select exactly one feature, optionally by cadastral number."""
    if len(gdf) == 1:
        return gdf.iloc[0]

    if not CADASTRAL_NUMBER:
        raise ValueError(
            f"Файл содержит {len(gdf)} объектов. "
            "Задайте CADASTRAL_NUMBER для однозначного выбора участка."
        )

    candidates = []
    aliases = (
        "cadastral_number", "cadastralNumber", "cad_num", "cadnum",
        "cadastral_id", "cadastralId", "кадастровый_номер", "кадастровый номер",
    )
    for _, row in gdf.iterrows():
        value = find_attribute(row, aliases)
        if value is not None and str(value).strip() == CADASTRAL_NUMBER:
            candidates.append(row)

    if len(candidates) != 1:
        raise ValueError(
            f"По CADASTRAL_NUMBER={CADASTRAL_NUMBER!r} найдено "
            f"{len(candidates)} объектов, ожидался ровно один."
        )
    return candidates[0]


def read_cadastre(input_path: Path = INPUT_PATH) -> dict[str, Any]:
    """Load the parcel and return the documented VOK-104 contract."""
    if not input_path.is_file():
        raise FileNotFoundError(f"Файл кадастровых данных не найден: {input_path}")

    try:
        gdf = gpd.read_file(input_path)
    except Exception as exc:
        raise ValueError(f"Не удалось прочитать {input_path}: {exc}") from exc

    if gdf.empty:
        raise ValueError("Кадастровый файл не содержит объектов.")
    if "geometry" not in gdf.columns:
        raise ValueError("В кадастровом файле отсутствует geometry.")
    if gdf.crs is None:
        raise ValueError(
            "У исходных кадастровых данных не указана CRS; "
            "автоматическое определение небезопасно."
        )

    gdf = gdf.to_crs(TARGET_CRS)
    row = select_feature(gdf)

    cadastral_number = find_attribute(
        row,
        (
            "cadastral_number", "cadastralNumber", "cad_num", "cadnum",
            "cadastral_id", "cadastralId", "кадастровый_номер", "кадастровый номер",
        ),
    )
    if cadastral_number is None:
        raise ValueError("Не найден кадастровый номер участка.")
    cadastral_number = str(cadastral_number).strip()
    if not cadastral_number:
        raise ValueError("Кадастровый номер пуст.")

    area_m2 = parse_area_m2(row)
    geometry = normalize_geometry(row.geometry)

    # Area is calculated in a metric equal-area CRS only for validation.
    metric_geometry = gpd.GeoSeries([geometry], crs=TARGET_CRS).to_crs(AREA_CRS).iloc[0]
    geometry_area_m2 = float(metric_geometry.area)
    if geometry_area_m2 <= 0:
        raise ValueError("Площадь геометрии должна быть положительной.")

    relative_error = abs(geometry_area_m2 - area_m2) / area_m2 if area_m2 else 0.0
    if relative_error > AREA_TOLERANCE:
        raise ValueError(
            f"Площадь атрибута ({area_m2:.2f} м²) не совпадает с геометрией "
            f"({geometry_area_m2:.2f} м²): ошибка {relative_error:.1%}."
        )

    land_category = find_attribute(
        row, ("land_category", "category", "категория_земель", "категория земель")
    )
    permitted_use = find_attribute(
        row,
        ("permitted_use", "land_use", "разрешенное_использование",
         "разрешённое_использование", "вид_разрешенного_использования"),
    )

    return {
        "schema_version": "1.0",
        "cadastral_number": cadastral_number,
        "area_m2": round(area_m2, 3),
        "geometry_area_m2": round(geometry_area_m2, 3),
        "area_relative_error": round(relative_error, 6),
        "land_category": str(land_category).strip() if land_category is not None else None,
        "permitted_use": str(permitted_use).strip() if permitted_use is not None else None,
        "geometry": mapping(geometry),
        "crs": TARGET_CRS,
        "area_validation_crs": AREA_CRS,
    }


def save_cadastre(data: dict[str, Any], output_path: Path = OUTPUT_PATH) -> None:
    """Persist the normalized contract as UTF-8 JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    try:
        data = read_cadastre(INPUT_PATH)
        save_cadastre(data, OUTPUT_PATH)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[cadastre][ERROR] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[cadastre][ERROR] Непредвиденная ошибка: {exc}", file=sys.stderr)
        return 1

    print("Кадастровые данные VOK-104 подготовлены.")
    print(f"Кадастровый номер: {data['cadastral_number']}")
    print(f"Площадь: {data['area_m2']} м²")
    print(f"CRS обмена: {data['crs']}")
    print(f"Результат: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
