"""
Обработчик диалогов с ИИ.

Использует ProxyAPI (совместим с OpenAI SDK) для анализа транскрибации
диалога с клиентом и возврата структурированных данных в формате JSON.

Обработка ошибок:
- Отсутствие/некорректность API-ключа
- Ошибки аутентификации и оплаты (401/402)
- Сетевые сбои и таймауты (с ретраями)
- Некорректный JSON в ответе модели (с ретраями)
- Неполный JSON (отсутствуют обязательные поля)
"""

import json
import logging
import os
import time
from typing import Any

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)

logger = logging.getLogger(__name__)

# Загружаем переменные окружения из .env файла
load_dotenv()

# Конфигурация
PROXYAPI_KEY = os.getenv("PROXYAPI_KEY", "")
PROXYAPI_MODEL = os.getenv("PROXYAPI_MODEL", "openai/gpt-5-mini")

# Настройки запроса
REQUEST_TIMEOUT = 60          # секунд на один запрос к API
MAX_RETRIES = 2               # доп. попытки при сетевых сбоях / битом JSON
RETRY_DELAY = 2               # секунд между попытками (растёт линейно)
MAX_COMPLETION_TOKENS = 1024  # лимит токенов ответа

# Обязательные поля JSON-ответа модели
REQUIRED_FIELDS = ("client_name", "topic", "main_request", "mood", "next_steps")

# Паузы между попытками: 2с, 4с
_RETRY_DELAYS = (RETRY_DELAY, RETRY_DELAY * 2)

# Дружественные сообщения для типовых ошибок ProxyAPI
_ERROR_HINTS = {
    AuthenticationError: "Неверный API-ключ. Проверьте PROXYAPI_KEY в .env.",
    PermissionDeniedError: "Доступ запрещён. Проверьте права ключа в console.proxyapi.ru.",
    RateLimitError: "Превышен лимит запросов или закончился баланс. Проверьте счёт в console.proxyapi.ru.",
    BadRequestError: "Некорректный запрос к API (возможно, модель не поддерживает заданные параметры).",
    APITimeoutError: f"API не ответил за {REQUEST_TIMEOUT} секунд.",
    APIConnectionError: "Не удалось соединиться с api.proxyapi.ru. Проверьте интернет.",
}


