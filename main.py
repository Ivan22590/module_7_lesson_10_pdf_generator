"""
AI Client Report Generator — точка входа.

Связывает все модули: чтение транскрибации → обработка ИИ → генерация PDF.
Поддерживает интерактивное меню и CLI-аргументы.
"""

import argparse
import logging
import sys
from pathlib import Path

from ai_processor import process_dialog_with_ai
from pdf_generator import generate_pdf

# Приглушаем шумный логгер fontTools (внутренности fpdf2)
logging.getLogger("fontTools").setLevel(logging.WARNING)

# Настройка логирования (в stdout, чтобы stderr оставался только для ошибок)
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Пути
PROJECT_ROOT = Path(__file__).parent.resolve()
EXAMPLES_DIR = PROJECT_ROOT / "examples"
REPORTS_DIR = PROJECT_ROOT / "reports"
TEMPLATES_DIR = PROJECT_ROOT / "templates"


def read_transcription_from_file(file_path: Path) -> str:
    """Читает текст транскрибации из файла."""
    if not file_path.is_file():
        raise FileNotFoundError(f"Файл не найден: {file_path}")

    text = file_path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Файл пуст: {file_path}")

    logger.info("Прочитан файл: %s (%d символов)", file_path.name, len(text))
    return text


def read_transcription_from_input() -> str:
    """Читает текст транскрибации из ручного ввода пользователя."""
    print("\nВведите текст диалога (для завершения введите пустую строку):")
    lines = []
    while True:
        try:
            line = input()
            if line == "":
                break
            lines.append(line)
        except EOFError:
            break

    text = "\n".join(lines)
    if not text.strip():
        raise ValueError("Вы не ввели текст диалога.")

    logger.info("Введено вручную: %d символов", len(text))
    return text


def _get_example_files() -> list[Path]:
    """Возвращает список .txt-файлов из папки examples/."""
    if not EXAMPLES_DIR.is_dir():
        return []
    return sorted(EXAMPLES_DIR.glob("*.txt"))


def _get_template_files() -> list[Path]:
    """Возвращает список .html-шаблонов из папки templates/."""
    if not TEMPLATES_DIR.is_dir():
        return []
    return sorted(TEMPLATES_DIR.glob("*.html"))


def show_template_menu() -> Path | None:
    """
    Отображает меню выбора HTML-шаблона отчёта.

    Returns:
        Путь к выбранному шаблону или None (использовать автоматический выбор).
    """
    templates = _get_template_files()

    print("\nДоступные шаблоны отчёта (папка templates/):")
    if templates:
        for idx, tpl_path in enumerate(templates, start=1):
            print(f"  {idx}. {tpl_path.name}")
    else:
        print("  [!] Папка templates/ пуста — будет использован шаблон по умолчанию.")

    print("  0. Автоматический выбор (последний изменённый шаблон)")

    while True:
        print("\nВыберите шаблон: ", end="")
        choice = input().strip()

        if choice == "0":
            return None

        if choice.isdigit():
            idx = int(choice)
            if templates and 1 <= idx <= len(templates):
                return templates[idx - 1]
            max_val = len(templates) if templates else 0
            print(
                f"\n[ОШИБКА] Неверный номер. Доступны: 1-{max_val} или 0."
            )
            continue

        print("\n[ОШИБКА] Введите номер шаблона или 0.")


def show_menu() -> int | None:
    """
    Отображает цифровое диалоговое меню с выбором источника транскрибации.

    Returns:
        Выбранный код пункта меню (int) или None при выходе.
    """
    example_files = _get_example_files()

    print("\n" + "=" * 55)
    print("   AI CLIENT REPORT GENERATOR")
    print("=" * 55)

    if example_files:
        print("\nДоступные транскрибации (папка examples/):")
        for idx, file_path in enumerate(example_files, start=1):
            print(f"  {idx}. {file_path.name}")
    else:
        print("\n[!] Папка examples/ пуста или не содержит .txt-файлов.")

    print("\nДополнительные действия:")
    print("  0. Ввести текст диалога вручную")
    print("  9. Указать путь к произвольному файлу")
    print("  q. Выход")
    print("-" * 55)

    return None  # Placeholder — реальная логика выбора в run_interactive


def get_user_choice(example_files: list[Path]) -> str | None:
    """
    Получает выбор пользователя из меню и возвращает текст транскрибации.

    Args:
        example_files: Список доступных файлов из examples/.

    Returns:
        Текст транскрибации или None, если пользователь вышел.
    """
    while True:
        print("\nВыберите пункт меню: ", end="")
        choice = input().strip().lower()

        # Выход
        if choice in ("q", "quit", "exit", "выход"):
            return None

        # Ручной ввод текста
        if choice == "0":
            try:
                return read_transcription_from_input()
            except ValueError as e:
                print(f"\n[ОШИБКА] {e}")
                continue

        # Путь к произвольному файлу
        if choice == "9":
            print("Введите путь к файлу: ", end="")
            file_input = input().strip()
            if not file_input:
                print("\n[ОШИБКА] Путь не указан.")
                continue
            try:
                file_path = Path(file_input)
                # Если путь относительный, ищем от корня проекта
                if not file_path.is_absolute():
                    file_path = PROJECT_ROOT / file_path
                return read_transcription_from_file(file_path)
            except (FileNotFoundError, ValueError) as e:
                print(f"\n[ОШИБКА] {e}")
                continue

        # Выбор файла из examples/
        if choice.isdigit():
            idx = int(choice)
            if example_files and 1 <= idx <= len(example_files):
                selected_file = example_files[idx - 1]
                try:
                    return read_transcription_from_file(selected_file)
                except (FileNotFoundError, ValueError) as e:
                    print(f"\n[ОШИБКА] {e}")
                    continue
            else:
                max_val = len(example_files) if example_files else 0
                print(
                    f"\n[ОШИБКА] Неверный номер. "
                    f"Доступны: 1-{max_val}, 0, 9 или q."
                )
                continue

        # Неверный ввод
        print("\n[ОШИБКА] Неверный ввод. Введите номер пункта, 0, 9 или q.")


