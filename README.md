# Генератор PDF-чеков

Консольный скрипт, который берёт данные из CSV или JSON, подставляет их в HTML-шаблон и собирает PDF через WeasyPrint. После генерации файл открывается в системной программе просмотра.

Работает на **Windows** и **macOS**. Кириллица выводится шрифтом DejaVu Sans.

## Что делает скрипт

1. Находит CSV/JSON в папке `data/` и HTML-шаблоны в `templates/`.
2. Показывает нумерованные списки и просит выбрать файл данных и шаблон.
3. Выводит доступные чеки по полю `invoice_id`.
4. Генерирует PDF в папку `output/` и открывает его.

## Структура проекта

```
ПДФ_чек/
├── generate_pdf.py      # основной скрипт
├── requirements.txt
├── data/                # исходные данные (CSV, JSON)
│   ├── invoices.csv
│   └── invoices.json
├── templates/           # HTML-шаблоны
│   ├── receipt.html     # кассовый чек
│   └── invoice.html     # счёт
├── fonts/               # DejaVu Sans (кириллица)
└── output/              # готовые PDF
```

## Установка

Нужен Python 3.10+.

```bash
pip install -r requirements.txt
```

WeasyPrint зависит от системных библиотек **Pango/GTK**.

### Windows

Установите GTK3 Runtime, например:

```bash
winget install tschoonj.GTKForWindows
```

Или поставьте [GTK3 Runtime Installer](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases) в `C:\GTK3-Runtime`. Скрипт сам ищет DLL в типичных папках.

Альтернатива: MSYS2 и пакет `mingw-w64-ucrt-x86_64-pango`.

### macOS

```bash
brew install pango
```

## Запуск

```bash
python generate_pdf.py
```

Пример диалога:

```
  [1]  invoices.csv
  [2]  invoices.json

Выберите файл данных (1–2): 2

  [1]  invoice.html
  [2]  receipt.html

Выберите HTML-шаблон (1–2): 2

  [1]  INV-101
  [2]  INV-102
  [3]  INV-103

Выберите invoice id (1–3): 1
```

Готовый файл: `output/check_INV-101.pdf`.

## Формат данных

Скрипт ищет идентификатор чека в полях: `invoice_id`, `invoiceId`, `id`.

Полезные поля для шаблонов:

| Поле             | Описание                          |
|------------------|-----------------------------------|
| `invoice_id`     | номер чека / счёта                |
| `date`           | дата                              |
| `customer`       | покупатель                        |
| `customer_email` | email                             |
| `items`          | позиции (строка в CSV или список в JSON) |
| `amount`         | итоговая сумма                    |
| `currency`       | валюта, по умолчанию `RUB`        |
| `status`         | статус                            |

CSV читается через pandas (если установлен) или стандартный модуль `csv`. JSON — через стандартный `json`.

Пример JSON:

```json
{
  "invoice_id": "INV-101",
  "date": "2026-10-08",
  "customer": "Анна Волкова",
  "customer_email": "anna.volkova@example.com",
  "items": [
    {"name": "Кофемашина", "qty": 1, "price": 24990}
  ],
  "amount": 26980,
  "currency": "RUB",
  "status": "оплачен"
}
```

## Шаблоны

Шаблоны — обычный HTML + Jinja2. В шаблон передаются поля записи и список `items_list` с полями `name`, `qty`, `price`, `line_total`.

Чтобы добавить свой шаблон, положите `.html` файл в `templates/`. Он появится в меню при следующем запуске.

## Шрифты

Для кириллицы нужны файлы в `fonts/`:

- `DejaVuSans.ttf`
- `DejaVuSans-Bold.ttf` (желательно)

Если шрифта нет, скрипт предупредит: PDF может собраться, но русские буквы отобразятся некорректно.

## Зависимости Python

- `weasyprint` — HTML → PDF
- `jinja2` — подстановка данных в шаблон
- `pandas` — удобный разбор CSV (необязателен, есть запасной путь через `csv`)
