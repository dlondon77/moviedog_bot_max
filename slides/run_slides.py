# run_slides.py
"""
CLI-обёртка для генерации слайдов.
Возвращает JSON в stdout — его парсит бот.
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

    input_dir = input(f"Папка input [{key}/input/]: ").strip() or "input"
    output_dir = input(f"Папка output [output/]: ").strip() or "output"

    return key, input_dir, output_dir


def main():
    parser = argparse.ArgumentParser(description="Генератор слайдов КиноИщейки")
    parser.add_argument("--rubric", help="Код рубрики (например, mnenie_kinoyishcheyki)")
    parser.add_argument("--input", default="input", help="Папка input")
    parser.add_argument("--output", default="output", help="Папка output")
    parser.add_argument("--json", action="store_true", help="Вывод в JSON (для бота)")

    args = parser.parse_args()

    # Если рубрика не задана и мы в интерактиве — показать меню
    if not args.rubric:
        if sys.stdin.isatty() and not args.json:
            rubric_key, input_dir, output_dir = interactive_menu()
        else:
            print(json.dumps({
                "ok": False,
                "error": "Не указана рубрика (--rubric)",
                "code": "NO_RUBRIC",
            }, ensure_ascii=False))
            sys.exit(1)
    else:
        rubric_key = args.rubric
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

    if args.json or not sys.stdin.isatty():
        print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result.get("ok"):
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
