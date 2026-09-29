# run_slides.py
"""
CLI-обёртка для генерации слайдов.

Приоритет выбора рубрики:
  1. --rubric (аргумент)
  2. input/rubric.txt
  3. переменная окружения RUBRIC
  4. интерактивное меню (только в терминале)
"""

import os
import sys
import json
import argparse

from slides_generation import generate
from slide_files import check_input_ready
from rubrics import RUBRICS, list_for_menu


def interactive_menu():
    """Интерактивное меню выбора рубрики."""
    print("🐕 КиноИщейка — генератор слайдов")
    print("=" * 50)
    print()

    items = list_for_menu()
    for i, (key, title, enabled) in enumerate(items, 1):
        status = "готово" if enabled else "скоро"
        print(f"  [{i}] 🎬 {title:<30} [{status}]")

    print()
    choice = input("Выбери номер рубрики (или q для выхода): ").strip()

    if choice.lower() == "q":
        print("🐾 Пока!")
        sys.exit(0)

    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(items):
            print("❌ Неверный номер")
            sys.exit(1)
    except ValueError:
        print("❌ Введи число")
        sys.exit(1)

    key, title, enabled = items[idx]
    print(f"\nТы выбрал: {title}\n")

    input_dir = input("Папка input [input]: ").strip() or "input"
    output_dir = input("Папка output [output]: ").strip() or "output"

    return key, input_dir, output_dir


def read_rubric_from_file(input_dir):
    """Читает код рубрики из input/rubric.txt."""
    path = os.path.join(input_dir, "rubric.txt")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        key = f.read().strip()
    return key or None


def resolve_rubric(args, input_dir):
    """
    Определяет рубрику по приоритету:
      1. --rubric
      2. input/rubric.txt
      3. RUBRIC из окружения
      4. интерактивное меню (если терминал)
    Возвращает (rubric_key, source) или (None, None).
    """
    # 1. Аргумент
    if args.rubric:
        return args.rubric, "cli"

    # 2. Файл
    key = read_rubric_from_file(input_dir)
    if key:
        return key, "file"

    # 3. Переменная окружения
    key = os.environ.get("RUBRIC", "").strip()
    if key:
        return key, "env"

    # 4. Интерактив — только если запущено в живом терминале
    if sys.stdin.isatty() and not args.json:
        key, input_dir, output_dir = interactive_menu()
        # Перезапишем пути — их вернул интерактив
        args.input = input_dir
        args.output = output_dir
        return key, "interactive"

    return None, None


def main():
    parser = argparse.ArgumentParser(description="Генератор слайдов КиноИщейки")
    parser.add_argument("--rubric", help="Код рубрики (например, mnenie_kinoyishcheyki)")
    parser.add_argument("--input", default="input", help="Папка input")
    parser.add_argument("--output", default="output", help="Папка output")
    parser.add_argument("--json", action="store_true", help="Вывод в JSON (для бота)")

    args = parser.parse_args()

    rubric_key, source = resolve_rubric(args, args.input)

    if not rubric_key:
        result = {
            "ok": False,
            "error": "Рубрика не указана. Передай --rubric, положи код в input/rubric.txt "
                     "или запусти в терминале для интерактивного меню.",
            "code": "NO_RUBRIC",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)

    # Пути могут быть переопределены интерактивом — считываем заново
    input_dir = args.input
    output_dir = args.output

    # Проверка input
    ok, missing = check_input_ready(input_dir, required_frames=5)
    if not ok:
        result = {
            "ok": False,
            "error": f"Не хватает файлов: {', '.join(missing)}",
            "code": "MISSING_INPUT",
            "missing": missing,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)

    # Генерация
    result = generate(rubric_key, input_dir, output_dir)
    result["rubric"] = rubric_key
    result["rubric_source"] = source

    # JSON — для бота или если явно попросили
    if args.json or not sys.stdin.isatty():
        print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result.get("ok"):
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
