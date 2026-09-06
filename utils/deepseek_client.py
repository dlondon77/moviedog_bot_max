import re
import json
import requests
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

class DeepSeekClient:
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com/v1"):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    
    def split_opinion(self, text: str, rating: int = 0, 
                      hashtags: List[str] = None, 
                      atmosphere_hashtags: List[str] = None) -> List[str]:
        """Разбивает мнение на 5 смысловых блоков"""
        
        prompt = f"""Ты — КиноИщейка, собака-девочка, кинокритик с отличным чутьём. Разбей мнение на 5 смысловых блоков.

Твоё мнение:
{text}

Разбей на блоки для слайдов:
1. "О чём лай?" — сюжет
2. "Какая атмосфера?" — атмосфера
3. "Какая игра?" — актёры
4. "Что зарыто?" — смыслы
5. "Какой вердикт?" — итог

ПРАВИЛА:
- Каждый блок — 1-2 предложения (максимум 30 слов)
- Сохрани стиль и юмор КиноИщейки
- НЕ упоминай оценку в тексте

Верни JSON: {{"blocks": ["блок1", "блок2", "блок3", "блок4", "блок5"]}}"""

        try:
            data = {
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 600
            }
            
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=data,
                timeout=60
            )
            response.raise_for_status()
            
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                blocks = data.get("blocks", [])
                if len(blocks) >= 5:
                    return blocks[:5]
            
            return self._fallback_split(text)
            
        except Exception as e:
            logger.error(f"DeepSeek ошибка: {e}")
            return self._fallback_split(text)
    
    def generate_post(self, film_data: Dict, opinion_data: Dict, blocks: List[str]) -> str:
        """Генерирует пост для канала"""
        prompt = f"""Ты — КиноИщейка, собака-девочка, кинокритик. Напиши пост для Telegram-канала о фильме.

Информация:
Фильм: {film_data['title']} ({film_data['year']})
Страна: {film_data['country']}
Режиссёр: {film_data['director']}
Оценка: {opinion_data['rating']}/10

Блоки мнения:
{chr(10).join([f"{i+1}. {block}" for i, block in enumerate(blocks)])}

Напиши пост, который:
1. Начинается с яркого заголовка с эмодзи
2. Содержит краткое, но увлекательное мнение (3-4 предложения из блоков)
3. Заканчивается призывом: "Хочешь узнать моё мнение о фильме? Пиши мне — @MovieDog_bot! 🐕"
4. Добавь в конце хэштеги: #КиноИщейка #МнениеКиноИщейки #кино #обзор
5. Объем: 5-7 предложений"""

        try:
            data = {
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 500
            }
            
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=data,
                timeout=60
            )
            response.raise_for_status()
            
            result = response.json()
            post_text = result["choices"][0]["message"]["content"]
            
            if "MovieDog_bot" not in post_text:
                post_text += f"\n\n🐕 Хочешь узнать моё мнение о фильме? Пиши мне — @MovieDog_bot !"
            
            return post_text
            
        except Exception as e:
            logger.error(f"Ошибка генерации поста: {e}")
            return self._fallback_post(film_data, opinion_data, blocks)
    
    def _fallback_split(self, text: str) -> List[str]:
        """Запасной вариант разбивки"""
        sentences = re.split(r'[.!?]', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
        while len(sentences) < 5:
            sentences.append(sentences[-1] if sentences else "Нет данных")
        return [sentences[i] + "." for i in range(5)]
    
    def _fallback_post(self, film_data: Dict, opinion_data: Dict, blocks: List[str]) -> str:
        """Запасной вариант поста"""
        return f"""🎬 {film_data['title']} ({film_data['year']})

{blocks[0]}
{blocks[1]}
{blocks[2]}

⭐ Оценка: {opinion_data['rating']}/10

🐕 Хочешь узнать моё мнение о фильме? Пиши мне — @MovieDog_bot !

#КиноИщейка #МнениеКиноИщейки #кино #обзор"""
