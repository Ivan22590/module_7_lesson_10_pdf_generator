"""
Генератор PDF-отчётов.

Подставляет данные из AI-анализа в HTML-шаблон (Jinja2) и конвертирует
в PDF с помощью FPDF2. FPDF2 поддерживает кириллицу из коробки.
Поддерживает смену шаблона через конфигурацию или автоматически
выбирает последний изменённый шаблон.
"""

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fpdf import FPDF
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

# Загружаем переменные окружения
load_dotenv()

# Пути
PROJECT_ROOT = Path(__file__).parent.resolve()
TEMPLATES_DIR = PROJECT_ROOT / "templates"
REPORTS_DIR = PROJECT_ROOT / "reports"


def _get_template_path() -> Path:
    """
    Возвращает путь к используемому HTML-шаблону.

    Приоритет:
    1. Переменная окружения TEMPLATE_PATH
    2. Последний по дате .html-файл в папке templates/
    """
    template_path_str = os.getenv("TEMPLATE_PATH", "").strip()
    if template_path_str:
        template_path = PROJECT_ROOT / template_path_str
        if template_path.is_file():
            logger.info("Используется шаблон из TEMPLATE_PATH: %s", template_path)
            return template_path
        logger.warning(
            "Шаблон из TEMPLATE_PATH не найден: %s. Ищем в папке templates/."
        )

    # Автоматический поиск последнего изменённого шаблона
    html_files = list(TEMPLATES_DIR.glob("*.html"))
    if not html_files:
        raise FileNotFoundError(
            "Не найдено HTML-файлов в папке templates/. "
            "Положите шаблон (например, default.html) и попробуйте снова."
        )

    # Сортируем по времени последнего изменения (новые — первыми)
    template_path = sorted(html_files, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    logger.info(
        "Автоматически выбран шаблон: %s (изменён: %s)",
        template_path,
        datetime.fromtimestamp(template_path.stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    )
    return template_path


def render_template(data: dict[str, Any], template_path: Path) -> str:
    """
    Подставляет данные в HTML-шаблон через Jinja2.

    Args:
        data: Словарь с данными для подстановки.
        template_path: Путь к HTML-файлу шаблона.

    Returns:
        Отрендеренная HTML-строка.
    """
    logger.info("Рендеринг шаблона: %s", template_path)

    env = Environment(
        loader=FileSystemLoader(template_path.parent),
        autoescape=True,
    )

    template = env.get_template(template_path.name)

    # Добавляем служебные данные
    now = datetime.now()
    data.setdefault("generated_at", now.strftime("%d.%m.%Y в %H:%M"))
    data.setdefault("generated_at_year", str(now.year))

    return template.render(**data)


def generate_pdf(
    data: dict[str, Any],
    output_dir: Path | None = None,
    template_path: Path | None = None,
) -> Path:
    """
    Генерирует PDF-отчёт из данных и шаблона.

    Args:
        data: Словарь с полями: client_name, topic, main_request, mood, next_steps.
        output_dir: Папка для сохранения PDF (по умолчанию reports/).
        template_path: Путь к HTML-шаблону (по умолчанию — из конфигурации).

    Returns:
        Путь к созданному PDF-файлу.
    """
    output_dir = output_dir or REPORTS_DIR
    template_path = template_path or _get_template_path()

    # Создаём папку для отчётов, если нет
    output_dir.mkdir(parents=True, exist_ok=True)

    # Рендерим HTML
    html_content = render_template(data, template_path)

    # Формируем имя файла с датой
    now = datetime.now()
    filename = f"report_{now.strftime('%Y-%m-%d_%H-%M')}.pdf"
    output_path = output_dir / filename

    logger.info("Конвертация HTML в PDF: %s", output_path)

    # Создаём PDF
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)

    # Регистрируем Unicode-шрифт для кириллицы
    font_dir = PROJECT_ROOT / "fonts"
    font_variants = {
        "": font_dir / "arial.ttf",
        "B": font_dir / "arialbd.ttf",
        "I": font_dir / "ariali.ttf",
        "BI": font_dir / "arialbi.ttf",
    }

    if font_variants[""].is_file():
        for style, path in font_variants.items():
            if path.is_file():
                pdf.add_font("Custom", style, str(path))
        logger.info("Шрифт зарегистрирован для кириллицы: %s", font_variants[""].name)
    else:
        logger.warning(
            "Шрифт не найден: %s. Скопируйте arial.ttf в папку fonts/. "
            "Кириллица может отображаться некорректно.",
            font_variants[""],
        )

    pdf.add_page()

    # write_html не понимает <head>/<meta> — передаём только содержимое <body>
    body_match = re.search(r"<body[^>]*>(.*)</body>", html_content, re.DOTALL | re.IGNORECASE)
    body_html = body_match.group(1) if body_match else html_content

    # Рендерим HTML через fpdf2 (Custom — зарегистрированный Unicode-шрифт)
    pdf.write_html(body_html, font_family="Custom")

    # Сохраняем PDF
    pdf.output(str(output_path))

    logger.info("PDF успешно сохранён: %s (%.1f КБ)", output_path, output_path.stat().st_size / 1024)
    return output_path
