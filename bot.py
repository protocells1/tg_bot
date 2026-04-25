import os
import asyncio
import logging
import random
from PIL import Image, ImageFilter, ImageEnhance
import aiohttp

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from groq import Groq

# Загружаем переменные окружения
load_dotenv()

# Настройка логов
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- КОНФИГУРАЦИЯ ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Проверка наличия ключей
print(f"TELEGRAM_TOKEN loaded: {bool(TELEGRAM_TOKEN)}")
print(f"GROQ_API_KEY loaded: {bool(GROQ_API_KEY)}")

if not TELEGRAM_TOKEN:
    raise Exception("TELEGRAM_TOKEN not found!")
if not GROQ_API_KEY:
    raise Exception("GROQ_API_KEY not found!")

# Подключаем Groq
groq_client = Groq(api_key=GROQ_API_KEY)

# --- КЛАВИАТУРА ---
def get_main_keyboard():
    buttons = [
        ["🤖 Общий чат"],
        ["🖼 Сгенерировать изображение", "🎬 Сгенерировать видео"],
        ["✨ Оживить фото", "✏️ Редактировать фото"],
        ["🗑 Очистить историю", "ℹ️ Помощь"]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

# --- ИСТОРИЯ ДИАЛОГА ---
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

# --- ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЙ ---
async def generate_image(prompt: str) -> str:
    encoded = prompt.replace(" ", "%20").replace("?", "%3F").replace("!", "%21")
    return f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&model=flux&nologo=true"

# --- ГЕНЕРАЦИЯ ВИДЕО ---
async def generate_video_demo(prompt: str) -> str:
    await asyncio.sleep(2)
    return "https://sample-videos.com/video123/mp4/720/big_buck_bunny_720p_1mb.mp4"

# --- ОЖИВЛЕНИЕ ФОТО (упрощённая версия)---
async def animate_photo(photo_url: str) -> str:
    return photo_url

# --- РЕДАКТИРОВАНИЕ ФОТО ---
async def edit_photo(photo_url: str, prompt: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(photo_url) as resp:
            photo_bytes = await resp.read()
    
    input_path = f"edit_{random.randint(1,999999)}.jpg"
    output_path = f"edited_{random.randint(1,999999)}.jpg"
    
    with open(input_path, "wb") as f:
        f.write(photo_bytes)
    
    img = Image.open(input_path)
    text = prompt.lower()
    
    if "черно" in text or "bw" in text:
        img = img.convert("L")
    elif "размыт" in text or "blur" in text:
        img = img.filter(ImageFilter.GaussianBlur(radius=5))
    elif "контраст" in text or "contrast" in text:
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.8)
    elif "ярче" in text or "bright" in text:
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(1.5)
    elif "негатив" in text or "negative" in text:
        img = Image.eval(img, lambda x: 255 - x)
    else:
        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(1.3)
    
    img.save(output_path, "JPEG", quality=90)
    os.remove(input_path)
    
    return output_path

# --- ОБРАБОТЧИКИ КОМАНД ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Привет! Я бот с нейросетями!*\n\n"
        "🎮 *Команды:*\n"
        "/image текст — сгенерировать картинку\n"
        "/video текст — сгенерировать видео\n"
        "/animate — оживить фото\n"
        "/edit описание — отредактировать фото\n"
        "/clear — очистить историю\n\n"
        "👇 *Используй кнопки внизу!*",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_history(update.effective_user.id)
    await update.message.reply_text("✅ История очищена!", reply_markup=get_main_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("❓ Пример: `/image кот`", parse_mode="Markdown")
        return
    
    msg = await update.message.reply_text(f"🎨 Генерирую: {prompt[:50]}...")
    try:
        url = await generate_image(prompt)
        await update.message.reply_photo(photo=url, caption=f"🖼 {prompt[:200]}")
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

async def video_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("❓ Пример: `/video закат`")
        return
    
    msg = await update.message.reply_text(f"🎬 Генерирую видео...")
    try:
        url = await generate_video_demo(prompt)
        await update.message.reply_video(video=url, caption=f"🎥 {prompt[:200]}")
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

async def animate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✨ Отправь мне фото!")

async def edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("❓ Пример: `/edit черно-белое`\nЗатем отправь фото")
        return
    context.user_data['edit_prompt'] = prompt
    await update.message.reply_text("📸 Отправь фото")

# --- ОБРАБОТКА ТЕКСТА (ДИАЛОГ С GROQ) ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    # Обработка кнопок
    if text == "🤖 Общий чат":
        await update.message.reply_text("✅ Пиши мне сообщения!", reply_markup=get_main_keyboard())
        return
    elif text == "🖼 Сгенерировать изображение":
        await update.message.reply_text("Отправь: `/image описание`", parse_mode="Markdown")
        return
    elif text == "🎬 Сгенерировать видео":
        await update.message.reply_text("Отправь: `/video описание`")
        return
    elif text == "✨ Оживить фото":
        await animate_command(update, context)
        return
    elif text == "✏️ Редактировать фото":
        await update.message.reply_text("Отправь: `/edit эффект`", parse_mode="Markdown")
        return
    elif text == "🗑 Очистить историю":
        await clear(update, context)
        return
    elif text == "ℹ️ Помощь":
        await start(update, context)
        return
    
    # Диалог с Groq
    await update.message.chat.send_action(action="typing")
    add_to_history(user_id, "user", text)
    
    messages = [{"role": "system", "content": "Ты дружелюбный помощник. Отвечай кратко на русском."}]
    messages.extend(get_history(user_id)[-10:])
    
    try:
        response = groq_client.chat.completions.create(
            model="llama3-70b-8192",
            messages=messages,
            temperature=0.7,
            max_tokens=1024
        )
        answer = response.choices[0].message.content
        add_to_history(user_id, "assistant", answer)
        await update.message.reply_text(answer, reply_markup=get_main_keyboard())
    except Exception as e:
        logging.error(f"Groq error: {e}")
        await update.message.reply_text(f"⚠️ Ошибка AI: {str(e)[:100]}", reply_markup=get_main_keyboard())

# --- ОБРАБОТКА ФОТО ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    file = await photo.get_file()
    photo_url = file.file_path
    
    if context.user_data.get('edit_prompt'):
        prompt = context.user_data['edit_prompt']
        await update.message.reply_text(f"✏️ Редактирую: {prompt}...")
        try:
            result_path = await edit_photo(photo_url, prompt)
            with open(result_path, 'rb') as f:
                await update.message.reply_photo(photo=f, caption="✅ Готово!")
            os.remove(result_path)
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
        finally:
            del context.user_data['edit_prompt']
    else:
        await update.message.reply_text("✨ Оживляю фото...")
        result_path = await animate_photo(photo_url)
        if result_path == photo_url:
            await update.message.reply_text("⚠️ Функция оживления временно недоступна. Бот работает в базовом режиме.")

# --- ЗАПУСК БОТА ---
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("image", image_command))
    app.add_handler(CommandHandler("video", video_command))
    app.add_handler(CommandHandler("animate", animate_command))
    app.add_handler(CommandHandler("edit", edit_command))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    print("🚀 Бот запущен и работает 24/7!")
    app.run_polling()

if __name__ == "__main__":
    main()