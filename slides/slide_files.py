# slide_files.py
"""
Утилиты для работы с файлами слайдов.
Используются ботом, чтобы разложить данные пользователя по input/.
"""

import os
import shutil


# Какие файлы НЕ удаляем при очистке input/
KEEP_ON_RESET = {"cta.txt"}


def ensure_dirs(input_dir):
    """Создаёт структуру папок, если её нет."""
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(os.path.join(input_dir, "frames"), exist_ok=True)


def reset_input(input_dir, keep=None):
    """
    Чистит input/, кроме файлов из KEEP_ON_RESET (cta.txt).
    Файлы, которые надо сохранить, можно передать в keep (set имён).
    """
    if keep is None:
        keep = KEEP_ON_RESET

    if not os.path.exists(input_dir):
        ensure_dirs(input_dir)
        return

    for name in os.listdir(input_dir):
        if name in keep:
            continue
        path = os.path.join(input_dir, name)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        except Exception as e:
            print(f"⚠️ Не удалось удалить {path}: {e}")

    ensure_dirs(input_dir)


def save_film_text(input_dir, text):
    """Сохраняет карточку фильма в input/film.txt."""
    ensure_dirs(input_dir)
    path = os.path.join(input_dir, "film.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.strip() + "\n")
    return path


def save_opinion_text(input_dir, text):
    """Сохраняет мнение в input/opinion.txt."""
    ensure_dirs(input_dir)
    path = os.path.join(input_dir, "opinion.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.strip() + "\n")
    return path


def save_frame(input_dir, index, file_bytes, ext="jpg"):
    """
    Сохраняет картинку как input/frames/frame_{index}.jpg.
    index — 1..5.
    """
    ensure_dirs(input_dir)
    path = os.path.join(input_dir, "frames", f"frame_{index}.{ext}")
    with open(path, "wb") as f:
        f.write(file_bytes)
    return path


def save_cta_text(input_dir, text):
    """Сохраняет CTA (если надо перезаписать общий)."""
    ensure_dirs(input_dir)
    path = os.path.join(input_dir, "cta.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.strip() + "\n")
    return path


def list_output_files(output_dir):
    """
    Возвращает список файлов в output/ (только имена, отсортированные).
    Скрывает generation.log.
    """
    if not os.path.exists(output_dir):
        return []
    files = []
    for name in sorted(os.listdir(output_dir)):
        if name == "generation.log":
            continue
        path = os.path.join(output_dir, name)
        if os.path.isfile(path):
            files.append(name)
    return files


def check_input_ready(input_dir, required_frames=5):
    """
    Проверяет, что все нужные файлы на месте.
    Возвращает (ok: bool, missing: list[str]).
    """
    missing = []

    film = os.path.join(input_dir, "film.txt")
    opinion = os.path.join(input_dir, "opinion.txt")
    cta = os.path.join(input_dir, "cta.txt")

    if not os.path.exists(film):
        missing.append("film.txt")
    if not os.path.exists(opinion):
        missing.append("opinion.txt")
    if not os.path.exists(cta):
        missing.append("cta.txt")

    frames_dir = os.path.join(input_dir, "frames")
    for i in range(1, required_frames + 1):
        p = os.path.join(frames_dir, f"frame_{i}.jpg")
        if not os.path.exists(p):
            missing.append(f"frames/frame_{i}.jpg")

    return (len(missing) == 0, missing)
