#!/usr/bin/env python3
"""
Генератор PDF-чеков из CSV/JSON данных и HTML-шаблонов (WeasyPrint).
Работает на Windows и macOS.
"""

from __future__ import annotations

import csv
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any


def _configure_native_libs() -> None:
    """
    Подключает системные библиотеки Pango/GTK для WeasyPrint
    (актуально для Windows и иногда для macOS/Homebrew).
    """
    system = platform.system()
    extra_dirs: list[str] = []

    if system == "Windows":
        candidates = [
            Path(r"C:\GTK3-Runtime\bin"),
            Path(r"C:\Program Files\GTK3-Runtime Win64\bin"),
            Path(r"C:\Program Files (x86)\GTK3-Runtime Win64\bin"),
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "GTK3-Runtime Win64"
            / "bin",
            Path(r"C:\msys64\ucrt64\bin"),
            Path(r"C:\msys64\mingw64\bin"),
        ]
        for path in candidates:
            if path.is_dir():
                extra_dirs.append(str(path))
                # Python 3.8+: явная регистрация каталога DLL
                if hasattr(os, "add_dll_directory"):
                    try:
                        os.add_dll_directory(str(path))
                    except OSError:
                        pass

        if extra_dirs:
            os.environ["PATH"] = os.pathsep.join(extra_dirs + [os.environ.get("PATH", "")])
            existing = os.environ.get("WEASYPRINT_DLL_DIRECTORIES", "")
            merged = os.pathsep.join(
                [d for d in extra_dirs + existing.split(os.pathsep) if d]
            )
            os.environ["WEASYPRINT_DLL_DIRECTORIES"] = merged

    elif system == "Darwin":
        # Apple Silicon / Intel Homebrew
        for lib_dir in ("/opt/homebrew/lib", "/usr/local/lib"):
            if Path(lib_dir).is_dir():
                current = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
                os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = os.pathsep.join(
                    filter(None, [lib_dir, current])
                )


_configure_native_libs()

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None

from jinja2 import Environment, FileSystemLoader, select_autoescape

try:
    from weasyprint import CSS, HTML
except OSError as exc:  # pragma: no cover
    print(
        "Не удалось загрузить WeasyPrint (нет системных библиотек Pango/GTK).\n"
        "Windows: установите GTK3 Runtime "
        "(winget install tschoonj.GTKForWindows)\n"
        "  или MSYS2 + pacman -S mingw-w64-ucrt-x86_64-pango\n"
        "macOS:   brew install pango\n"
        f"Подробности: {exc}"
    )
    sys.exit(1)

# --- пути относительно скрипта -------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = BASE_DIR / "templates"
OUTPUT_DIR = BASE_DIR / "output"
FONTS_DIR = BASE_DIR / "fonts"

INVOICE_ID_KEYS = ("invoice_id", "invoiceId", "InvoiceId", "id", "ID")


# --- утилиты консоли -----------------------------------------------------------
def print_header(title: str) -> None:
    line = "=" * 56
    print(f"\n{line}")
    print(f"  {title}")
    print(line)


def print_menu(title: str, items: list[str]) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    for i, item in enumerate(items, start=1):
        print(f"  [{i}]  {item}")


def ask_choice(prompt: str, count: int) -> int:
    """Запрашивает номер пункта меню (1..count)."""
    while True:
        raw = input(f"\n{prompt} (1–{count}): ").strip()
        if not raw.isdigit():
            print("  Введите число из списка.")
            continue
        value = int(raw)
        if 1 <= value <= count:
            return value
        print(f"  Число должно быть от 1 до {count}.")


# --- работа с файлами ----------------------------------------------------------
def list_data_files() -> list[Path]:
    if not DATA_DIR.is_dir():
        return []
    files = sorted(
        [
            p
            for p in DATA_DIR.iterdir()
            if p.is_file() and p.suffix.lower() in {".csv", ".json"}
        ],
        key=lambda p: p.name.lower(),
    )
    return files


def list_templates() -> list[Path]:
    if not TEMPLATES_DIR.is_dir():
        return []
    return sorted(
        [p for p in TEMPLATES_DIR.iterdir() if p.is_file() and p.suffix.lower() in {".html", ".htm"}],
        key=lambda p: p.name.lower(),
    )


def load_csv(path: Path) -> list[dict[str, Any]]:
    """Читает CSV через pandas (если доступен) или стандартный csv."""
    if pd is not None:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        return df.to_dict(orient="records")

    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader]


def load_json(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)

    if isinstance(data, list):
        if not all(isinstance(item, dict) for item in data):
            raise ValueError("JSON-массив должен содержать объекты.")
        return data

    if isinstance(data, dict):
        # распространённые обёртки: {"invoices": [...]} / {"data": [...]}
        for key in ("invoices", "data", "records", "items"):
            if key in data and isinstance(data[key], list):
                return data[key]
        return [data]

    raise ValueError("Ожидался JSON-объект или массив объектов.")


