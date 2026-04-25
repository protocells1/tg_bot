import os
import asyncio
import logging
import random
from PIL import Image, ImageFilter, ImageEnhance
import aiohttp
import cv2
import numpy as np
from ultralytics import YOLO
import pytesseract

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
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
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Инициализация клиентов
groq_client = Groq(api_key=GROQ_API_KEY)

# Загрузка YOLO модели (для распознавания объектов)
try:
    yolo_model = YOLO("yolov8n.pt")
    YOLO_AVAILABLE = True
except:
    YOLO_AVAILABLE = False
    logging.warning("YOLO model not loaded")

# --- КЛАВИАТУРА ---
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

# ============================================================
# 1. ГЕНЕРАЦИЯ ФОТО (Pollinations - бесплатно)
# ============================================================
async def generate_photo(prompt: str) -> str:
    encoded = prompt.replace(" ", "%20").replace("?", "%3F").replace("!", "%21")
    return f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&model=flux&nologo=true"

# ============================================================
# 2. ГЕНЕРАЦИЯ ТЕКСТА ПЕСНИ (OpenRouter - бесплатно)
# ============================================================
async def generate_song_lyrics(topic: str) -> str:
    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "mistralai/mistral-7b-instruct:free",
            "messages": [
                {"role": "system", "content": "Ты поэт. Напиши текст песни на русском с куплетами и припевом. Только текст, без лишних слов."},
                {"role": "user", "content": f"Напиши песню на тему: {topic}"}
            ],
            "max_tokens": 800
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data, headers=headers) as resp:
                result = await resp.json()
                return result.get("choices", [{}])[0].get("message", {}).get("content", "❌ Ошибка")
    except Exception as e:
        return f"❌ Ошибка: {str(e)[:100]}"

# ============================================================
# 3. АНАЛИЗ ФОТО (OpenRouter Vision - бесплатно)
# ============================================================
async def analyze_photo_ai(photo_url: str, question: str = "Опиши подробно что ты видишь на этом фото на русском языке") -> str:
    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "google/gemini-flash-1.5",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {"type": "image_url", "image_url": {"url": photo_url}}
                    ]
                }
            ],
            "max_tokens": 500
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data, headers=headers) as resp:
                result = await resp.json()
                return result.get("choices", [{}])[0].get("message", {}).get("content", "❌ Не удалось проанализировать")
    except Exception as e:
        return f"❌ Ошибка: {str(e)[:100]}"

# ============================================================
# 4. РАСПОЗНАВАНИЕ ОБЪЕКТОВ (YOLO - бесплатно, локально)
# ============================================================
async def detect_objects_local(photo_url: str) -> tuple:
    if not YOLO_AVAILABLE:
        return "❌ Функция временно недоступна", None
    
    async with aiohttp.ClientSession() as session:
        async with session.get(photo_url) as resp:
            photo_bytes = await resp.read()
    
    input_path = f"detect_{random.randint(1,999999)}.jpg"
    output_path = f"detected_{random.randint(1,999999)}.jpg"
    
    with open(input_path, "wb") as f:
        f.write(photo_bytes)
    
    results = yolo_model(input_path)
    
    # Сохраняем фото с рамками
    annotated = results[0].plot()
    cv2.imwrite(output_path, annotated)
    
    # Формируем отчёт
    detected = {}
    for box in results[0].boxes:
        class_id = int(box.cls[0])
        class_name = yolo_model.names[class_id]
        confidence = float(box.conf[0])
        if class_name not in detected:
            detected[class_name] = 0
        detected[class_name] += 1
    
    if detected:
        report = "🔍 *Найденные объекты:*\n"
        for obj, count in detected.items():
            report += f"• {obj}: {count} шт.\n"
    else:
        report = "🔍 Объекты не найдены"
    
    os.remove(input_path)
    return report, output_path

