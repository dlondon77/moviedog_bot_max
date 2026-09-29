# slides_generation.py
"""
Библиотека генерации слайдов КиноИщейки.
Точка входа: generate(rubric_key, input_dir, output_dir).
"""

import os
import re
import base64
import json
import logging
import requests

from rubrics import get_rubric


# ============================================================
# DEEPSEEK
# ============================================================

DEEPSEEK_API_KEY = os.environ.get(
    "DEEPSEEK_API_KEY",
    "sk-1be9e78c0cd347d4bdda68f8b54e0992",
)
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"


# ============================================================
# ЛОГИРОВАНИЕ
# ============================================================

def setup_logger(log_path):
    logger = logging.getLogger("slides")
    logger.setLevel(logging.INFO)

    # Чистим старые хендлеры
    for h in list(logger.handlers):
        logger.removeHandler(h)

    fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    return logger


# ============================================================
# ПАРСЕРЫ
# ============================================================

def parse_film_file(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    result = {
        "title": "",
        "country": "",
        "year": "",
        "director": "",
        "actors": "",
    }

    lines = content.strip().split("\n")

    for i, line in enumerate(lines):
        line = line.strip()

        if i == 0:
            title_clean = re.sub(r'^[🎬📁⭐🌍🎭📝🎥👥]', '', line).strip()
            year_match = re.search(r'\((\d{4})\)', title_clean)
            if year_match:
                result["year"] = year_match.group(1)
                result["title"] = re.sub(r'\s*\(\d{4}\)$', '', title_clean).strip()
            else:
                result["title"] = title_clean
            continue

        line_clean = re.sub(r'^[🎬📁⭐🌍🎭📝🎥👥]', '', line).strip()

        if "Страна:" in line_clean:
            result["country"] = line_clean.replace("Страна:", "").strip()
        elif "Режиссер" in line_clean or "Режиссёр" in line_clean:
            result["director"] = line_clean.replace("Режиссер:", "").replace("Режиссёр:", "").strip()
        elif "Актеры" in line_clean or "Актёры" in line_clean:
            result["actors"] = line_clean.replace("Актеры:", "").replace("Актёры:", "").strip()

    return result


def parse_opinion_file(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    result = {
        "opinion": "",
        "rating": 0,
        "hashtags": [],
        "atmosphere_hashtags": [],
    }

    for line in content.strip().split("\n"):
        line = line.strip()
        if line.startswith("Оценка:"):
            m = re.search(r'(\d+)', line)
            if m:
                result["rating"] = int(m.group(1))
        elif line.startswith("Настроение:"):
            result["hashtags"].extend(re.findall(r'#[А-Яа-яA-Za-z_\w]+', line))
        elif line.startswith("Атмосфера:"):
            result["atmosphere_hashtags"].extend(re.findall(r'#[А-Яа-яA-Za-z_\w]+', line))
        else:
            result["opinion"] += line + " "

    result["opinion"] = result["opinion"].strip()
    result["hashtags"] = list(dict.fromkeys(result["hashtags"]))
    result["atmosphere_hashtags"] = list(dict.fromkeys(result["atmosphere_hashtags"]))
    return result


# ============================================================
# DEEPSEEK — РАЗБИВКА МНЕНИЯ
# ============================================================

def split_opinion_with_deepseek(text, rating, hashtags, atmosphere_hashtags, logger):
    prompt = f"""Ты — КиноИщейка, собака-девочка, кинокритик с отличным чутьём. Ты уже написала своё мнение о фильме, теперь тебе нужно разбить его на 5 смысловых блоков для слайдов в Instagram-карусели.

Твоё мнение:
{text}

Разбей его на 5 логических блоков для следующих слайдов:

1️⃣ "О чём лай?" — кратко о сюжете, главном герое, что происходит
2️⃣ "Какая атмосфера?" — описание атмосферы, визуала, настроения фильма
3️⃣ "Какая игра?" — об актёрской игре, кто особенно запомнился
4️⃣ "Что зарыто?" — о скрытых смыслах, глубине, идеях, символизме
5️⃣ "Какой вердикт?" — итоговое мнение, плюсы и минусы, стоит ли смотреть

ПРАВИЛА:
- Каждый блок — 1-2 предложения (максимум 30 слов)
- Сохрани собачий юмор и образ КиноИщейки (говори о себе в женском роде)
- Сохрани ключевые метафоры из оригинального текста
- Блоки должны быть логически связаны
- НЕ добавляй новые факты, которых нет в исходном мнении
- НЕ начинай с вводных фраз типа "Я думаю" или "Мне кажется"
- Используй только те слова и выражения, которые уже есть в тексте
- В 5-м блоке ("Какой вердикт?") НЕ упоминай оценку в виде числа — она будет отображаться отдельно

Оценка фильма: {rating}/10 (НЕ упоминай эту оценку в тексте блоков!)
Хэштеги настроения: {" ".join(hashtags) if hashtags else "нет"} (будут на 5-м слайде)
Хэштеги атмосферы: {" ".join(atmosphere_hashtags) if atmosphere_hashtags else "нет"} (будут на 2-м слайде)

Верни ответ строго в формате JSON:
{{
    "blocks": [
        "текст для слайда 1",
        "текст для слайда 2",
        "текст для слайда 3",
        "текст для слайда 4",
        "текст для слайда 5"
    ]
}}"""

    try:
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        }
        data = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "Ты — КиноИщейка, собака-девочка, кинокритик. Ты помогаешь структурировать свои же обзоры для соцсетей. Будь точной и остроумной. Никогда не упоминай числовую оценку в тексте блоков."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 600,
        }

        logger.info("🤖 Отправляем запрос в DeepSeek...")
        r = requests.post(DEEPSEEK_URL, headers=headers, json=data, timeout=30)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        logger.info("📨 Ответ DeepSeek получен")

        m = re.search(r'\{.*\}', content, re.DOTALL)
        if m:
            parsed = json.loads(m.group())
            blocks = parsed.get("blocks", [])
            if len(blocks) >= 5:
                return blocks[:5]

        logger.warning("⚠️ Не удалось распарсить ответ DeepSeek, fallback")
        return fallback_split(text)

    except Exception as e:
        logger.error(f"⚠️ Ошибка DeepSeek: {e}")
        return fallback_split(text)


