import os
import asyncio
import logging
import random
from PIL import Image, ImageFilter, ImageEnhance
import aiohttp

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY)

print("=== БОТ ЗАПУЩЕН ===")

def get_main_keyboard():
    buttons = [
        [KeyboardButton("💬 Общий чат")],
        [KeyboardButton("🖼 Создать фото"), KeyboardButton("📝 Создать песню")],
        [KeyboardButton("✏️ Редактировать фото"), KeyboardButton("🔍 Анализ фото")],
        [KeyboardButton("👁️ Найти объекты"), KeyboardButton("📖 Распознать текст")],
        [KeyboardButton("🗑 Очистить историю"), KeyboardButton("❓ Помощь")]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def get_edit_keyboard():
    buttons = [
        [KeyboardButton("⚫ Черно-белое"), KeyboardButton("🌀 Размытие")],
        [KeyboardButton("✨ Контраст"), KeyboardButton("☀️ Ярче")],
        [KeyboardButton("🎭 Негатив"), KeyboardButton("◀️ Назад")]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

user_sessions = {}
MAX_HISTORY = 10

def get_history(user_id):
    if user_id not in user_sessions:
        user_sessions[user_id] = []
    return user_sessions[user_id]

def add_to_history(user_id, role, content):
    history = get_history(user_id)
    history.append({"role": role, "content": content})
    if len(history) > MAX_HISTORY:
        user_sessions[user_id] = history[-MAX_HISTORY:]

def clear_history(user_id):
    if user_id in user_sessions:
        user_sessions[user_id] = []

# --- Генерация фото ---
async def generate_photo(prompt: str) -> str:
    encoded = prompt.replace(" ", "%20").replace("?", "%3F").replace("!", "%21")
    return f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&model=flux&nologo=true"

# --- OpenRouter вызов (универсальный) ---
async def call_openrouter(model: str, messages: list) -> str:
    if not OPENROUTER_API_KEY:
        return "❌ OpenRouter API ключ не настроен"
    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://t.me/bot",
            "X-Title": "TelegramBot"
        }
        data = {
            "model": model,
            "messages": messages,
            "max_tokens": 800
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data, headers=headers) as resp:
                if resp.status != 200:
                    return f"❌ Ошибка API (статус {resp.status})"
                result = await resp.json()
                return result["choices"][0]["message"]["content"]
    except Exception as e:
        return f"❌ Ошибка: {str(e)[:100]}"

# --- Песня ---
async def generate_song_lyrics(topic: str) -> str:
    prompt = f"Напиши текст песни на русском языке на тему: {topic}. Только текст песни, без лишних слов."
    return await call_openrouter(
        "meta-llama/llama-3.1-8b-instruct:free",
        [{"role": "user", "content": prompt}]
    )

# --- Анализ фото, поиск объектов, текст (GPT-4o-mini работает идеально) ---
async def analyze_photo(photo_url: str) -> str:
    return await call_openrouter(
        "openai/gpt-4o-mini",
        [{"role": "user", "content": f"Опиши подробно это фото на русском языке: {photo_url}"}]
    )

async def describe_objects(photo_url: str) -> str:
    result = await call_openrouter(
        "openai/gpt-4o-mini",
        [{"role": "user", "content": f"Перечисли все объекты на этом фото на русском языке списком: {photo_url}"}]
    )
    return f"👁️ *Найденные объекты:*\n{result}"

async def extract_text_from_photo(photo_url: str) -> str:
    result = await call_openrouter(
        "openai/gpt-4o-mini",
        [{"role": "user", "content": f"Вытащи весь текст с этого фото (если нет текста, напиши 'Текст не найден'): {photo_url}"}]
    )
    return f"📖 *Распознанный текст:*\n{result}"

# --- Редактирование фото ---
async def edit_photo_local(photo_url: str, effect: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(photo_url) as resp:
            photo_bytes = await resp.read()
    input_path = f"edit_{random.randint(1,999999)}.jpg"
    output_path = f"edited_{random.randint(1,999999)}.jpg"
    with open(input_path, "wb") as f:
        f.write(photo_bytes)
    img = Image.open(input_path)
    eff = effect.lower()
    if "черно" in eff:
        img = img.convert("L")
    elif "размыт" in eff:
        img = img.filter(ImageFilter.GaussianBlur(radius=5))
    elif "контраст" in eff:
        img = ImageEnhance.Contrast(img).enhance(1.8)
    elif "ярче" in eff:
        img = ImageEnhance.Brightness(img).enhance(1.5)
    elif "негатив" in eff:
        img = Image.eval(img, lambda x: 255 - x)
    else:
        img = ImageEnhance.Sharpness(img).enhance(1.3)
    img.save(output_path, "JPEG", quality=90)
    os.remove(input_path)
    return output_path

# --- Обработчики ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Бот AI — 100% бесплатно!*\n\n"
        "✨ *Что умеет:*\n"
        "• 💬 *Общий чат* — Groq\n"
        "• 🖼 *Создать фото* — Pollinations\n"
        "• 📝 *Создать песню* — OpenRouter (текст)\n"
        "• ✏️ *Редактировать фото* — локально\n"
        "• 🔍 *Анализ фото, объекты, текст* — GPT-4o-mini\n\n"
        "👇 *Нажми на любую кнопку*",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_history(update.effective_user.id)
    await update.message.reply_text("✅ История очищена!", reply_markup=get_main_keyboard())

async def photo_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🖼 Напиши описание фото:")
    context.user_data['awaiting_photo'] = True

async def process_photo_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_photo'):
        prompt = update.message.text
        await update.message.reply_text(f"🎨 Создаю фото: {prompt[:100]}...")
        url = await generate_photo(prompt)
        await update.message.reply_photo(photo=url, caption=f"🖼 {prompt[:200]}")
        del context.user_data['awaiting_photo']

async def song_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Напиши тему песни:")
    context.user_data['awaiting_song'] = True

async def process_song_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_song'):
        topic = update.message.text
        await update.message.reply_text(f"📝 Пишу песню на тему: {topic}...")
        lyrics = await generate_song_lyrics(topic)
        await update.message.reply_text(f"🎵 *Текст песни*\n\n{lyrics[:3000]}", parse_mode="Markdown")
        del context.user_data['awaiting_song']

async def edit_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✏️ Отправь ФОТО, затем выбери эффект.", reply_markup=get_edit_keyboard())
    context.user_data['awaiting_edit_photo'] = True

async def analyze_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Отправь ФОТО")
    context.user_data['awaiting_analyze'] = True

async def detect_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👁️ Отправь ФОТО")
    context.user_data['awaiting_detect'] = True

async def ocr_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📖 Отправь ФОТО с текстом")
    context.user_data['awaiting_ocr'] = True

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    file = await photo.get_file()
    photo_url = file.file_path

    if context.user_data.get('awaiting_analyze'):
        await update.message.reply_text("Анализирую фото...")
        result = await analyze_photo(photo_url)
        await update.message.reply_text(f"🔎 *Анализ:*\n{result}", parse_mode="Markdown")
        del context.user_data['awaiting_analyze']
    elif context.user_data.get('awaiting_detect'):
        await update.message.reply_text("Ищу объекты...")
        result = await describe_objects(photo_url)
        await update.message.reply_text(result, parse_mode="Markdown")
        del context.user_data['awaiting_detect']
    elif context.user_data.get('awaiting_ocr'):
        await update.message.reply_text("Распознаю текст...")
        result = await extract_text_from_photo(photo_url)
        await update.message.reply_text(result, parse_mode="Markdown")
        del context.user_data['awaiting_ocr']
    elif context.user_data.get('awaiting_edit_photo'):
        context.user_data['edit_photo_path'] = photo_url
        await update.message.reply_text("✅ Фото получено! Выбери эффект:", reply_markup=get_edit_keyboard())
    else:
        await update.message.reply_text("Нажми нужную кнопку: 🔍 Анализ 👁️ Объекты 📖 Текст ✏️ Редакт", reply_markup=get_main_keyboard())

async def handle_edit_effect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    effect = update.message.text
    if effect == "◀️ Назад":
        await update.message.reply_text("Главное меню", reply_markup=get_main_keyboard())
        context.user_data.pop('awaiting_edit_photo', None)
        context.user_data.pop('edit_photo_path', None)
        return
    if context.user_data.get('edit_photo_path'):
        await update.message.reply_text(f"✨ Применяю {effect}...")
        result = await edit_photo_local(context.user_data['edit_photo_path'], effect)
        with open(result, 'rb') as f:
            await update.message.reply_photo(photo=f, caption=f"✅ Эффект '{effect}'")
        os.remove(result)
        context.user_data.pop('edit_photo_path', None)
    else:
        await update.message.reply_text("Сначала отправь фото через ✏️ Редактировать фото!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if context.user_data.get('awaiting_photo'):
        await process_photo_prompt(update, context)
        return
    if context.user_data.get('awaiting_song'):
        await process_song_topic(update, context)
        return

    if text == "💬 Общий чат":
        await update.message.reply_text("💬 Режим диалога", reply_markup=get_main_keyboard())
    elif text == "🖼 Создать фото":
        await photo_request(update, context)
    elif text == "📝 Создать песню":
        await song_request(update, context)
    elif text == "✏️ Редактировать фото":
        await edit_request(update, context)
    elif text == "🔍 Анализ фото":
        await analyze_request(update, context)
    elif text == "👁️ Найти объекты":
        await detect_request(update, context)
    elif text == "📖 Распознать текст":
        await ocr_request(update, context)
    elif text == "🗑 Очистить историю":
        await clear(update, context)
    elif text == "❓ Помощь":
        await start(update, context)
    elif text in ["⚫ Черно-белое", "🌀 Размытие", "✨ Контраст", "☀️ Ярче", "🎭 Негатив", "◀️ Назад"]:
        await handle_edit_effect(update, context)
    else:
        await update.message.chat.send_action(action="typing")
        add_to_history(user_id, "user", text)
        messages = [{"role": "system", "content": "Ты дружелюбный помощник. Отвечай кратко на русском."}]
        messages.extend(get_history(user_id)[-10:])
        try:
            response = groq_client.chat.completions.create(model="llama-3.3-70b-versatile", messages=messages, temperature=0.7, max_tokens=1024)
            answer = response.choices[0].message.content
            add_to_history(user_id, "assistant", answer)
            await update.message.reply_text(answer, reply_markup=get_main_keyboard())
        except Exception as e:
            await update.message.reply_text(f"⚠️ Ошибка: {str(e)[:100]}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    print("🚀 Бот AI обновлён. Функции фото/текста работают через GPT-4o-mini.")
    app.run_polling()

if __name__ == "__main__":
    main()
