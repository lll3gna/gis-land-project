#!/usr/bin/env python3
"""
imagery/process_imagery.py

Подготовка спутникового снимка участка VOK-104
для последующего модуля сегментации.

Поддерживаемые форматы:
    - GeoTIFF / TIFF
    - PNG
    - JPEG / JPG

Для геопривязанных TIFF:
    - читаем через rasterio;
    - приводим CRS к EPSG:4326;
    - сохраняем временный нормализованный растр;
    - преобразуем его в PNG.

Для обычных PNG/JPEG:
    - читаем через PIL;
    - CRS отсутствует, поэтому перепроецирование не выполняется.

Результат:
    data/samples/ready_for_segmentation.png
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image

from rasterio.enums import Resampling
from rasterio.transform import array_bounds, from_bounds
from rasterio.warp import calculate_default_transform, reproject


# ============================================================================
# Конфигурация
# ============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Входной файл можно переопределить через переменную окружения.
DEFAULT_INPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "samples"
    / "vok104_imagery.tif"
)

INPUT_PATH = Path(
    os.getenv(
        "IMAGERY_INPUT_PATH",
        str(DEFAULT_INPUT_PATH),
    )
)

# Итоговый файл для модуля сегментации.
OUTPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "samples"
    / "ready_for_segmentation.png"
)

# Единая система координат проекта.
TARGET_CRS = "EPSG:4326"

# Максимальный размер стороны изображения.
#
# Если снимок больше, он будет уменьшен пропорционально.
# Это позволяет не передавать в сегментацию огромные изображения.
MAX_IMAGE_SIZE = int(
    os.getenv("IMAGERY_MAX_SIZE", "2048")
)


# ============================================================================
# Логирование
# ============================================================================

def log(message: str) -> None:
    """Выводит понятное сообщение о текущем этапе обработки."""
    print(f"[imagery] {message}")


# ============================================================================
# Проверка входного файла
# ============================================================================

def validate_input_file(path: Path) -> None:
    """Проверяет наличие и тип входного файла."""

    if not path.exists():
        raise FileNotFoundError(
            f"Входной файл не найден: {path}"
        )

    if not path.is_file():
        raise FileNotFoundError(
            f"Указанный путь не является файлом: {path}"
        )

    supported_extensions = {
        ".tif",
        ".tiff",
        ".png",
        ".jpg",
        ".jpeg",
    }

    if path.suffix.lower() not in supported_extensions:
        raise ValueError(
            f"Неподдерживаемый формат файла: {path.suffix}. "
            f"Поддерживаются: {', '.join(sorted(supported_extensions))}"
        )


# ============================================================================
# Работа с GeoTIFF
# ============================================================================

def read_geotiff(path: Path) -> Image.Image:
    """
    Читает GeoTIFF и, если необходимо, перепроецирует его в EPSG:4326.

    Возвращает обычный PIL.Image, который дальше используется
    одинаково для TIFF/PNG/JPEG.
    """

    log(f"Открытие геопривязанного растра: {path}")

    try:
        with rasterio.open(path) as src:

            if src.crs is None:
                raise ValueError(
                    "У GeoTIFF отсутствует система координат (CRS). "
                    "Невозможно выполнить автоматическое перепроецирование."
                )

            log(f"Исходная CRS: {src.crs}")
            log(f"Размер: {src.width} x {src.height}")
            log(f"Количество каналов: {src.count}")

            # ----------------------------------------------------------------
            # Определяем преобразование к EPSG:4326.
            # ----------------------------------------------------------------

            transform, width, height = calculate_default_transform(
                src.crs,
                TARGET_CRS,
                src.width,
                src.height,
                *src.bounds,
            )

            log(
                f"Новый размер после перепроецирования: "
                f"{width} x {height}"
            )

            # ----------------------------------------------------------------
            # Определяем количество каналов.
            #
            # Для RGB используем первые три канала.
            # Для одноканального снимка создаем grayscale.
            # ----------------------------------------------------------------

            if src.count == 1:
                output_channels = 1
            else:
                output_channels = min(src.count, 3)

            destination = np.zeros(
                (output_channels, height, width),
                dtype=src.dtypes[0],
            )

            # ----------------------------------------------------------------
            # Перепроецирование каждого канала.
            # ----------------------------------------------------------------

            for band_index in range(output_channels):
                reproject(
                    source=rasterio.band(
                        src,
                        band_index + 1,
                    ),
                    destination=destination[band_index],
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=TARGET_CRS,
                    resampling=Resampling.bilinear,
                )

    except rasterio.errors.RasterioIOError as exc:
        raise ValueError(
            f"Не удалось прочитать GeoTIFF: {exc}"
        ) from exc

    # ------------------------------------------------------------------------
    # Преобразуем NumPy-массив в PIL Image.
    # ------------------------------------------------------------------------

    if output_channels == 1:
        image_array = destination[0]
        image_array = normalize_to_uint8(image_array)

        return Image.fromarray(
            image_array,
            mode="L",
        )

    # rasterio хранит RGB как:
    #
    #   channels x height x width
    #
    # PIL ожидает:
    #
    #   height x width x channels
    #
    image_array = np.transpose(
        destination,
        (1, 2, 0),
    )

    image_array = normalize_to_uint8(image_array)

    return Image.fromarray(
        image_array,
        mode="RGB",
    )


# ============================================================================
# Работа с обычными изображениями
# ============================================================================

def read_regular_image(path: Path) -> Image.Image:
    """
    Читает PNG/JPEG через PIL.

    У обычных изображений нет геопривязки, поэтому CRS к ним
    не применяется.
    """

    log(f"Открытие обычного изображения: {path}")

    try:
        with Image.open(path) as image:
            # Приводим все изображения к RGB.
            #
            # Это важно, чтобы сегментационный модуль всегда получал
            # одинаковое количество каналов.
            image = image.convert("RGB")
            return image.copy()

    except (OSError, ValueError) as exc:
        raise ValueError(
            f"Не удалось прочитать изображение: {exc}"
        ) from exc


# ============================================================================
# Нормализация значений
# ============================================================================

def normalize_to_uint8(
    array: np.ndarray,
) -> np.ndarray:
    """
    Приводит значения изображения к диапазону 0..255.

    Это особенно важно для спутниковых TIFF, где значения пикселей
    могут быть uint16, int16 или float.
    """

    array = np.asarray(array)

    if array.dtype == np.uint8:
        return array

    array = array.astype(np.float32)

    # Убираем NaN и бесконечности.
    array = np.nan_to_num(
        array,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )

    min_value = float(array.min())
    max_value = float(array.max())

    if max_value <= min_value:
        return np.zeros(
            array.shape,
            dtype=np.uint8,
        )

    # Линейное масштабирование:
    #
    # исходный диапазон -> 0..255
    array = (
        (array - min_value)
        / (max_value - min_value)
        * 255.0
    )

    return np.clip(
        array,
        0,
        255,
    ).astype(np.uint8)


# ============================================================================
# Изменение размера
# ============================================================================

def resize_for_segmentation(
    image: Image.Image,
    max_size: int = MAX_IMAGE_SIZE,
) -> Image.Image:
    """
    Пропорционально уменьшает изображение, если оно слишком большое.

    Если изображение уже достаточно маленькое — оставляем исходный размер.
    """

    width, height = image.size

    log(
        f"Исходный размер изображения: "
        f"{width} x {height}"
    )

    largest_side = max(width, height)

    if largest_side <= max_size:
        log(
            f"Изображение уже соответствует ограничению "
            f"{max_size}px."
        )
        return image

    scale = max_size / largest_side

    new_width = max(
        1,
        round(width * scale),
    )

    new_height = max(
        1,
        round(height * scale),
    )

    log(
        f"Изменение размера: "
        f"{width} x {height} -> "
        f"{new_width} x {new_height}"
    )

    return image.resize(
        (new_width, new_height),
        Image.Resampling.LANCZOS,
    )


# ============================================================================
# Сохранение
# ============================================================================

def save_prepared_image(
    image: Image.Image,
    output_path: Path,
) -> None:
    """Сохраняет подготовленный снимок в PNG."""

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    log(f"Сохранение результата: {output_path}")

    try:
        image.save(
            output_path,
            format="PNG",
        )
    except OSError as exc:
        raise OSError(
            f"Не удалось сохранить результат: {exc}"
        ) from exc

    log("PNG успешно сохранен.")


# ============================================================================
# Основной pipeline
# ============================================================================

def process_imagery(
    input_path: Path,
    output_path: Path,
) -> None:
    """
    Полный pipeline подготовки спутникового снимка:

        1. Проверка файла.
        2. Определение формата.
        3. Чтение.
        4. Перепроецирование GeoTIFF -> EPSG:4326.
        5. Приведение каналов.
        6. Изменение размера.
        7. Сохранение PNG.
    """

    log("==========================================")
    log("Начало обработки спутникового снимка VOK-104")
    log("==========================================")

    # ------------------------------------------------------------------------
    # Этап 1. Проверка файла.
    # ------------------------------------------------------------------------

    log("Этап 1/5: проверка входного файла")
    validate_input_file(input_path)

    # ------------------------------------------------------------------------
    # Этап 2. Чтение.
    # ------------------------------------------------------------------------

    log("Этап 2/5: чтение изображения")

    extension = input_path.suffix.lower()

    if extension in {".tif", ".tiff"}:
        image = read_geotiff(input_path)

        log(
            f"Геопривязанный TIFF приведен к {TARGET_CRS}"
        )

    else:
        image = read_regular_image(input_path)

        log(
            "Обычное изображение не содержит геопривязки; "
            "перепроецирование не требуется."
        )

    # ------------------------------------------------------------------------
    # Этап 3. Нормализация изображения.
    # ------------------------------------------------------------------------

    log("Этап 3/5: нормализация изображения")

    # Гарантируем RGB на выходе.
    if image.mode != "RGB":
        image = image.convert("RGB")

    log(
        f"Формат изображения после нормализации: "
        f"{image.mode}"
    )

    # ------------------------------------------------------------------------
    # Этап 4. Изменение размера.
    # ------------------------------------------------------------------------

    log("Этап 4/5: подготовка размера для сегментации")

    image = resize_for_segmentation(image)

    # ------------------------------------------------------------------------
    # Этап 5. Сохранение.
    # ------------------------------------------------------------------------

    log("Этап 5/5: сохранение подготовленного изображения")

    save_prepared_image(
        image,
        output_path,
    )

    log("==========================================")
    log("Обработка завершена успешно")
    log(f"Результат: {output_path}")
    log(f"Размер: {image.width} x {image.height}")
    log("Готово для передачи в модуль сегментации.")
    log("==========================================")


# ============================================================================
# CLI
# ============================================================================

def main() -> int:
    """Точка входа скрипта."""

    try:
        process_imagery(
            input_path=INPUT_PATH,
            output_path=OUTPUT_PATH,
        )

        return 0

    except FileNotFoundError as exc:
        print(
            f"[imagery][ERROR] {exc}",
            file=sys.stderr,
        )
        return 1

    except ValueError as exc:
        print(
            f"[imagery][ERROR] {exc}",
            file=sys.stderr,
        )
        return 1

    except Exception as exc:
        print(
            f"[imagery][ERROR] Непредвиденная ошибка: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