def fallback_split(text):
    sentences = re.split(r'[.!?]', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]

    if len(sentences) >= 5:
        return [sentences[i] + "." for i in range(5)]

    while len(sentences) < 5:
        sentences.append(sentences[-1] if sentences else "Нет данных")

    return [sentences[i] + "." for i in range(5)]


# ============================================================
# HTML-КАРТОЧКА
# ============================================================

def generate_card_html(template_path, frame_path, film_data, slide_title, slide_text,
                       rating, hashtags, atmosphere_hashtags,
                       is_first, is_atmosphere, is_last):
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    with open(frame_path, "rb") as f:
        img_data = base64.b64encode(f.read()).decode("utf-8")

    country_year = film_data["country"]
    if film_data.get("year"):
        country_year += f", {film_data['year']}"

    html = html.replace("{{FRAME}}", f"data:image/jpeg;base64,{img_data}")
    html = html.replace("{{SLIDE_TITLE}}", slide_title)
    html = html.replace("{{SLIDE_TEXT}}", slide_text)
    html = html.replace("{{RUBRIC}}", "Мнение КиноИщейки")

    html = html.replace("{{ARROW_VISIBLE}}", "" if is_first else "hidden")

    if is_first:
        html = html.replace("{{TITLE}}", film_data["title"])
        html = html.replace("{{COUNTRY}}", country_year)
        html = html.replace("{{DIRECTOR}}", film_data["director"])
        html = html.replace("{{ACTORS}}", film_data["actors"])
        html = html.replace("{{FILM_INFO_VISIBLE}}", "")
    else:
        html = html.replace("{{TITLE}}", "")
        html = html.replace("{{COUNTRY}}", "")
        html = html.replace("{{DIRECTOR}}", "")
        html = html.replace("{{ACTORS}}", "")
        html = html.replace("{{FILM_INFO_VISIBLE}}", "hidden")

    if is_last:
        bones = ""
        for i in range(10):
            bones += '<span class="bone-filled">🦴</span>' if i < rating else '<span class="bone-empty">🦴</span>'

        rating_html = f"""
        <div class="rating-wrapper">
          <span class="rating-number">{rating}</span>
          <span class="rating-bones">{bones}</span>
        </div>
        """
        html = html.replace("{{RATING}}", rating_html)
    else:
        html = html.replace("{{RATING}}", "")

    if is_atmosphere and atmosphere_hashtags:
        html = html.replace("{{HASHTAGS}}", f'<div class="hashtags">{" ".join(atmosphere_hashtags[:5])}</div>')
    elif is_last and hashtags:
        html = html.replace("{{HASHTAGS}}", f'<div class="hashtags">{" ".join(hashtags[:5])}</div>')
    else:
        html = html.replace("{{HASHTAGS}}", "")

    return html


