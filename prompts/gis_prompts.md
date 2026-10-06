# Промпты для Codex

Все промпты ниже используют терминологию и контракт из `docs/data-schema.md`.

## 1. Кадастр

> Изучи `docs/data-schema.md`. Напиши Python-скрипт `cadastre/read_cadastre.py` для VOK-104: прочитай GeoJSON через GeoPandas, однозначно выбери участок по кадастровому номеру, если объектов несколько, приведи геометрию к Polygon/MultiPolygon, исправляй невалидную геометрию через make_valid, проверь площадь в метрической CRS и единицы, извлеки кадастровый номер, площадь, категорию земель и разрешённое использование. Результат сохрани в `vok104_cadastre.json` строго по схеме версии 1.0, геометрию для обмена храни в EPSG:4326. Не меняй модули segmentation/export.

## 2. Imagery

> Изучи `docs/data-schema.md`. Напиши `imagery/process_imagery.py` для VOK-104. Поддержи GeoTIFF/TIFF и PNG/JPEG. Для GeoTIFF сохрани CRS и transform, перепроецируй снимок в настраиваемую метрическую рабочую CRS, обработай nodata, не угадывай порядок каналов: используй ColorInterp либо требуй `IMAGERY_BANDS=R,G,B`. Для 16-bit/float используй robust percentile clipping вместо min-max. После resize скорректируй affine transform. Сохрани датированные PNG, геопривязанный GeoTIFF, world file, nodata mask и manifest JSON по схеме 1.0. Не создавай искусственную геопривязку для обычного PNG/JPEG.

## 3. Тесты

> Изучи `docs/data-schema.md`. Добавь минимальные pytest-тесты, которые проверяют: чтение sample GeoJSON, проверку площади и JSON-контракт; обработку sample GeoTIFF, наличие CRS/transform в GeoTIFF и manifest; устойчивость percentile normalization к выбросам. Тесты должны запускаться после `pip install -r requirements.txt`.

## 4. Общее правило

Перед изменением интерфейсов сверяйся с `docs/data-schema.md`. Не добавляй секреты, токены или ключи в код/репозиторий.
