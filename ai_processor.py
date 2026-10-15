"""
Обработчик диалогов с ИИ.

Использует ProxyAPI (совместим с OpenAI SDK) для анализа транскрибации
диалога с клиентом и возврата структурированных данных в формате JSON.
"""

import json
import logging
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

logger = logging.getLogger(__name__)

# Загружаем переменные окружения из .env файла
load_dotenv()

# Конфигурация
PROXYAPI_KEY = os.getenv("PROXYAPI_KEY", "")
PROXYAPI_MODEL = os.getenv("PROXYAPI_MODEL", "openai/gpt-5-mini")


def _get_client() -> OpenAI:
    """Создаёт и возвращает клиент OpenAI, подключённый к ProxyAPI."""
    if not PROXYAPI_KEY:
        raise ValueError(
            "Отсутствует API-ключ ProxyAPI. "
            "Создайте файл .env и добавьте переменную PROXYAPI_KEY. "
            "См. .env.example"
        )

    return OpenAI(
        api_key=PROXYAPI_KEY,
        base_url="https://api.proxyapi.ru/v1",
    )


SYSTEM_PROMPT = """\
Ты — аналитик качества клиентского сервиса. Твоя задача — проанализировать \
транскрибацию диалога оператора с клиентом и вернуть строго структурированные \
данные в формате JSON.

Верни ТОЛЬКО валидный JSON-объект со следующими полями:
- "client_name": Имя или описание клиента (если имя не названо — "Не указано")
- "topic": Краткая тема обращения (3-5 слов)
- "main_request": Основной запрос клиента (1-2 предложения)
- "mood": Настроение клиента — "Позитивное", "Нейтральное" или "Негативное"
- "next_steps": Перечислите следующие шаги для работы с клиентом \
(каждый шаг с новой строки, начинается с номера и тире)

Важно: верни только JSON без Markdown-обёрток (без ````json ... ````), \
без дополнительных текстов или объяснений.
"""


def process_dialog_with_ai(text: str) -> dict[str, Any]:
    """
    Отправляет транскрибацию диалога в LLM через ProxyAPI и возвращает
    распаршенный JSON-ответ с структурированными данными.

    Args:
        text: Полный текст транскрибации диалога.

    Returns:
        Словарь с ключами: client_name, topic, main_request, mood, next_steps.

    Raises:
        ValueError: Если отсутствует API-ключ или ответ невалиден.
        Exception: Ошибки сети или API.
    """
    if not text or not text.strip():
        raise ValueError("Транскрибация пуста — нечего анализировать.")

    logger.info("Отправка транскрибации в LLM (модель: %s)...", PROXYAPI_MODEL)
    logger.debug("Длина текста: %d символов", len(text))

    client = _get_client()

    max_retries = 2
    for attempt in range(1 + max_retries):
        try:
            response = client.chat.completions.create(
                model=PROXYAPI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                max_completion_tokens=1024,
            )

            raw_content = response.choices[0].message.content
            logger.info("Получен ответ от LLM (попытка %d).", attempt + 1)

            parsed = _parse_llm_response(raw_content)
            logger.info("JSON успешно распарсен: %s", list(parsed.keys()))
            return parsed

        except json.JSONDecodeError as e:
            logger.warning(
                "Ошибка парсинга JSON (попытка %d/%d): %s",
                attempt + 1,
                1 + max_retries,
                e,
            )
            if attempt == max_retries:
                raise ValueError(
                    "Не удалось распарсить ответ ИИ. "
                    f"Содержимое ответа: {raw_content[:500]}"
                ) from e
        except Exception as e:
            logger.error("Ошибка при вызове LLM: %s", e, exc_info=True)
            if attempt == max_retries:
                raise
            logger.info("Повторная попытка через 2 секунды...")
            import time
            time.sleep(2)

    # Не должно достигаться, но для безопасности
    raise ValueError("Исчерпаны все попытки обращения к LLM.")


def _parse_llm_response(content: str) -> dict[str, Any]:
    """
    Извлекает и парсит JSON из ответа LLM, убирая Markdown-обёртки.
    """
    cleaned = content.strip()

    # Убираем ```json ... ``` если есть
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned_lines = []
        skip_next = False
        for line in lines:
            if line.strip().startswith("```"):
                if skip_next:
                    break
                skip_next = True
                continue
            if skip_next:
                cleaned_lines.append(line)
        cleaned = "\n".join(cleaned_lines).strip()

    return json.loads(cleaned)