# ============================================================
# POST.TXT
# ============================================================

def normalize_paragraphs(text):
    if not text:
        return ""
    break_markers = ("Оценка:", "Настроение:", "Атмосфера:", "🎞", "Загляни", "👉", "А если", "#мнение")
    lines = text.split("\n")
    paragraphs, current = [], []

    for line in lines:
        s = line.strip()
        if not s:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if current and any(s.startswith(m) for m in break_markers):
            paragraphs.append(" ".join(current))
            current = [s]
        else:
            current.append(s)

    if current:
        paragraphs.append(" ".join(current))

    return "\n\n".join(paragraphs)


PARAGRAPH_EMOJIS = ["🐕", "🦴", "🐾", "🎬", "🎞"]


def emojize_paragraphs(text):
    if not text:
        return text
    paragraphs = text.split("\n\n")
    result, idx = [], 0
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if re.match(r'^[\U0001F300-\U0001FAFF\u2600-\u27BF]', p):
            result.append(p)
            continue
        if p.startswith("Оценка:"):
            result.append("⭐ " + p)
        elif p.startswith("Настроение:"):
            result.append("🏷 " + p)
        elif p.startswith("Атмосфера:"):
            result.append("🌫 " + p)
        else:
            result.append(f"{PARAGRAPH_EMOJIS[idx % len(PARAGRAPH_EMOJIS)]} {p}")
            idx += 1
    return "\n\n".join(result)


def build_post_text(input_dir):
    opinion_path = os.path.join(input_dir, "opinion.txt")
    cta_path = os.path.join(input_dir, "cta.txt")

    with open(opinion_path, "r", encoding="utf-8") as f:
        opinion_text = f.read().strip()

    cta = ""
    if os.path.exists(cta_path):
        with open(cta_path, "r", encoding="utf-8") as f:
            cta = f.read().strip()

    opinion_text = normalize_paragraphs(opinion_text)
    cta = normalize_paragraphs(cta)
    opinion_text = emojize_paragraphs(opinion_text)

    parts = [opinion_text]
    if cta:
        parts.append(cta)
    return "\n\n".join(parts).strip() + "\n"


# ============================================================
# ГЕНЕРАЦИЯ SINGLE
# ============================================================

