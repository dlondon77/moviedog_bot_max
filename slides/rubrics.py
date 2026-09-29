# rubrics.py
"""
Конфиг рубрик КиноИщейки.
"""

RUBRICS = {
    # ============ SINGLE (один фильм, 5 слайдов) ============
    "mnenie_kinoyishcheyki": {
        "title": "Мнение КиноИщейки",
        "type": "single",
        "template": "opinion.html",
        "slide_titles": [
            "О чём лай?",
            "Какая атмосфера?",
            "Какая игра?",
            "Что зарыто?",
            "Какой вердикт?",
        ],
        "enabled": True,
    },
    "luchshaya_kostochka": {
        "title": "Лучшая косточка",
        "type": "single",
        "template": "luchshaya_kostochka.html",
        "slide_titles": [
            "О чём лай?",
            "Какая атмосфера?",
            "Какая игра?",
            "Что зарыто?",
            "Какой вердикт?",
        ],
        "enabled": False,
    },
    "razbor_polaet": {
        "title": "Разбор полает",
        "type": "single",
        "template": "razbor_polaet.html",
        "slide_titles": [
            "О чём лай?",
            "Какая атмосфера?",
            "Какая игра?",
            "Что зарыто?",
            "Какой вердикт?",
        ],
        "enabled": False,
    },
    "raskopki_kinoklassiki": {
        "title": "Раскопки киноклассики",
        "type": "single",
        "template": "raskopki_kinoklassiki.html",
        "slide_titles": [
            "О чём лай?",
            "Какая атмосфера?",
            "Какая игра?",
            "Что зарыто?",
            "Какой вердикт?",
        ],
        "enabled": False,
    },

    # ============ MULTI (несколько фильмов, N слайдов) ============
    "nyuhayu_novinki": {
        "title": "Нюхаю новинки",
        "type": "multi",
        "template": "nyuhayu_novinki.html",
        "slide_title": "О чём лай?",
        "enabled": False,
    },
    "gavgav_vybor": {
        "title": "ГавГав выбор",
        "type": "multi",
        "template": "gavgav_vybor.html",
        "slide_title": "О чём лай?",
        "enabled": False,
    },
    "na_krasnoy_dorozhke": {
        "title": "На красной дорожке",
        "type": "multi",
        "template": "na_krasnoy_dorozhke.html",
        "slide_title": "О чём лай?",
        "enabled": False,
    },
}


def get_rubric(key):
    return RUBRICS.get(key)


def list_for_menu():
    """Список рубрик для меню бота: [(key, title, enabled), ...]"""
    return [(k, v["title"], v.get("enabled", False)) for k, v in RUBRICS.items()]
