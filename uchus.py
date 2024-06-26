import logging
import requests
import asyncio
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from telegram.error import TimedOut, NetworkError

import aiohttp

import os

TOKEN = os.getenv('TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GAME_URL = os.getenv('GAME_URL')

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

async def start(update: Update, context: CallbackContext) -> None:
    keyboard = [
        [KeyboardButton("Задать вопрос спикеру"), KeyboardButton("Задать вопрос помощнику")],
        [KeyboardButton("Генерировать черно-белое изображение"), KeyboardButton("Играть в игру")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "Привет! Это бот конференции. Выберите действие:",
        reply_markup=reply_markup
    )
    context.user_data.clear()  # Очищаем данные пользователя при старте

async def handle_message(update: Update, context: CallbackContext) -> None:
    user_message = update.message.text

    if user_message == "Задать вопрос спикеру":
        await ask_speaker(update, context)
    elif user_message == "Задать вопрос помощнику":
        context.user_data['state'] = 'waiting_for_ai_question'
        await update.message.reply_text("Введите свой вопрос для помощника (ИИ)")
    elif user_message == "Генерировать черно-белое изображение":
        context.user_data['state'] = 'waiting_for_image_prompt'
        await update.message.reply_text("Введите описание для генерации черно-белого изображения")
    elif user_message == "Играть в игру":
        await send_game(update, context)
    elif context.user_data.get('state') == 'waiting_for_ai_question':
        await handle_ai_response(update, context)
    elif context.user_data.get('state') == 'waiting_for_image_prompt':
        await handle_image_generation(update, context)
    elif context.user_data.get('state') == 'waiting_for_hall':
        await process_hall_selection(update, context)
    elif context.user_data.get('state') == 'waiting_for_speaker_question':
        await send_question_to_django(update, context)
    else:
        await update.message.reply_text("Пожалуйста, выберите действие с помощью кнопок.")

async def send_game(update: Update, context: CallbackContext) -> None:
    keyboard = [[InlineKeyboardButton("Играть в Skipper", url=GAME_URL)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Нажмите кнопку ниже, чтобы играть в игру:", reply_markup=reply_markup)

async def ask_speaker(update: Update, context: CallbackContext) -> None:
    halls = ["Зал 1", "Зал 2", "Зал 3", "Зал 4"]
    keyboard = [[KeyboardButton(halls[i]), KeyboardButton(halls[i+1])] for i in range(0, len(halls), 2)]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("Выберите зал, в котором вы находитесь:", reply_markup=reply_markup)
    context.user_data['state'] = 'waiting_for_hall'

async def process_hall_selection(update: Update, context: CallbackContext) -> None:
    selected_hall = update.message.text
    if selected_hall in ["Зал 1", "Зал 2", "Зал 3", "Зал 4"]:
        context.user_data['selected_hall'] = selected_hall
        context.user_data['state'] = 'waiting_for_speaker_question'
        await update.message.reply_text(f"Вы выбрали {selected_hall}. Теперь введите ваш вопрос для спикера:")
    else:
        await update.message.reply_text("Пожалуйста, выберите зал из предложенных вариантов.")

async def send_question_to_django(update: Update, context: CallbackContext) -> None:
    user_message = update.message.text
    hall = context.user_data.get('selected_hall')
    
    if not hall:
        await update.message.reply_text("Пожалуйста, сначала выберите зал.")
        return

    name = update.message.from_user.full_name or 'Anonymous'

    # Отправка вопроса на сервер Django
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post('http://127.0.0.1:8000/api/questions/', json={
                'name': name,
                'questions': user_message,
                'hall': hall
            }) as response:
                response.raise_for_status()  # Вызовет исключение для неуспешных статус-кодов
                await update.message.reply_text(
                    f"Спасибо за вопрос. Спикер ответит на него в конце выступления."
                )
    except aiohttp.ClientError as e:
        logger.error(f"Ошибка при отправке вопроса на Django: {e}")
        await update.message.reply_text(
            f"Произошла ошибка при отправке вашего вопроса. Пожалуйста, попробуйте еще раз позже."
        )

    # Возвращаем клавиатуру с основными опциями
    await return_to_main_menu(update, context)

async def ask_helper(update: Update, context: CallbackContext) -> None:
    context.user_data['state'] = 'waiting_for_ai_question'
    await update.message.reply_text("Введите свой вопрос для помощника (ИИ)")

async def handle_ai_response(update: Update, context: CallbackContext) -> None:
    user_message = update.message.text

    # Используем OpenAI API
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    prompt = f"Ответь на следующий вопрос подробно и сжато, закончи сообщение точкой и обязательно уложись в 500 символов(это обязательное требование):\n{user_message}"
    payload = {
        "model": "gpt-4",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 500,
        "temperature": 0.7
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                response.raise_for_status()  # Вызовет исключение для неуспешных статус-кодов
                result = await response.json()

            logger.info(f"Response from OpenAI: {result}")
            if "choices" in result and len(result["choices"]) > 0:
                ai_response = result["choices"][0]["message"]["content"]
                await update.message.reply_text(f"Ответ помощника:\n\n{ai_response}")
            else:
                raise ValueError(f"Unexpected response format: {result}")
    except (aiohttp.ClientError, ValueError) as e:
        logger.error(f"Ошибка при получении ответа от ИИ: {e}")
        await update.message.reply_text(
            f"Извините, произошла ошибка при получении ответа от ИИ. Попробуйте еще раз позже."
        )

    # Возвращаем клавиатуру с основными опциями
    await return_to_main_menu(update, context)

async def generate_image(update: Update, context: CallbackContext) -> None:
    context.user_data['state'] = 'waiting_for_image_prompt'
    await update.message.reply_text("Введите описание для генерации черно-белого изображения")

async def handle_image_generation(update: Update, context: CallbackContext) -> None:
    user_message = update.message.text

    # Сообщение об ожидании
    waiting_message = await update.message.reply_text("Пожалуйста, подождите. Изображение генерится...")

    # Используем OpenAI API для генерации изображений
    url = "https://api.openai.com/v1/images/generations"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    prompt = f"Сделай 3D картинку в стиле комикса: {user_message}"
    payload = {
        "prompt": prompt,
        "n": 1,
        "size": "512x512"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                response.raise_for_status()  # Вызовет исключение для неуспешных статус-кодов
                result = await response.json()

            logger.info(f"Response from OpenAI: {result}")
            if "data" in result and len(result["data"]) > 0:
                image_url = result["data"][0]["url"]
                await update.message.reply_photo(image_url)
            else:
                raise ValueError(f"Unexpected response format: {result}")
    except (aiohttp.ClientError, ValueError) as e:
        logger.error(f"Ошибка при получении изображения: {e}")
        await update.message.reply_text(
            f"Извините, произошла ошибка при получении изображения. Попробуйте еще раз позже."
        )

    # Удаляем сообщение об ожидании
    await context.bot.delete_message(chat_id=update.message.chat_id, message_id=waiting_message.message_id)

    # Возвращаем клавиатуру с основными опциями
    await return_to_main_menu(update, context)

async def return_to_main_menu(update: Update, context: CallbackContext) -> None:
    keyboard = [
        [KeyboardButton("Задать вопрос спикеру")],
        [KeyboardButton("Задать вопрос помощнику")],
        [KeyboardButton("Генерировать черно-белое изображение")],
        [KeyboardButton("Играть в игру")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Выберите следующее действие:", reply_markup=reply_markup)
    context.user_data.clear()  # Очищаем данные пользователя при возврате в главное меню

async def handle_ai(update: Update, context: CallbackContext) -> None:
    context.user_data['state'] = 'waiting_for_ai_question'
    await update.message.reply_text("Введите свой вопрос для помощника (ИИ)")

async def handle_generate_photo(update: Update, context: CallbackContext) -> None:
    context.user_data['state'] = 'waiting_for_image_prompt'
    await update.message.reply_text("Введите описание для генерации черно-белого изображения")

async def main() -> None:
    while True:
        try:
            application = Application.builder().token(TOKEN).build()

            application.add_handler(CommandHandler("start", start))
            application.add_handler(CommandHandler("ask_speaker", ask_speaker))
            application.add_handler(CommandHandler("ask_helper", ask_helper))
            application.add_handler(CommandHandler("generate_image", generate_image))
            application.add_handler(CommandHandler("ask_ai", handle_ai))
            application.add_handler(CommandHandler("generate_photo", handle_generate_photo))
            application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

            await application.initialize()
            print("Бот успешно запущен!")
            await application.start()
            await application.run_polling()
        except (TimedOut, NetworkError) as e:
            print(f"Произошла сетевая ошибка: {e}. Повторная попытка через 10 секунд...")
            await asyncio.sleep(10)
        except Exception as e:
            print(f"Произошла ошибка: {e}. Перезапуск бота через 30 секунд...")
            await asyncio.sleep(30)

if __name__ == '__main__':
    asyncio.run(main())