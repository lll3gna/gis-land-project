#!/usr/bin/env python3
"""
cadastre/read_cadastre.py

Загрузка и нормализация кадастровых границ участка VOK-104.

Источник:
    data/samples/vok104_boundary.geojson

Результат:
    - кадастровый номер;
    - площадь участка;
    - геометрия Polygon / MultiPolygon;
    - геометрия в WGS 84 (EPSG:4326).

Зависимости:
    geopandas
    shapely
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry


# ---------------------------------------------------------------------------
# Пути
# ---------------------------------------------------------------------------

# По умолчанию ожидаем стандартную структуру проекта:
# project/
# ├── cadastre/
# │   └── read_cadastre.py
# ├── data/
# │   └── samples/
# │       └── vok104_boundary.geojson
# └── docs/
#     └── data-schema.md
#
# При необходимости путь можно переопределить через переменную окружения.
DEFAULT_INPUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "samples"
    / "vok104_boundary.geojson"
)

INPUT_PATH = Path(
    os.getenv("CADASTRE_INPUT_PATH", str(DEFAULT_INPUT_PATH))
)

TARGET_CRS = "EPSG:4326"


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def find_attribute(
    row: Any,
    possible_names: tuple[str, ...],
) -> Any:
    """
    Находит значение атрибута по списку допустимых названий.

    Это позволяет работать с GeoJSON, где одно и то же поле может называться,
    например, cadastral_number, cad_num или кадастровый_номер.
    """

    # Сначала проверяем точное совпадение имени.
    for name in possible_names:
        if name in row.index:
            value = row[name]

            if value is not None:
                try:
                    if not (value != value):  # NaN
                        return value
                except Exception:
                    return value

    # Затем проверяем регистр независимо.
    normalized = {
        str(column).strip().lower(): column
        for column in row.index
    }

    for name in possible_names:
        actual_name = normalized.get(name.lower())

        if actual_name is not None:
            value = row[actual_name]

            if value is not None:
                try:
                    if not (value != value):
                        return value
                except Exception:
                    return value

    return None


def normalize_geometry(
    geometry: BaseGeometry,
) -> Polygon | MultiPolygon:
    """
    Проверяет и нормализует геометрию участка.

    На выходе допустимы только:
        Polygon
        MultiPolygon

    Для последующей передачи в модуль сегментации.
    """

    if geometry is None or geometry.is_empty:
        raise ValueError("Геометрия участка отсутствует или пустая.")

    # Если геометрия повреждена, пытаемся исправить её.
    if not geometry.is_valid:
        geometry = geometry.buffer(0)

    if geometry.is_empty or not geometry.is_valid:
        raise ValueError(
            "Не удалось исправить поврежденную геометрию участка."
        )

    if isinstance(geometry, Polygon):
        return geometry

    if isinstance(geometry, MultiPolygon):
        return geometry

    # Некоторые источники могут отдавать GeometryCollection.
    # Из него извлекаем только Polygon-компоненты.
    if geometry.geom_type == "GeometryCollection":
        polygons = [
            geom
            for geom in geometry.geoms
            if isinstance(geom, Polygon)
        ]

        if not polygons:
            raise ValueError(
                "GeometryCollection не содержит Polygon."
            )

        return MultiPolygon(polygons)

    raise ValueError(
        f"Неподдерживаемый тип геометрии: {geometry.geom_type}. "
        "Ожидался Polygon или MultiPolygon."
    )


def geometry_to_geojson(
    geometry: Polygon | MultiPolygon,
) -> dict[str, Any]:
    """
    Преобразует Shapely Polygon/MultiPolygon в GeoJSON geometry.
    """

    return json.loads(
        gpd.GeoSeries([geometry], crs=TARGET_CRS)
        .to_json()
    )["features"][0]["geometry"]


# ---------------------------------------------------------------------------
# Основная функция
# ---------------------------------------------------------------------------

def read_cadastre(
    input_path: Path = INPUT_PATH,
) -> dict[str, Any]:
    """
    Загружает кадастровый участок и приводит его к единой структуре данных.

    Возвращает:

    {
        "cadastral_number": "...",
        "area_m2": 1234.56,
        "geometry": {
            "type": "Polygon",
            "coordinates": [...]
        },
        "crs": "EPSG:4326"
    }
    """

    # -----------------------------------------------------------------------
    # 1. Проверяем наличие файла
    # -----------------------------------------------------------------------

    if not input_path.exists():
        raise FileNotFoundError(
            f"Файл кадастровых данных не найден: {input_path}"
        )

    if not input_path.is_file():
        raise FileNotFoundError(
            f"Указанный путь не является файлом: {input_path}"
        )

    # -----------------------------------------------------------------------
    # 2. Загружаем GeoJSON через GeoPandas
    # -----------------------------------------------------------------------

    try:
        gdf = gpd.read_file(input_path)
    except Exception as exc:
        raise ValueError(
            f"Не удалось прочитать кадастровый файл "
            f"{input_path}: {exc}"
        ) from exc

    if gdf.empty:
        raise ValueError(
            f"Файл {input_path} не содержит объектов."
        )

    if "geometry" not in gdf.columns:
        raise ValueError(
            "В кадастровом файле отсутствует поле geometry."
        )

    # -----------------------------------------------------------------------
    # 3. Определяем систему координат
    # -----------------------------------------------------------------------

    if gdf.crs is None:
        raise ValueError(
            "У исходных кадастровых данных не указана система координат. "
            "Автоматически определить CRS безопасно невозможно."
        )

    # Автоматически приводим координаты к WGS 84 / EPSG:4326.
    if gdf.crs.to_epsg() != 4326:
        try:
            gdf = gdf.to_crs(TARGET_CRS)
        except Exception as exc:
            raise ValueError(
                f"Не удалось преобразовать CRS "
                f"{gdf.crs} -> {TARGET_CRS}: {exc}"
            ) from exc

    # -----------------------------------------------------------------------
    # 4. Берем участок VOK-104
    # -----------------------------------------------------------------------
    #
    # В большинстве случаев GeoJSON будет содержать один объект.
    # Если объектов несколько, используем первый и явно сообщаем об этом.
    # При необходимости здесь можно добавить фильтрацию по кадастровому
    # номеру.

    row = gdf.iloc[0]

    if len(gdf) > 1:
        print(
            f"Предупреждение: файл содержит {len(gdf)} объектов. "
            "Для VOK-104 используется первый объект."
        )

    # -----------------------------------------------------------------------
    # 5. Извлекаем кадастровый номер
    # -----------------------------------------------------------------------

    cadastral_number = find_attribute(
        row,
        (
            "cadastral_number",
            "cadastralNumber",
            "cad_num",
            "cadnum",
            "cadastral_id",
            "cadastralId",
            "кадастровый_номер",
            "кадастровый номер",
        ),
    )

    if cadastral_number is None:
        raise ValueError(
            "Не найден кадастровый номер участка. "
            "Ожидался атрибут cadastral_number."
        )

    cadastral_number = str(cadastral_number).strip()

    if not cadastral_number:
        raise ValueError(
            "Кадастровый номер участка пуст."
        )

    # -----------------------------------------------------------------------
    # 6. Извлекаем площадь
    # -----------------------------------------------------------------------

    area = find_attribute(
        row,
        (
            "area_m2",
            "area",
            "area_sq_m",
            "areaSqM",
            "square",
            "площадь",
            "площадь_м2",
            "площадь_м²",
        ),
    )

    if area is None:
        raise ValueError(
            "Не найдена площадь участка. "
            "Ожидался атрибут area_m2 или area."
        )

    try:
        area_m2 = float(area)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Некорректное значение площади: {area!r}"
        ) from exc

    if area_m2 < 0:
        raise ValueError(
            f"Площадь участка не может быть отрицательной: {area_m2}"
        )

    # -----------------------------------------------------------------------
    # 7. Нормализуем геометрию
    # -----------------------------------------------------------------------

    geometry = normalize_geometry(row.geometry)

    # -----------------------------------------------------------------------
    # 8. Формируем единый объект данных проекта
    # -----------------------------------------------------------------------

    result = {
        "cadastral_number": cadastral_number,
        "area_m2": area_m2,
        "geometry": geometry_to_geojson(geometry),
        "crs": TARGET_CRS,
    }

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    """
    Точка входа при запуске:

        python cadastre/read_cadastre.py
    """

    print("Загрузка кадастровых данных VOK-104...")
    print(f"Файл: {INPUT_PATH}")

    try:
        cadastre = read_cadastre(INPUT_PATH)

    except FileNotFoundError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    except ValueError as exc:
        print(f"Ошибка данных: {exc}", file=sys.stderr)
        return 1

    except Exception as exc:
        # Защита от неожиданных ошибок библиотек/файловой системы.
        print(
            f"Непредвиденная ошибка при обработке кадастровых данных: "
            f"{exc}",
            file=sys.stderr,
        )
        return 1

    # -----------------------------------------------------------------------
    # Вывод ключевых атрибутов
    # -----------------------------------------------------------------------

    print()
    print("Кадастровый участок VOK-104")
    print("-" * 40)
    print(f"Кадастровый номер: {cadastre['cadastral_number']}")
    print(f"Площадь, м²:       {cadastre['area_m2']}")
    print(f"CRS:               {cadastre['crs']}")
    print(
        f"Тип геометрии:     {cadastre['geometry']['type']}"
    )
    print("-" * 40)

    # Геометрия подготовлена в GeoJSON-виде для передачи
    # непосредственно в следующий модуль проекта.
    print("Геометрия подготовлена для модуля сегментации.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
