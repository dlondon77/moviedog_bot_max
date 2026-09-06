import re
from typing import Dict, List

def parse_opinion_file(file_path: str) -> Dict:
    """Парсит файл opinion.txt"""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    result = {
        "opinion": "",
        "rating": 0,
        "hashtags": [],
        "atmosphere_hashtags": []
    }
    
    for line in content.strip().split("\n"):
        line = line.strip()
        if line.startswith("Оценка:"):
            match = re.search(r'(\d+)', line)
            if match:
                result["rating"] = int(match.group(1))
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


def extract_opinion_components(text: str) -> Dict:
    """Извлекает оценку и хэштеги из текста мнения"""
    result = {
        "clean_opinion": text,
        "rating": 0,
        "hashtags": [],
        "atmosphere_hashtags": []
    }
    
    # Извлекаем оценку
    rating_match = re.search(r'Оценка:\s*(\d+)', text)
    if rating_match:
        result["rating"] = int(rating_match.group(1))
    
    # Извлекаем хэштеги настроения
    hashtags_match = re.search(r'Настроение:\s*(#[А-Яа-яA-Za-z_\w]+(?:\s+#[А-Яа-яA-Za-z_\w]+)*)', text)
    if hashtags_match:
        result["hashtags"] = re.findall(r'#[А-Яа-яA-Za-z_\w]+', hashtags_match.group(1))
    
    # Извлекаем хэштеги атмосферы
    atmosphere_match = re.search(r'Атмосфера:\s*(#[А-Яа-яA-Za-z_\w]+(?:\s+#[А-Яа-яA-Za-z_\w]+)*)', text)
    if atmosphere_match:
        result["atmosphere_hashtags"] = re.findall(r'#[А-Яа-яA-Za-z_\w]+', atmosphere_match.group(1))
    
    # Убираем оценку и хэштеги из основного текста
    clean_text = text
    clean_text = re.sub(r'Оценка:.*?(?=\n|$)', '', clean_text, flags=re.DOTALL)
    clean_text = re.sub(r'Настроение:.*?(?=\n|$)', '', clean_text, flags=re.DOTALL)
    clean_text = re.sub(r'Атмосфера:.*?(?=\n|$)', '', clean_text, flags=re.DOTALL)
    result["clean_opinion"] = clean_text.strip()
    
    return result