def run_interactive() -> None:
    """Запускает интерактивный режим с цифровым меню."""
    example_files = _get_example_files()
    show_menu()

    text = get_user_choice(example_files)
    if text is None:
        print("\nВыход. До свидания!")
        sys.exit(0)

    # Выбор шаблона отчёта
    template_path = show_template_menu()

    _process_and_generate(text, template_path)


def run_cli(file_path: Path, template_path: Path | None = None) -> None:
    """Запускает CLI-режим с указанием файла через аргумент."""
    try:
        if not file_path.is_absolute():
            file_path = PROJECT_ROOT / file_path
        text = read_transcription_from_file(file_path)
    except (FileNotFoundError, ValueError) as e:
        logger.error("Ошибка чтения файла: %s", e)
        print(f"\n[ОШИБКА] {e}")
        sys.exit(1)

    _process_and_generate(text, template_path)


def _process_and_generate(text: str, template_path: Path | None = None) -> None:
    """Общий пайплайн: AI-обработка → генерация PDF."""
    # Шаг 1: Обработка через ИИ
    print("\n⏳ Анализ диалога с помощью ИИ...")
    try:
        ai_data = process_dialog_with_ai(text)
    except ValueError as e:
        logger.error("Ошибка ИИ-обработки: %s", e)
        print(f"\n[ОШИБКА] {e}")
        sys.exit(1)
    except Exception as e:
        logger.error("Непредвиденная ошибка при обращении к ИИ: %s", e, exc_info=True)
        print(f"\n[ОШИБКА] Не удалось обратиться к ИИ: {e}")
        sys.exit(1)

    print("✅ Диалог проанализирован успешно!")
    print(f"   Клиент: {ai_data.get('client_name', 'Н/Д')}")
    print(f"   Тема: {ai_data.get('topic', 'Н/Д')}")
    print(f"   Настроение: {ai_data.get('mood', 'Н/Д')}")

    # Добавляем транскрибацию и цвет настроения для шаблона
    ai_data["transcript"] = _format_transcript_html(text)
    ai_data.setdefault(
        "mood_color",
        {"Позитивное": "#1e8449", "Нейтральное": "#a04000"}.get(
            ai_data.get("mood", ""), "#922b21"
        ),
    )

    # Шаг 2: Генерация PDF
    print("\n⏳ Генерация PDF-отчёта...")
    if template_path:
        print(f"   Шаблон: {template_path.name}")
    try:
        pdf_path = generate_pdf(ai_data, template_path=template_path)
    except FileNotFoundError as e:
        logger.error("Ошибка шаблона: %s", e)
        print(f"\n[ОШИБКА] {e}")
        sys.exit(1)
    except Exception as e:
        logger.error("Ошибка генерации PDF: %s", e, exc_info=True)
        print(f"\n[ОШИБКА] Не удалось создать PDF: {e}")
        sys.exit(1)

    # Успех
    relative_path = pdf_path.relative_to(PROJECT_ROOT)
    print(f"\n{'=' * 55}")
    print(f"📄 Отчёт успешно создан: {relative_path}")
    print(f"{'=' * 55}\n")


def _format_transcript_html(text: str) -> str:
    """
    Форматирует транскрибацию в HTML-теги, поддерживаемые fpdf2.

    Реплики помечаются цветом: Оператор — синий, Клиент — фиолетовый.
    Спецсимволы HTML экранируются вручную.
    """
    lines = text.strip().split("\n")
    html_lines = []
    for line in lines:
        # Экранируем HTML-спецсимволы
        safe_line = (
            line.replace("&", "&")
            .replace("<", "<")
            .replace(">", ">")
        )
        # Подсвечиваем роли цветом (fpdf2 поддерживает тег <font>)
        if "Оператор:" in safe_line:
            safe_line = safe_line.replace(
                "Оператор:", '<font color="#2980b9"><b>Оператор:</b></font>', 1
            )
        elif "Клиент:" in safe_line:
            safe_line = safe_line.replace(
                "Клиент:", '<font color="#8e44ad"><b>Клиент:</b></font>', 1
            )
        html_lines.append(f"<p>{safe_line}</p>")

    return "\n".join(html_lines)


def main() -> None:
    """Главная функция: парсинг аргументов и запуск нужного режима."""
    parser = argparse.ArgumentParser(
        description="AI Client Report Generator — PDF-отчёты по диалогам с клиентами",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Примеры:
  python main.py                                    # Интерактивное меню
  python main.py --file examples/transcription.txt  # Из файла
  python main.py --file dialog.txt --template templates/green_right.html
        """,
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="Путь к файлу с транскрибацией (для неинтерактивного режима)",
    )
    parser.add_argument(
        "--template",
        type=Path,
        help="Путь к HTML-шаблону (по умолчанию — автоматический выбор из templates/)",
    )

    args = parser.parse_args()

    if args.file:
        run_cli(args.file, args.template)
    else:
        run_interactive()


if __name__ == "__main__":
    main()