# ============================================================
# 5. РАСПОЗНАВАНИЕ ТЕКСТА (Tesseract OCR - бесплатно)
# ============================================================
async def extract_text_from_image(photo_url: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(photo_url) as resp:
            photo_bytes = await resp.read()
    
    input_path = f"ocr_{random.randint(1,999999)}.jpg"
    
    with open(input_path, "wb") as f:
        f.write(photo_bytes)
    
    try:
        img = Image.open(input_path)
        text = pytesseract.image_to_string(img, lang="rus+eng")
        os.remove(input_path)
        
        if text.strip():
            return f"📖 *Распознанный текст:*\n\n{text.strip()[:2000]}"
        else:
            return "📖 Текст на фото не найден"
    except Exception as e:
        os.remove(input_path)
        return f"❌ Ошибка распознавания: {str(e)[:100]}"

# ============================================================
# 6. РЕДАКТИРОВАНИЕ ФОТО (локально, бесплатно)
# ============================================================
async def edit_photo_local(photo_url: str, effect: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(photo_url) as resp:
            photo_bytes = await resp.read()
    
    input_path = f"edit_{random.randint(1,999999)}.jpg"
    output_path = f"edited_{random.randint(1,999999)}.jpg"
    
    with open(input_path, "wb") as f:
        f.write(photo_bytes)
    
    img = Image.open(input_path)
    effect_lower = effect.lower()
    
    if "черно" in effect_lower or "чёрно" in effect_lower:
        img = img.convert("L")
    elif "размыт" in effect_lower:
        img = img.filter(ImageFilter.GaussianBlur(radius=5))
    elif "контраст" in effect_lower:
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.8)
    elif "ярче" in effect_lower:
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(1.5)
    elif "негатив" in effect_lower:
        img = Image.eval(img, lambda x: 255 - x)
    else:
        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(1.3)
    
    img.save(output_path, "JPEG", quality=90)
    os.remove(input_path)
    return output_path

# ============================================================
# ОБРАБОТЧИКИ КОМАНД
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Бот AI — 100% бесплатно!*\n\n"
        "✨ *Что умеет:*\n"
        "• 💬 *Общий чат* — просто пиши сообщения\n"
        "• 🖼 *Создать фото* — опиши что хочешь увидеть\n"
        "• 📝 *Создать песню* — напиши тему, получишь текст\n"
        "• ✏️ *Редактировать фото* — отправь фото и выбери эффект\n"
        "• 🔍 *Анализ фото* — AI опишет что на фото\n"
        "• 👁️ *Найти объекты* — нейросеть найдёт все предметы\n"
        "• 📖 *Распознать текст* — вытащит текст с фото\n\n"
        "🔥 *Всё работает бесплатно!*\n"
        "👇 *Нажми на любую кнопку внизу*",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_history(update.effective_user.id)
    await update.message.reply_text("✅ История очищена!", reply_markup=get_main_keyboard())

# --- ФОТО ---
async def photo_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🖼 Напиши описание фото:", parse_mode="Markdown")
    context.user_data['awaiting_photo_prompt'] = True

async def process_photo_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_photo_prompt'):
        prompt = update.message.text
        await update.message.reply_text(f"🎨 Создаю фото: *{prompt[:100]}*...\n⏳ 10-20 секунд", parse_mode="Markdown")
        try:
            url = await generate_photo(prompt)
            await update.message.reply_photo(photo=url, caption=f"🖼 *Ваше фото*\n{prompt[:200]}", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
        finally:
            del context.user_data['awaiting_photo_prompt']

# --- ПЕСНЯ ---
async def song_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Напиши тему песни (любовь, дружба, космос...):", parse_mode="Markdown")
    context.user_data['awaiting_song_topic'] = True

async def process_song_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_song_topic'):
        topic = update.message.text
        await update.message.reply_text(f"📝 Пишу песню на тему: *{topic}*...\n⏳ До 15 секунд", parse_mode="Markdown")
        try:
            lyrics = await generate_song_lyrics(topic)
            await update.message.reply_text(f"🎵 *Текст песни*\n\n{lyrics[:3000]}", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
        finally:
            del context.user_data['awaiting_song_topic']

# --- АНАЛИЗ ФОТО ---
async def analyze_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 *Анализ фото*\n\nОтправь мне любое фото, и я опишу что на нём изображено.", parse_mode="Markdown")
    context.user_data['awaiting_analyze'] = True

async def process_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_analyze'):
        photo = update.message.photo[-1]
        file = await photo.get_file()
        photo_url = file.file_path
        
        await update.message.reply_text("🔍 Анализирую фото...\n⏳ До 20 секунд")
        try:
            analysis = await analyze_photo_ai(photo_url)
            await update.message.reply_text(f"🔎 *Результат анализа:*\n\n{analysis}", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
        finally:
            del context.user_data['awaiting_analyze']

# --- ПОИСК ОБЪЕКТОВ ---
async def detect_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👁️ *Поиск объектов*\n\nОтправь фото, и я найду все объекты на нём.", parse_mode="Markdown")
    context.user_data['awaiting_detect'] = True

async def process_detect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_detect'):
        photo = update.message.photo[-1]
        file = await photo.get_file()
        photo_url = file.file_path
        
        await update.message.reply_text("👁️ Ищу объекты на фото...\n⏳ До 15 секунд")
        try:
            report, output_path = await detect_objects_local(photo_url)
            await update.message.reply_text(report, parse_mode="Markdown")
            if output_path and os.path.exists(output_path):
                with open(output_path, 'rb') as f:
                    await update.message.reply_photo(photo=f, caption="🔍 Обведены найденные объекты")
                os.remove(output_path)
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
        finally:
            del context.user_data['awaiting_detect']

# --- РАСПОЗНАВАНИЕ ТЕКСТА ---
async def ocr_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📖 *Распознавание текста*\n\nОтправь фото с текстом (книга, вывеска, документ).", parse_mode="Markdown")
    context.user_data['awaiting_ocr'] = True

async def process_ocr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_ocr'):
        photo = update.message.photo[-1]
        file = await photo.get_file()
        photo_url = file.file_path
        
        await update.message.reply_text("📖 Распознаю текст...\n⏳ До 10 секунд")
        try:
            text = await extract_text_from_image(photo_url)
            await update.message.reply_text(text, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
        finally:
            del context.user_data['awaiting_ocr']

# --- РЕДАКТИРОВАНИЕ ФОТО ---
async def edit_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✏️ *Редактирование фото*\n\nОтправь мне ФОТО, затем выбери эффект.", reply_markup=get_edit_keyboard(), parse_mode="Markdown")
    context.user_data['awaiting_photo_for_edit'] = True

async def process_edit_effect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    effect = update.message.text
    
    if effect == "◀️ Назад":
        await update.message.reply_text("Главное меню:", reply_markup=get_main_keyboard())
        context.user_data.pop('awaiting_photo_for_edit', None)
        context.user_data.pop('edit_photo_path', None)
        return
    
    if context.user_data.get('edit_photo_path'):
        photo_path = context.user_data['edit_photo_path']
        await update.message.reply_text(f"✨ Применяю эффект: {effect}...")
        try:
            result_path = await edit_photo_local(photo_path, effect)
            with open(result_path, 'rb') as f:
                await update.message.reply_photo(photo=f, caption=f"✅ Эффект '{effect}' применён!")
            os.remove(result_path)
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
        finally:
            context.user_data.pop('edit_photo_path', None)
    else:
        await update.message.reply_text("Сначала отправь фото для редактирования!")

async def save_photo_for_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_photo_for_edit'):
        photo = update.message.photo[-1]
        file = await photo.get_file()
        photo_url = file.file_path
        context.user_data['edit_photo_path'] = photo_url
        await update.message.reply_text("✅ Фото получено! Теперь выбери эффект:", reply_markup=get_edit_keyboard())

# --- ОБРАБОТКА ТЕКСТА (главные кнопки и AI диалог) ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    # Проверка на ожидание ввода
    if context.user_data.get('awaiting_photo_prompt'):
        await process_photo_prompt(update, context)
        return
    if context.user_data.get('awaiting_song_topic'):
        await process_song_topic(update, context)
        return
    if context.user_data.get('awaiting_analyze'):
        await process_analyze(update, context)
        return
    if context.user_data.get('awaiting_detect'):
        await process_detect(update, context)
        return
    if context.user_data.get('awaiting_ocr'):
        await process_ocr(update, context)
        return
    
    # Главные кнопки
    if text == "💬 Общий чат":
        await update.message.reply_text("💬 Режим диалога активирован. Пиши мне сообщения!", reply_markup=get_main_keyboard())
        return
    elif text == "🖼 Создать фото":
        await photo_request(update, context)
        return
    elif text == "📝 Создать песню":
        await song_request(update, context)
        return
    elif text == "✏️ Редактировать фото":
        await edit_request(update, context)
        return
    elif text == "🔍 Анализ фото":
        await analyze_request(update, context)
        return
    elif text == "👁️ Найти объекты":
        await detect_request(update, context)
        return
    elif text == "📖 Распознать текст":
        await ocr_request(update, context)
        return
    elif text == "🗑 Очистить историю":
        await clear(update, context)
        return
    elif text == "❓ Помощь":
        await start(update, context)
        return
    
    # Кнопки эффектов
    if text in ["⚫ Черно-белое", "🌀 Размытие", "✨ Контраст", "☀️ Ярче", "🎭 Негатив", "◀️ Назад"]:
        await process_edit_effect(update, context)
        return
    
    # Обычный диалог с Groq AI
    await update.message.chat.send_action(action="typing")
    add_to_history(user_id, "user", text)
    
    messages = [{"role": "system", "content": "Ты дружелюбный помощник. Отвечай кратко на русском."}]
    messages.extend(get_history(user_id)[-10:])
    
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.7,
            max_tokens=1024
        )
        answer = response.choices[0].message.content
        add_to_history(user_id, "assistant", answer)
        await update.message.reply_text(answer, reply_markup=get_main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка: {str(e)[:100]}", reply_markup=get_main_keyboard())

# --- ОБРАБОТКА ФОТО ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_photo_for_edit'):
        await save_photo_for_edit(update, context)
    else:
        await update.message.reply_text(
            "📸 Что сделать с фото?\n\n"
            "• 🔍 *Анализ фото* — описать\n"
            "• 👁️ *Найти объекты* — найти предметы\n"
            "• 📖 *Распознать текст* — вытащить текст\n"
            "• ✏️ *Редактировать фото* — изменить\n\n"
            "Нажми соответствующую кнопку в меню.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )

# --- ЗАПУСК ---
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    print("🚀 Бот AI запущен! Все функции бесплатны!")
    app.run_polling()

if __name__ == "__main__":
    main()