def load_records(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return load_csv(path)
    if suffix == ".json":
        return load_json(path)
    raise ValueError(f"Неподдерживаемый формат: {suffix}")


def get_invoice_id(record: dict[str, Any]) -> str | None:
    for key in INVOICE_ID_KEYS:
        if key in record and str(record[key]).strip():
            return str(record[key]).strip()
    return None


def index_by_invoice_id(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        inv_id = get_invoice_id(record)
        if inv_id is None:
            continue
        indexed[inv_id] = record
    return indexed


# --- подготовка данных для шаблона --------------------------------------------
def _as_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def normalize_items(record: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Приводит позиции чека к единому виду:
    [{"name", "qty", "price", "line_total"}, ...]
    """
    raw = record.get("items")
    items_list: list[dict[str, Any]] = []

    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("title") or item.get("description") or "—")
            qty = _as_number(item.get("qty", item.get("quantity", 1))) or 1
            price = _as_number(item.get("price", item.get("amount", 0))) or 0
            line_total = _as_number(item.get("line_total"))
            if line_total is None:
                line_total = qty * price
            items_list.append(
                {
                    "name": name,
                    "qty": _format_number(qty),
                    "price": _format_number(price),
                    "line_total": _format_number(line_total),
                }
            )
        return items_list

    # CSV: строка с позициями через «;»
    if isinstance(raw, str) and raw.strip():
        for part in raw.split(";"):
            part = part.strip()
            if not part:
                continue
            items_list.append(
                {
                    "name": part,
                    "qty": "—",
                    "price": "—",
                    "line_total": "—",
                }
            )
    return items_list


def _format_number(value: float) -> str:
    if value == int(value):
        return f"{int(value):,}".replace(",", " ")
    return f"{value:,.2f}".replace(",", " ")


def prepare_context(record: dict[str, Any]) -> dict[str, Any]:
    ctx = dict(record)
    amount = _as_number(record.get("amount") or record.get("total"))
    if amount is not None:
        ctx["amount"] = _format_number(amount)
    elif "amount" not in ctx:
        ctx["amount"] = "—"

    ctx.setdefault("currency", "RUB")
    ctx["items_list"] = normalize_items(record)

    # для CSV оставляем исходную строку items как fallback в шаблоне
    if not isinstance(ctx.get("items"), str):
        ctx["items"] = ""

    return ctx


# --- генерация PDF ------------------------------------------------------------
def build_font_css() -> CSS | None:
    """CSS с локальными шрифтами DejaVu Sans (кириллица)."""
    regular = FONTS_DIR / "DejaVuSans.ttf"
    bold = FONTS_DIR / "DejaVuSans-Bold.ttf"

    if not regular.is_file():
        print(
            f"\n  Предупреждение: шрифт не найден ({regular}).\n"
            "  Кириллица может отображаться некорректно. "
            "Положите DejaVuSans.ttf в папку fonts/."
        )
        return None

    faces = [
        f"""
        @font-face {{
          font-family: "DejaVu Sans";
          src: url("{regular.as_uri()}");
          font-weight: normal;
          font-style: normal;
        }}
        """
    ]
    if bold.is_file():
        faces.append(
            f"""
            @font-face {{
              font-family: "DejaVu Sans";
              src: url("{bold.as_uri()}");
              font-weight: bold;
              font-style: normal;
            }}
            """
        )

    faces.append(
        """
        body, * {
          font-family: "DejaVu Sans", "Roboto", "Arial", sans-serif !important;
        }
        """
    )
    return CSS(string="\n".join(faces))


def render_pdf(template_name: str, context: dict[str, Any], output_path: Path) -> None:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "htm"]),
    )
    template = env.get_template(template_name)
    html_str = template.render(**context)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    stylesheets = []
    font_css = build_font_css()
    if font_css is not None:
        stylesheets.append(font_css)

    # base_url = корень проекта, чтобы url("fonts/...") в шаблонах резолвились
    HTML(string=html_str, base_url=str(BASE_DIR)).write_pdf(
        target=str(output_path),
        stylesheets=stylesheets,
    )


def open_pdf(path: Path) -> None:
    """Открывает PDF в системной программе (Windows / macOS / Linux)."""
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except OSError as exc:
        print(f"  Не удалось открыть PDF автоматически: {exc}")
        print(f"  Файл сохранён здесь: {path}")


# --- main ---------------------------------------------------------------------
def main() -> int:
    print_header("Генератор PDF-чеков")

    data_files = list_data_files()
    templates = list_templates()

    if not data_files:
        print(f"\nНет CSV/JSON файлов в {DATA_DIR}")
        return 1
    if not templates:
        print(f"\nНет HTML-шаблонов в {TEMPLATES_DIR}")
        return 1

    print_menu("Доступные файлы с данными", [f.name for f in data_files])
    print_menu("Доступные HTML-шаблоны", [f.name for f in templates])

    data_idx = ask_choice("Выберите файл данных", len(data_files))
    tmpl_idx = ask_choice("Выберите HTML-шаблон", len(templates))

    data_path = data_files[data_idx - 1]
    template_path = templates[tmpl_idx - 1]

    print(f"\n→ Данные:   {data_path.name}")
    print(f"→ Шаблон:   {template_path.name}")

    try:
        records = load_records(data_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"\nОшибка чтения файла данных: {exc}")
        return 1

    by_id = index_by_invoice_id(records)
    if not by_id:
        print(
            "\nВ файле не найдены записи с invoice id "
            f"(ожидаются поля: {', '.join(INVOICE_ID_KEYS)})."
        )
        return 1

    invoice_ids = list(by_id.keys())
    print_menu("Доступные чеки (invoice id)", invoice_ids)
    inv_idx = ask_choice("Выберите invoice id", len(invoice_ids))
    invoice_id = invoice_ids[inv_idx - 1]
    record = by_id[invoice_id]

    context = prepare_context(record)
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in invoice_id)
    output_path = OUTPUT_DIR / f"check_{safe_name}.pdf"

    print(f"\nГенерация PDF для {invoice_id}…")
    try:
        render_pdf(template_path.name, context, output_path)
    except Exception as exc:  # WeasyPrint / Jinja2
        print(f"\nОшибка генерации PDF: {exc}")
        return 1

    print(f"✓ PDF сохранён: {output_path}")
    print("Открываю файл…")
    open_pdf(output_path)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nПрервано пользователем.")
        sys.exit(130)
