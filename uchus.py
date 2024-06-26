import logging
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

import aiohttp
import os

TOKEN = os.getenv('TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GAME_URL = os.getenv('GAME_URL')

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Определение состояний
class BotStates(StatesGroup):
    WAITING_FOR_AI_QUESTION = State()
    WAITING_FOR_IMAGE_PROMPT = State()
    WAITING_FOR_HALL = State()
    WAITING_FOR_SPEAKER_QUESTION = State()

# Клавиатура главного меню
main_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
main_keyboard.row(KeyboardButton("Задать вопрос спикеру"), KeyboardButton("Задать вопрос помощнику"))
main_keyboard.row(KeyboardButton("Генерировать черно-белое изображение"), KeyboardButton("Играть в игру"))

# Клавиатура выбора зала
hall_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
hall_keyboard.row(KeyboardButton("Зал 1"), KeyboardButton("Зал 2"))
hall_keyboard.row(KeyboardButton("Зал 3"), KeyboardButton("Зал 4"))

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    logger.info(f"Получена команда /start от {message.from_user.id}")
    await message.reply("Привет! Это бот конференции. Выберите действие:", reply_markup=main_keyboard)

@dp.message_handler(commands=['ask_ai', 'ask_speaker', 'generate_photo'], state="*")
async def cancel_current_state(message: types.Message, state: FSMContext):
    logger.info(f"Команда {message.text} получена, завершаем текущее состояние")
    await state.finish()

    # Выполнение соответствующей команды после завершения состояния
    if message.text == "/ask_ai":
        await ask_ai_command(message)
    elif message.text == "/ask_speaker":
        await ask_speaker_command(message)
    elif message.text == "/generate_photo":
        await generate_photo_command(message)

@dp.message_handler(commands=['ask_ai'])
async def ask_ai_command(message: types.Message):
    logger.info(f"Получена команда /ask_ai от {message.from_user.id}")
    await ask_ai(message)

@dp.message_handler(commands=['ask_speaker'])
async def ask_speaker_command(message: types.Message):
    logger.info(f"Получена команда /ask_speaker от {message.from_user.id}")
    await ask_speaker(message)

@dp.message_handler(commands=['generate_photo'])
async def generate_photo_command(message: types.Message):
    logger.info(f"Получена команда /generate_photo от {message.from_user.id}")
    await generate_image_prompt(message)

@dp.message_handler(lambda message: message.text == "Задать вопрос спикеру")
async def ask_speaker(message: types.Message, state: FSMContext):
    await state.finish()  # Завершаем текущее состояние
    logger.info(f"Получена команда 'Задать вопрос спикеру' от {message.from_user.id}")
    await message.reply("Выберите зал, в котором вы находитесь:", reply_markup=hall_keyboard)
    await BotStates.WAITING_FOR_HALL.set()

@dp.message_handler(state=BotStates.WAITING_FOR_HALL)
async def process_hall_selection(message: types.Message, state: FSMContext):
    logger.info(f"Пользователь {message.from_user.id} выбрал зал: {message.text}")
    if message.text in ["Зал 1", "Зал 2", "Зал 3", "Зал 4"]:
        await state.update_data(selected_hall=message.text)
        await message.reply(f"Вы выбрали {message.text}. Теперь введите ваш вопрос для спикера:")
        await BotStates.WAITING_FOR_SPEAKER_QUESTION.set()
    else:
        await message.reply("Пожалуйста, выберите зал из предложенных вариантов.")

@dp.message_handler(state=BotStates.WAITING_FOR_SPEAKER_QUESTION)
async def send_question_to_django(message: types.Message, state: FSMContext):
    logger.info(f"Пользователь {message.from_user.id} задал вопрос: {message.text}")
    user_data = await state.get_data()
    hall = user_data.get('selected_hall')
    
    if not hall:
        await message.reply("Пожалуйста, сначала выберите зал.")
        return

    name = message.from_user.full_name or 'Anonymous'

    # Отправка вопроса на сервер Django
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post('http://127.0.0.1:8000/api/questions/', json={
                'name': name,
                'questions': message.text,
                'hall': hall
            }) as response:
                response.raise_for_status()
                await message.reply("Спасибо за вопрос. Спикер ответит на него в конце выступления.")
    except aiohttp.ClientError as e:
        logger.error(f"Ошибка при отправке вопроса на Django: {e}")
        await message.reply("Произошла ошибка при отправке вашего вопроса. Пожалуйста, попробуйте еще раз позже.")

    await state.finish()
    await message.reply("Выберите следующее действие:", reply_markup=main_keyboard)

@dp.message_handler(lambda message: message.text == "Задать вопрос помощнику")
async def ask_ai(message: types.Message, state: FSMContext):
    await state.finish()  # Завершаем текущее состояние
    logger.info(f"Получена команда 'Задать вопрос помощнику' от {message.from_user.id}")
    await message.reply("Введите свой вопрос для помощника (ИИ)")
    await BotStates.WAITING_FOR_AI_QUESTION.set()

@dp.message_handler(state=BotStates.WAITING_FOR_AI_QUESTION)
async def handle_ai_response(message: types.Message, state: FSMContext):
    logger.info(f"Пользователь {message.from_user.id} задал вопрос ИИ: {message.text}")
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    prompt = f"Ответь на следующий вопрос подробно и сжато, закончи сообщение точкой и обязательно уложись в 500 символов(это обязательное требование):\n{message.text}"
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
                response.raise_for_status()
                result = await response.json()

            logger.info(f"Response from OpenAI: {result}")
            if "choices" in result and len(result["choices"]) > 0:
                ai_response = result["choices"][0]["message"]["content"]
                await message.reply(f"Ответ помощника:\n\n{ai_response}")
            else:
                raise ValueError(f"Unexpected response format: {result}")
    except (aiohttp.ClientError, ValueError) as e:
        logger.error(f"Ошибка при получении ответа от ИИ: {e}")
        await message.reply("Извините, произошла ошибка при получении ответа от ИИ. Попробуйте еще раз позже.")

    await state.finish()
    await message.reply("Выберите следующее действие:", reply_markup=main_keyboard)

@dp.message_handler(lambda message: message.text == "Генерировать черно-белое изображение")
async def generate_image_prompt(message: types.Message, state: FSMContext):
    await state.finish()  # Завершаем текущее состояние
    logger.info(f"Получена команда 'Генерировать черно-белое изображение' от {message.from_user.id}")
    await message.reply("Введите описание для генерации черно-белого изображения")
    await BotStates.WAITING_FOR_IMAGE_PROMPT.set()

@dp.message_handler(state=BotStates.WAITING_FOR_IMAGE_PROMPT)
async def handle_image_generation(message: types.Message, state: FSMContext):
    logger.info(f"Пользователь {message.from_user.id} запросил генерацию изображения: {message.text}")
    waiting_message = await message.reply("Пожалуйста, подождите. Изображение генерится...")

    url = "https://api.openai.com/v1/images/generations"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    prompt = f"Сделай 3D картинку в стиле комикса: {message.text}"
    payload = {
        "prompt": prompt,
        "n": 1,
        "size": "512x512"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                response.raise_for_status()
                result = await response.json()

            logger.info(f"Response from OpenAI: {result}")
            if "data" in result and len(result["data"]) > 0:
                image_url = result["data"][0]["url"]
                await message.reply_photo(image_url)
            else:
                raise ValueError(f"Unexpected response format: {result}")
    except (aiohttp.ClientError, ValueError) as e:
        logger.error(f"Ошибка при получении изображения: {e}")
        await message.reply("Извините, произошла ошибка при получении изображения. Попробуйте еще раз позже.")

    await bot.delete_message(chat_id=message.chat.id, message_id=waiting_message.message_id)
    await state.finish()
    await message.reply("Выберите следующее действие:", reply_markup=main_keyboard)

@dp.message_handler(lambda message: message.text == "Играть в игру")
async def play_game(message: types.Message, state: FSMContext):
    await state.finish()  # Завершаем текущее состояние
    logger.info(f"Получена команда 'Играть в игру' от {message.from_user.id}")
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("Играть в Skipper", url=GAME_URL))
    await message.reply("Нажмите кнопку ниже, чтобы играть в игру:", reply_markup=keyboard)

async def main():
    while True:
        try:
            await dp.start_polling()
        except Exception as e:
            logger.error(f"Произошла ошибка: {e}. Перезапуск через 5 секунд...")
            await asyncio.sleep(5)

if __name__ == '__main__':
    asyncio.run(main())