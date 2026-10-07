# GIS Land Project — участок VOK-104

Репозиторий для обработки кадастровых данных и снимков участка VOK-104. Зона Влада отвечает за входные данные и подготовку стабильного контракта для модулей сегментации и экспорта.

## Структура

- `cadastre/` — чтение, валидация и нормализация кадастровых данных.
- `imagery/` — подготовка GeoTIFF/PNG/JPEG с сохранением геопривязки там, где она есть.
- `segmentation/` — модули Ксюши; не изменяются этим этапом.
- `export/` — модули Ксюши; не изменяются этим этапом.
- `data/samples/` — маленькие синтетические данные для запуска и тестов.
- `docs/data-schema.md` — единый контракт между модулями.
- `prompts/gis_prompts.md` — промпты, использованные для разработки.

## Быстрый запуск

Требуется Python 3.10+.

```bash
git clone https://github.com/lll3gna/gis-land-project.git
cd gis-land-project
python -m venv .venv
source .venv/bin/activate
# Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python cadastre/read_cadastre.py
python imagery/process_imagery.py
python -m pytest -q
```

После запуска появятся нормализованный кадастровый JSON и датированные результаты снимка в `data/samples/`.

## Тестовые данные

Синтетический участок и снимок в `data/samples/` описывают одно место и пересоздаются командой `python tools/make_sample_data.py`. Подробности: [data/samples/README.md](data/samples/README.md).

## Источники данных

Сравнение НСПД, ЕГРН, API-агрегаторов, Esri, Яндекс, Google, Mapbox, Sentinel-2 и Геопортала Роскосмоса с рекомендацией для MVP: [docs/data-sources-comparison.md](docs/data-sources-comparison.md).

Проверка программного доступа к НСПД (итог: открытого канала нет, нужен запасной сценарий): [docs/nspd-spike.md](docs/nspd-spike.md).

## Переменные окружения

Кадастр:

- `CADASTRE_INPUT_PATH`
- `CADASTRE_OUTPUT_PATH`
- `CADASTRAL_NUMBER` — нужен только если входной файл содержит несколько объектов.
- `CADASTRE_AREA_CRS` — равновеликая CRS для проверки площади, по умолчанию EPSG:6933 (сохраняет площади, но искажает форму, поэтому используется только для площади).
- `CADASTRE_AREA_TOLERANCE` — относительная допустимая ошибка, по умолчанию 5%.

Снимок:

- `IMAGERY_INPUT_PATH`
- `IMAGERY_OUTPUT_DIR`
- `IMAGERY_DATE` — **дата съёмки** в имени результата, YYYY-MM-DD. Если не задана, подставляется дата обработки, а manifest помечает это полем `image_date_source: "processing"`.
- `IMAGERY_WORKING_CRS` — метрическая равноугольная CRS для снимка, по умолчанию EPSG:32637 (WGS 84 / UTM 37N, покрывает 36–42° в.д.). Для участков вне этой зоны задайте свою UTM-зону или местную МСК.
- `IMAGERY_BANDS` — явное соответствие R,G,B, например `3,2,1`; если не задано, используются теги ColorInterp GeoTIFF.
- `IMAGERY_LOW_PERCENTILE`, `IMAGERY_HIGH_PERCENTILE` — по умолчанию 2 и 98.
- `IMAGERY_MAX_SIZE` — максимальная сторона PNG, по умолчанию 2048.

## Контракт результатов imagery

Для GeoTIFF создаются:

- `YYYY-MM-DD_vok104_cadastre.png` — изображение для сегментации;
- `YYYY-MM-DD_vok104_cadastre.tif` — тот же результат с CRS/transform;
- `YYYY-MM-DD_vok104_cadastre.pgw` — world file для PNG;
- `YYYY-MM-DD_vok104_cadastre.prj` — система координат для PNG (world file её не содержит);
- `YYYY-MM-DD_vok104_cadastre_nodata_mask.png` — маска зон без данных;
- `YYYY-MM-DD_vok104_cadastre.json` — manifest с CRS, transform, каналами и параметрами нормализации.

PNG/JPEG без исходной геопривязки не получают искусственную CRS: manifest явно помечает их как `georeferenced: false`.

## Безопасность

Секреты не хранятся в репозитории. Локальные `.env` и виртуальные окружения игнорируются через `.gitignore`.