def _get_client() -> OpenAI:
    """
    Создаёт и возвращает клиент OpenAI, подключённый к ProxyAPI.

    Raises:
        ValueError: Если ключ отсутствует.
    """
    if not PROXYAPI_KEY:
        raise ValueError(
            "Отсутствует API-ключ ProxyAPI. "
            "Создайте файл .env и добавьте переменную PROXYAPI_KEY. "
            "См. .env.example"
        )

    logger.debug("Создание клиента ProxyAPI (timeout=%ss)", REQUEST_TIMEOUT)
    return OpenAI(
        api_key=PROXYAPI_KEY,
        base_url="https://api.proxyapi.ru/v1",
        timeout=REQUEST_TIMEOUT,
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
    распаршенный JSON-ответ со структурированными данными.

    Args:
        text: Полный текст транскрибации диалога.

    Returns:
        Словарь с ключами: client_name, topic, main_request, mood, next_steps.

    Raises:
        ValueError: Пустая транскрибация, нет ключа или невалидный ответ модели
            (все API-ошибки конвертируются в ValueError с дружественным текстом).
    """
    # --- Этап 1: Валидация входных данных ---
    if not text or not text.strip():
        logger.error("Получена пустая транскрибация — запрос к LLM не выполнялся")
        raise ValueError("Транскрибация пуста — нечего анализировать.")

    logger.info("Отправка транскрибации в LLM (модель: %s)...", PROXYAPI_MODEL)
    logger.debug("Длина текста: %d символов", len(text))

    # --- Этап 2: Создание клиента ---
    client = _get_client()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]

    # --- Этап 3: Запросы к API с ретраями ---
    last_error: Exception | None = None
    raw_content: str | None = None

    for attempt in range(1 + MAX_RETRIES):
        try:
            logger.info("Попытка %d/%d обращения к LLM...", attempt + 1, 1 + MAX_RETRIES)

            response = client.chat.completions.create(
                model=PROXYAPI_MODEL,
                messages=messages,
                max_completion_tokens=MAX_COMPLETION_TOKENS,
            )

            # Пустой ответ модели — тоже ошибка, требует повтора
            raw_content = response.choices[0].message.content
            if not raw_content or not raw_content.strip():
                raise ValueError("Модель вернула пустой ответ.")

            logger.info(
                "Получен ответ от LLM (попытка %d, %d символов).",
                attempt + 1,
                len(raw_content),
            )

            # --- Этап 4: Парсинг и валидация JSON ---
            parsed = _parse_llm_response(raw_content)
            _validate_fields(parsed)

            logger.info("JSON успешно распарсен и провалидирован: %s", list(parsed.keys()))
            return parsed

        except ValueError as e:
            # Пустой ответ, битый JSON или неполные поля — повторяем
            last_error = e
            logger.warning("Попытка %d/%d не удалась: %s",
                           attempt + 1, 1 + MAX_RETRIES, e)
            if attempt < MAX_RETRIES:
                delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                logger.info("Повторная попытка через %d сек...", delay)
                time.sleep(delay)

        except (APIConnectionError, APITimeoutError) as e:
            # Сетевые сбои — повторяем с нарастающей паузой
            last_error = e
            logger.error("Сетевая ошибка (попытка %d/%d): %s",
                         attempt + 1, 1 + MAX_RETRIES, e)
            if attempt < MAX_RETRIES:
                delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                logger.info("Повторная попытка через %d сек...", delay)
                time.sleep(delay)

        except AuthenticationError as e:
            # Неверный ключ — повторять бессмысленно
            logger.error("Ошибка аутентификации: %s", e)
            raise ValueError(_ERROR_HINTS[AuthenticationError]) from e

        except PermissionDeniedError as e:
            logger.error("Доступ запрещён: %s", e)
            raise ValueError(_ERROR_HINTS[PermissionDeniedError]) from e

        except RateLimitError as e:
            # Лимит/баланс — повторять бессмысленно до пополнения счёта
            logger.error("Превышен лимит запросов или не хватает средств: %s", e)
            raise ValueError(_ERROR_HINTS[RateLimitError]) from e

        except BadRequestError as e:
            # Ошибка в параметрах запроса — повторять бессмысленно
            logger.error("Некорректный запрос к API: %s", e)
            raise ValueError(f"{_ERROR_HINTS[BadRequestError]} Детали: {e}") from e

    # Исчерпаны все попытки
    if isinstance(last_error, (APIConnectionError, APITimeoutError)):
        hint = _ERROR_HINTS[type(last_error)]
        raise ValueError(f"{hint} После {1 + MAX_RETRIES} попыток.") from last_error

    preview = (raw_content or "")[:300]
    raise ValueError(
        f"Не удалось получить валидный JSON от ИИ за {1 + MAX_RETRIES} попыток. "
        f"Последний ответ модели: {preview}"
    ) from last_error


def _validate_fields(data: dict[str, Any]) -> None:
    """
    Проверяет наличие и непустоту обязательных полей JSON-ответа.

    Raises:
        ValueError: Если поле отсутствует или пустое.
    """
    missing = [f for f in REQUIRED_FIELDS if not str(data.get(f, "")).strip()]
    if missing:
        logger.warning("В JSON-ответе отсутствуют поля: %s", missing)
        raise ValueError(f"В JSON-ответе отсутствуют поля: {', '.join(missing)}")


def _parse_llm_response(content: str) -> dict[str, Any]:
    """
    Извлекает и парсит JSON из ответа LLM, убирая Markdown-обёртки.

    Raises:
        ValueError: Если JSON невалиден или не является объектом.
    """
    cleaned = _strip_markdown_fence(content.strip())
    logger.debug("Парсинг JSON (%d символов после очистки)", len(cleaned))

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning("Невалидный JSON от модели: %s", e)
        raise ValueError(f"Невалидный JSON в ответе модели: {e}") from e

    if not isinstance(data, dict):
        logger.warning("Модель вернула JSON, но не объект: %s", type(data).__name__)
        raise ValueError("Модель вернула JSON не-объект (ожидается словарь полей).")

    return data


def _strip_markdown_fence(text: str) -> str:
    """
    Убирает Markdown-обёртку ```json ... ``` если модель её добавила.
    """
    if not text.startswith("```"):
        return text

    lines = text.split("\n")
    cleaned_lines = []
    inside_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            if inside_fence:
                break  # закрывающая обёртка — конец JSON
            inside_fence = True  # открывающая обёртка — пропускаем
            continue
        if inside_fence:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()
