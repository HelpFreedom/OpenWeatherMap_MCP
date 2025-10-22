#!/usr/bin/env python3
"""
Клиент для взаимодействия с MCP сервером погоды через OpenAI GPT-4o-mini
"""

import os
import asyncio
import json
from dotenv import load_dotenv
from openai import OpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Загружаем переменные окружения
load_dotenv()

# Инициализируем клиент OpenAI
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def main():
    """
    Основная функция для запуска клиента
    """
    # Параметры для запуска MCP сервера через STDIO
    server_params = StdioServerParameters(
        command="python3",  # Команда для запуска
        args=["server.py"],  # Аргументы (путь к серверу)
        env=None  # Переменные окружения (используем текущие)
    )
    
    print("🚀 Запуск MCP клиента...")
    print("=" * 60)
    
    # Подключаемся к MCP серверу
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Инициализируем сессию
            await session.initialize()
            
            print("✅ Подключено к MCP серверу погоды")
            print("=" * 60)
            
            # Получаем список доступных инструментов с сервера
            tools_list = await session.list_tools()
            print(f"\n📋 Доступные инструменты ({len(tools_list.tools)}):")
            for tool in tools_list.tools:
                print(f"  • {tool.name}: {tool.description}")
            print()
            
            # Преобразуем MCP инструменты в формат OpenAI
            openai_tools = convert_mcp_tools_to_openai(tools_list.tools)
            
            # История сообщений для контекста
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Ты полезный ассистент, который помогает пользователям "
                        "узнать погоду в любом городе. У тебя есть доступ к "
                        "инструментам для получения текущей погоды и прогноза. "
                        "Всегда отвечай на русском языке."
                    )
                }
            ]
            
            print("💬 Чат запущен! Спрашивайте о погоде (введите 'выход' для завершения)")
            print("=" * 60)
            
            # Основной цикл общения
            while True:
                # Получаем ввод пользователя
                user_input = input("\n👤 Вы: ").strip()
                
                # Проверка на выход
                if user_input.lower() in ["выход", "exit", "quit", "q"]:
                    print("\n👋 До свидания!")
                    break
                
                if not user_input:
                    continue
                
                # Добавляем сообщение пользователя в историю
                messages.append({
                    "role": "user",
                    "content": user_input
                })
                
                # Флаг для отслеживания завершения обработки
                final_response = await process_conversation(
                    messages, 
                    openai_tools, 
                    session
                )
                
                # Выводим финальный ответ
                print(f"\n🤖 Ассистент: {final_response}")


async def process_conversation(messages: list, tools: list, session: ClientSession) -> str:
    """
    Обрабатывает разговор с возможными вызовами инструментов
    
    Args:
        messages: История сообщений
        tools: Список инструментов в формате OpenAI
        session: Сессия MCP клиента
        
    Returns:
        Финальный ответ ассистента
    """
    # Максимум 5 итераций для предотвращения бесконечных циклов
    max_iterations = 5
    
    for iteration in range(max_iterations):
        # Запрос к OpenAI GPT-4o-mini
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",  # Используем модель gpt-4o-mini
            messages=messages,
            tools=tools,  # Передаем доступные инструменты
            tool_choice="auto"  # Модель сама решает, нужны ли инструменты
        )
        
        # Получаем ответ ассистента
        assistant_message = response.choices[0].message
        
        # Добавляем ответ ассистента в историю
        messages.append({
            "role": "assistant",
            "content": assistant_message.content,
            "tool_calls": assistant_message.tool_calls
        })
        
        # Если модель не вызывает инструменты, возвращаем ответ
        if not assistant_message.tool_calls:
            return assistant_message.content or "Извините, я не смог сформировать ответ."
        
        # Обрабатываем вызовы инструментов
        print("\n⚙️ Вызов инструментов...")
        
        for tool_call in assistant_message.tool_calls:
            # Информация о вызове инструмента
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            
            print(f"  🔧 {function_name}({', '.join(f'{k}={v}' for k, v in function_args.items())})")
            
            # Вызываем инструмент через MCP
            try:
                result = await session.call_tool(function_name, function_args)
                
                # Получаем текстовый результат
                if result.content:
                    tool_result = result.content[0].text if result.content else "Нет результата"
                else:
                    tool_result = "Инструмент выполнен, но результат пуст"
                
            except Exception as e:
                tool_result = f"Ошибка при вызове инструмента: {str(e)}"
            
            # Добавляем результат инструмента в историю
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result
            })
    
    # Если достигли максимума итераций
    return "Извините, обработка заняла слишком много времени."


def convert_mcp_tools_to_openai(mcp_tools) -> list:
    """
    Конвертирует MCP инструменты в формат OpenAI
    
    Args:
        mcp_tools: Список инструментов от MCP сервера
        
    Returns:
        Список инструментов в формате OpenAI
    """
    openai_tools = []
    
    for tool in mcp_tools:
        # Формируем описание инструмента для OpenAI
        openai_tool = {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "Инструмент без описания",
                "parameters": tool.inputSchema  # JSON Schema параметров
            }
        }
        openai_tools.append(openai_tool)
    
    return openai_tools


# Запуск клиента
if __name__ == "__main__":
    try:
        # Запускаем асинхронную функцию
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Программа прервана пользователем")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