def generate_single(rubric, input_dir, output_dir, logger):
    film_path = os.path.join(input_dir, "film.txt")
    opinion_path = os.path.join(input_dir, "opinion.txt")

    if not os.path.exists(film_path):
        return {"ok": False, "error": "Не найден film.txt", "code": "MISSING_FILE"}
    if not os.path.exists(opinion_path):
        return {"ok": False, "error": "Не найден opinion.txt", "code": "MISSING_FILE"}

    film_data = parse_film_file(film_path)
    opinion_data = parse_opinion_file(opinion_path)

    logger.info(f"🎬 Фильм: {film_data['title']} ({film_data['year']})")
    logger.info(f"⭐ Оценка: {opinion_data['rating']}/10")

    blocks = split_opinion_with_deepseek(
        opinion_data["opinion"],
        opinion_data["rating"],
        opinion_data["hashtags"],
        opinion_data["atmosphere_hashtags"],
        logger,
    )

    slide_titles = rubric["slide_titles"]

    # Пути
    base_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(base_dir, "templates", rubric["template"])
    frames_dir = os.path.join(input_dir, "frames")

    if not os.path.exists(template_path):
        return {"ok": False, "error": f"Шаблон не найден: {template_path}", "code": "MISSING_TEMPLATE"}

    for i in range(5):
        frame_path = os.path.join(frames_dir, f"frame_{i+1}.jpg")
        if not os.path.exists(frame_path):
            return {"ok": False, "error": f"Не найден кадр: frame_{i+1}.jpg", "code": "MISSING_FRAME"}

    os.makedirs(output_dir, exist_ok=True)

    logger.info("🎨 Генерация 5 карточек...")

    created = []

    for i in range(5):
        frame_path = os.path.join(frames_dir, f"frame_{i+1}.jpg")
        html = generate_card_html(
            template_path=template_path,
            frame_path=frame_path,
            film_data=film_data,
            slide_title=slide_titles[i],
            slide_text=blocks[i],
            rating=opinion_data["rating"],
            hashtags=opinion_data["hashtags"],
            atmosphere_hashtags=opinion_data["atmosphere_hashtags"],
            is_first=(i == 0),
            is_atmosphere=(i == 1),
            is_last=(i == 4),
        )

        out_path = os.path.join(output_dir, f"card_{i+1}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)

        created.append(f"card_{i+1}.html")
        logger.info(f"✅ Слайд {i+1}: {slide_titles[i]} → card_{i+1}.html")

    # post.txt
    post_text = build_post_text(input_dir)
    post_path = os.path.join(output_dir, "post.txt")
    with open(post_path, "w", encoding="utf-8") as f:
        f.write(post_text)
    created.append("post.txt")
    logger.info("✅ post.txt сохранён")

    return {"ok": True, "files": created}


# ============================================================
# ЗАГЛУШКА MULTI
# ============================================================

def generate_multi(rubric, input_dir, output_dir, logger):
    return {
        "ok": False,
        "error": f"Рубрика '{rubric['title']}' (multi) ещё не реализована.",
        "code": "NOT_IMPLEMENTED",
    }


# ============================================================
# ГЛАВНАЯ ТОЧКА ВХОДА
# ============================================================

def generate(rubric_key, input_dir, output_dir):
    """
    Генерирует слайды и post.txt.
    Возвращает dict: {"ok": bool, "files": [...], "error": "..."}
    """
    os.makedirs(output_dir, exist_ok=True)
    log_path = os.path.join(output_dir, "generation.log")
    logger = setup_logger(log_path)

    logger.info("=" * 50)
    logger.info(f"🐕 Запуск генерации. Рубрика: {rubric_key}")

    rubric = get_rubric(rubric_key)
    if not rubric:
        msg = f"Рубрика '{rubric_key}' не найдена"
        logger.error(f"❌ {msg}")
        return {"ok": False, "error": msg, "code": "UNKNOWN_RUBRIC"}

    if not rubric.get("enabled"):
        msg = f"Рубрика '{rubric['title']}' ещё не реализована"
        logger.warning(f"⚠️ {msg}")
        return {"ok": False, "error": msg, "code": "NOT_ENABLED"}

    if rubric["type"] == "single":
        result = generate_single(rubric, input_dir, output_dir, logger)
    elif rubric["type"] == "multi":
        result = generate_multi(rubric, input_dir, output_dir, logger)
    else:
        result = {"ok": False, "error": f"Неизвестный тип: {rubric['type']}", "code": "UNKNOWN_TYPE"}

    if result.get("ok"):
        logger.info("🎉 ГОТОВО!")
    else:
        logger.error(f"❌ Ошибка: {result.get('error')}")

    return result
