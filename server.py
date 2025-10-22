#!/usr/bin/env python3
"""
MCP Сервер для получения погоды через OpenWeatherMap API
"""

import os
import logging
from typing import Any
import httpx
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# Загружаем переменные окружения из файла .env
load_dotenv()

# Настраиваем логирование (важно для STDIO серверов - не использовать print!)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Создаем экземпляр MCP сервера с именем "weather"
mcp = FastMCP("weather")

# Константы для работы с API
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
OPENWEATHER_BASE_URL = "https://api.openweathermap.org/data/2.5"


async def make_weather_request(endpoint: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """
    Вспомогательная функция для выполнения запросов к OpenWeatherMap API
    
    Args:
        endpoint: Конечная точка API (например, "weather" или "forecast")
        params: Параметры запроса
        
    Returns:
        JSON ответ от API или None в случае ошибки
    """
    # Проверяем наличие API ключа
    if not OPENWEATHER_API_KEY:
        logger.error("OPENWEATHER_API_KEY не найден в переменных окружения")
        return None
    
    # Добавляем API ключ к параметрам запроса
    params["appid"] = OPENWEATHER_API_KEY
    # Устанавливаем метрическую систему (Цельсий, метры/сек)
    params["lang"] = "ru"  # Русский язык для описаний
    
    # Формируем полный URL
    url = f"{OPENWEATHER_BASE_URL}/{endpoint}"
    
    try:
        # Выполняем асинхронный HTTP запрос
        async with httpx.AsyncClient() as client:
            logger.info(f"Запрос к API: {url}")
            response = await client.get(url, params=params, timeout=30.0)
            response.raise_for_status()  # Вызовет исключение при ошибке HTTP
            return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP ошибка: {e.response.status_code} - {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"Ошибка при запросе к API: {str(e)}")
        return None


@mcp.tool()
async def get_current_weather(city: str, units: str = "metric") -> str:
    """
    Получить текущую погоду для указанного города
    
    Args:
        city: Название города на русском или английском (например, "Москва" или "Moscow")
        units: Система измерения - "metric" (Цельсий) или "imperial" (Фаренгейт)
    
    Returns:
        Строка с описанием текущей погоды
    """
    logger.info(f"Запрос погоды для города: {city}")
    
    # Формируем параметры запроса
    params = {
        "q": city,
        "units": units
    }
    
    # Выполняем запрос к API
    data = await make_weather_request("weather", params)
    
    # Обработка ошибок
    if not data:
        return f"❌ Не удалось получить погоду для города '{city}'. Проверьте название города."
    
    if "cod" in data and data["cod"] != 200:
        return f"❌ Ошибка API: {data.get('message', 'Неизвестная ошибка')}"
    
    # Извлекаем данные из ответа
    try:
        # Основная информация
        main = data["main"]
        weather = data["weather"][0]
        wind = data["wind"]
        
        # Символ температуры в зависимости от системы измерения
        temp_unit = "°C" if units == "metric" else "°F"
        wind_unit = "м/с" if units == "metric" else "миль/ч"
        
        # Форматируем ответ
        result = f"""
🌍 Погода в городе {data['name']}, {data['sys']['country']}

🌡️ Температура: {main['temp']:.1f}{temp_unit}
🤔 Ощущается как: {main['feels_like']:.1f}{temp_unit}
📊 Мин/Макс: {main['temp_min']:.1f}{temp_unit} / {main['temp_max']:.1f}{temp_unit}

☁️ Условия: {weather['description'].capitalize()}
💧 Влажность: {main['humidity']}%
🎚️ Давление: {main['pressure']} гПа
💨 Ветер: {wind['speed']} {wind_unit}, направление {wind.get('deg', 'н/д')}°
        """.strip()
        
        logger.info(f"Успешно получена погода для {city}")
        return result
        
    except KeyError as e:
        logger.error(f"Ошибка при обработке данных: {e}")
        return f"❌ Ошибка при обработке данных о погоде: {str(e)}"


@mcp.tool()
async def get_forecast(city: str, days: int = 3, units: str = "metric") -> str:
    """
    Получить прогноз погоды на несколько дней
    
    Args:
        city: Название города на русском или английском
        days: Количество дней для прогноза (1-5)
        units: Система измерения - "metric" (Цельсий) или "imperial" (Фаренгейт)
    
    Returns:
        Строка с прогнозом погоды
    """
    logger.info(f"Запрос прогноза для города: {city} на {days} дней")
    
    # Ограничиваем количество дней
    days = min(max(days, 1), 5)
    
    # Формируем параметры запроса
    params = {
        "q": city,
        "units": units,
        "cnt": days * 8  # API возвращает данные каждые 3 часа, 8 записей = 1 день
    }
    
    # Выполняем запрос к API
    data = await make_weather_request("forecast", params)
    
    # Обработка ошибок
    if not data:
        return f"❌ Не удалось получить прогноз для города '{city}'."
    
    if "cod" not in data or data["cod"] != "200":
        return f"❌ Ошибка API: {data.get('message', 'Неизвестная ошибка')}"
    
    try:
        # Символы температуры
        temp_unit = "°C" if units == "metric" else "°F"
        
        # Группируем данные по дням
        forecasts = []
        current_date = None
        day_data = []
        
        for item in data["list"]:
            # Извлекаем дату
            date = item["dt_txt"].split()[0]
            
            if current_date != date:
                # Если накопили данные за день, обрабатываем их
                if day_data:
                    forecasts.append(format_day_forecast(day_data, temp_unit))
                    if len(forecasts) >= days:
                        break
                
                # Начинаем новый день
                current_date = date
                day_data = [item]
            else:
                day_data.append(item)
        
        # Обрабатываем последний день
        if day_data and len(forecasts) < days:
            forecasts.append(format_day_forecast(day_data, temp_unit))
        
        # Формируем итоговый ответ
        result = f"📅 Прогноз погоды для {data['city']['name']}, {data['city']['country']}\n\n"
        result += "\n\n".join(forecasts)
        
        logger.info(f"Успешно получен прогноз для {city}")
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при обработке прогноза: {e}")
        return f"❌ Ошибка при обработке данных прогноза: {str(e)}"


def format_day_forecast(day_data: list, temp_unit: str) -> str:
    """
    Форматирует прогноз на один день
    
    Args:
        day_data: Список данных о погоде за день (каждые 3 часа)
        temp_unit: Символ единицы температуры
        
    Returns:
        Отформатированная строка с прогнозом
    """
    # Берем первую запись для даты
    date = day_data[0]["dt_txt"].split()[0]
    
    # Вычисляем средние значения
    temps = [item["main"]["temp"] for item in day_data]
    avg_temp = sum(temps) / len(temps)
    min_temp = min(temps)
    max_temp = max(temps)
    
    # Самое частое описание погоды
    descriptions = [item["weather"][0]["description"] for item in day_data]
    most_common_desc = max(set(descriptions), key=descriptions.count)
    
    # Средняя влажность и ветер
    avg_humidity = sum(item["main"]["humidity"] for item in day_data) / len(day_data)
    avg_wind = sum(item["wind"]["speed"] for item in day_data) / len(day_data)
    
    return f"""
📆 {date}
🌡️ Средняя температура: {avg_temp:.1f}{temp_unit}
📊 Мин/Макс: {min_temp:.1f}{temp_unit} / {max_temp:.1f}{temp_unit}
☁️ Условия: {most_common_desc.capitalize()}
💧 Влажность: {avg_humidity:.0f}%
💨 Ветер: {avg_wind:.1f} м/с
    """.strip()


# Запуск сервера
if __name__ == "__main__":
    logger.info("Запуск MCP сервера погоды...")
    # Запускаем сервер через STDIO (стандартный ввод/вывод)
    mcp.run(transport="stdio")
