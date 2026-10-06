# Единая схема данных VOK-104

Версия контракта: **1.0**

## 1. Кадастровый объект

Нормализованный файл: `data/samples/vok104_cadastre.json`.

Обязательные поля:

| Поле | Тип | Описание |
|---|---|---|
| `schema_version` | string | Версия контракта |
| `cadastral_number` | string | Кадастровый номер |
| `area_m2` | number | Заявленная площадь в м² |
| `geometry_area_m2` | number | Площадь геометрии, рассчитанная в метрической CRS |
| `area_relative_error` | number | Относительная ошибка сравнения площадей |
| `geometry` | GeoJSON Geometry | Только Polygon или MultiPolygon |
| `crs` | string | Всегда EPSG:4326 для обмена |
| `area_validation_crs` | string | Метрическая CRS для проверки площади |
| `land_category` | string/null | Категория земель |
| `permitted_use` | string/null | Разрешённое использование |

Геометрия передаётся в WGS 84 / EPSG:4326 только для обмена. Площади не вычисляются в градусах.

## 2. Снимок

Канонический результат GeoTIFF хранит:

- CRS;
- affine transform;
- размеры;
- 3 uint8 RGB-канала;
- nodata = 0.

PNG предназначен для сегментации. Его геопривязка дублируется в `.pgw` и manifest JSON.

Формат имени:

`YYYY-MM-DD_vok104_cadastre.png`

Для GeoTIFF используется тот же stem с расширением `.tif`.

## 3. Manifest снимка

Пример обязательных полей:

```json
{
  "schema_version": "1.0",
  "source_crs": "EPSG:32637",
  "working_crs": "EPSG:6933",
  "exchange_crs": "EPSG:4326",
  "crs": "EPSG:6933",
  "transform": [1, 0, 0, 0, -1, 0],
  "bands": [1, 2, 3],
  "normalization": {
    "method": "percentile_clip",
    "low": 2,
    "high": 98
  },
  "georeferenced": true
}
```

Фактический transform всегда берётся из результата обработки и не должен заменяться примером выше.

## 4. Nodata

Зоны без данных после перепроецирования не считаются реальными чёрными пикселями. Они имеют отдельную маску `*_nodata_mask.png`; для GeoTIFF также записывается `nodata=0`.

## 5. Каналы

Порядок каналов не угадывается по первым трём band'ам. Для GeoTIFF:

1. используются ColorInterp RED/GREEN/BLUE, если теги присутствуют;
2. иначе необходимо явно задать `IMAGERY_BANDS=R,G,B`.

Пример для B,G,R исходного порядка: `IMAGERY_BANDS=3,2,1`.

## 6. Результат сегментации

Модуль сегментации должен принимать PNG + manifest и возвращать GeoJSON FeatureCollection:

```json
{
  "schema_version": "1.0",
  "source_image": "YYYY-MM-DD_vok104_cadastre.png",
  "source_crs": "EPSG:6933",
  "features": [
    {
      "type": "Feature",
      "properties": {
        "class": "building",
        "confidence": 0.0
      },
      "geometry": {
        "type": "Polygon",
        "coordinates": []
      }
    }
  ]
}
```

Допустимые классы: `building`, `vegetation`, `water_body`, `road`.

Координаты результата должны быть возвращены в CRS, указанной в `source_crs`, чтобы следующий модуль мог корректно выполнить метрические операции и экспорт.
