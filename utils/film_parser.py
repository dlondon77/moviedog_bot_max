import re
from typing import Dict

def parse_film_file(file_path: str) -> Dict:
    """Парсит файл film.txt"""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    result = {
        "title": "",
        "country": "",
        "year": "",
        "director": "",
        "actors": ""
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
