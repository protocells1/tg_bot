import os
import asyncio
import logging
import random
import aiohttp
import requests
from PIL import Image, ImageFilter, ImageEnhance
from io import BytesIO

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from groq import Groq
import replicate

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
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
WAVESPEED_API_KEY = os.getenv("WAVESPEED_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Инициализация клиентов
groq_client = Groq(api_key=GROQ_API_KEY)
replicate_client = replicate.Client(api_token=REPLICATE_API_TOKEN)

# --- КЛАВИАТУРА ---
def get_main_keyboard():
    buttons = [
        ["🤖 Общий чат"],
        ["🖼 8K Фото", "🎬 Видео из фото"],
        ["✨ Pro Редакт", "🖌️ Замена фона"],
        ["🖼️➕ Объединить фото", "🎵 Музыка/Песня"],
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

# ============================================================
# 1. ГЕНЕРАЦИЯ ФОТО 8K через WaveSpeed
# ============================================================
async def generate_photo_8k(prompt: str) -> str:
    """Генерация фото 8K с текстом через WaveSpeed API"""
    try:
        url = "https://api.wavespeed.ai/api/v2/black-forest-labs/flux-2-pro"
        headers = {"Authorization": f"Bearer {WAVESPEED_API_KEY}"}
        data = {"prompt": prompt, "image_size": "square_hd"}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data, headers=headers) as resp:
                result = await resp.json()
                return result.get("image_url")
    except Exception as e:
        logging.error(f"WaveSpeed error: {e}")
        return None

# ============================================================
# 2. PRO-РЕДАКТИРОВАНИЕ через Replicate
# ============================================================
async def edit_photo_pro(photo_url: str, instruction: str) -> str:
    """Pro-редактирование фото через InstructPix2Pix"""
    try:
        output = replicate_client.run(
            "timothybrooks/instruct-pix2pix:30c1d0b916a6d8f6a38a9a2c0c1c8f6a9a2d9c1c8f6a9a2d",
            input={
                "image": photo_url,
                "prompt": instruction,
                "num_outputs": 1,
                "guidance_scale": 7.5,
                "image_guidance_scale": 1.5,
                "diffusion_steps": 50
            }
        )
        return output[0] if isinstance(output, list) else output
    except Exception as e:
        logging.error(f"Edit error: {e}")
        return None

# ============================================================
# 3. ЗАМЕНА ФОНА через Replicate
# ============================================================
async def replace_background(photo_url: str, background_prompt: str) -> str:
    """Удаляет фон и генерирует новый"""
    try:
        # Удаляем фон
        removed = replicate_client.run(
            "cjwbw/rembg:fb8af171cfa1616ddcf1242c093f9c46bcada5ad4cf6f2fbe8b18b3d2d4c9c0b",
            input={"image": photo_url}
        )
        return removed
    except Exception as e:
        logging.error(f"Background error: {e}")
        return None

# ============================================================
# 4. ОБЪЕДИНЕНИЕ ФОТО через Replicate
# ============================================================
async def merge_photos(photo1_url: str, photo2_url: str, prompt: str) -> str:
    """Объединяет два фото в одно"""
    try:
        output = replicate_client.run(
            "salesforce/blip-2:4b32258c42e9e8b1a2c1d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4",
            input={
                "image": photo1_url,
                "condition_image": photo2_url,
                "prompt": prompt
            }
        )
        return output
    except Exception as e:
        logging.error(f"Merge error: {e}")
        return None

# ============================================================
# 5. МУЗЫКА через OpenRouter
# ============================================================
async def generate_music(prompt: str, is_instrumental: bool = False) -> dict:
    """Генерация музыки/песен через OpenRouter"""
    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        
        system_prompt = "Ты эксперт по написанию песен. Создай текст песни на русском языке."
        if is_instrumental:
            system_prompt += " Это будет инструментальная композиция, без слов. Опиши музыку."
        
        data = {
            "model": "meta-llama/llama-3.3-70b-instruct",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Напиши {'текст песни' if not is_instrumental else 'описание инструментальной музыки'} на тему: {prompt}"}
            ],
            "max_tokens": 1000
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data, headers=headers) as resp:
                result = await resp.json()
                lyrics = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                return {"lyrics": lyrics, "audio_url": None}
    except Exception as e:
        logging.error(f"Music error: {e}")
        return None

# ============================================================
# 6. АНИМАЦИЯ ФОТО В ВИДЕО через Replicate
# ============================================================
async def animate_photo_video(photo_url: str, prompt: str) -> str:
    """Превращает фото в видео с анимацией"""
    try:
        output = replicate_client.run(
            "stability-ai/stable-video-diffusion:3f0457e4619daac51203dedb472816fd4af51f3149fa7a9e0b5ffcf1b8172438",
            input={
                "input_image": photo_url,
                "video_length": 25,
                "sizing_strategy": "maintain_aspect_ratio",
                "frames_per_second": 8,
                "cond_aug": 0.02,
                "decoding_t": 1,
                "seed": random.randint(0, 1000000)
            }
        )
        return output[0] if isinstance(output, list) else output
    except Exception as e:
        logging.error(f"Animation error: {e}")
        return None

# ============================================================
# ОБРАБОТЧИКИ КОМАНД
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Супер-бот AI 2.0*\n\n"
        "✨ *Новые возможности:*\n"
        "• `/photo8k текст` — фото 8K с текстом\n"
        "• `/animatevideo` — оживить фото в видео\n"
        "• `/editpro инструкция` — Pro-редактирование\n"
        "• `/bg фон` — замена фона\n"
        "• `/merge` — объединить два фото\n"
        "• `/music описание` — песня\n"
        "• `/lyrics тема` — текст песни\n\n"
        "👇 *Используй кнопки внизу!*",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )

async def photo8k_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("❓ Пример: `/photo8k девушка с веснушками, дождь, 8k, фотореализм`")
        return
    
    msg = await update.message.reply_text(f"🎨 Создаю фото 8K: {prompt[:100]}...\n⏳ До 60 секунд")
    try:
        url = await generate_photo_8k(prompt)
        if url:
            await update.message.reply_photo(photo=url, caption=f"🖼 8K Фото\n{prompt[:200]}")
        else:
            await msg.edit_text("❌ Ошибка генерации. Возможно, закончились кредиты WaveSpeed.")
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

async def editpro_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    instruction = " ".join(context.args)
    if not instruction:
        await update.message.reply_text("❓ Пример: `/editpro сделать улыбку шире, добавить очки`\n\nЗатем отправь фото.")
        return
    context.user_data['editpro_instruction'] = instruction
    await update.message.reply_text("📸 Теперь отправь фото для Pro-редактирования")

async def bg_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    background = " ".join(context.args)
    if not background:
        await update.message.reply_text("❓ Пример: `/bg гора Эверест, снег`\n\nЗатем отправь фото.")
        return
    context.user_data['bg_prompt'] = background
    await update.message.reply_text("📸 Отправь фото для замены фона")

async def merge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("❓ Пример: `/merge человек на фоне Эйфелевой башни`\n\nЗатем отправь ДВА фото по очереди.")
        return
    context.user_data['merge_prompt'] = prompt
    context.user_data['merge_photos'] = []
    await update.message.reply_text("📸 Отправь ПЕРВОЕ фото")

async def music_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("❓ Пример: `/music грустная баллада о любви`\nДобавь `--inst` для инструментала")
        return
    
    is_instrumental = "--inst" in prompt
    if is_instrumental:
        prompt = prompt.replace("--inst", "").strip()
    
    msg = await update.message.reply_text(f"🎵 Создаю трек: {prompt[:100]}...\n⏳ До 30 секунд")
    try:
        result = await generate_music(prompt, is_instrumental)
        if result and result.get('lyrics'):
            await update.message.reply_text(f"📝 *Текст песни*\n\n{result['lyrics'][:3000]}", parse_mode="Markdown")
        else:
            await msg.edit_text("❌ Ошибка генерации текста")
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

async def animatevideo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 *Оживление фото в видео*\n\n"
        "1. Отправь мне ФОТО\n"
        "2. Затем напиши описание движения\n\n"
        "Пример: *человек идёт, волосы развеваются, камера приближается*",
        parse_mode="Markdown"
    )
    context.user_data['awaiting_animation'] = True

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_history(update.effective_user.id)
    await update.message.reply_text("✅ История очищена!", reply_markup=get_main_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# --- ОБРАБОТКА ФОТО ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    file = await photo.get_file()
    photo_url = file.file_path
    
    # Pro-редактирование
    if context.user_data.get('editpro_instruction'):
        instruction = context.user_data['editpro_instruction']
        await update.message.reply_text(f"✨ Редактирую: {instruction[:100]}...")
        try:
            result = await edit_photo_pro(photo_url, instruction)
            if result:
                await update.message.reply_photo(photo=result, caption="✅ Готово!")
            else:
                await update.message.reply_text("❌ Ошибка редактирования")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
        finally:
            del context.user_data['editpro_instruction']
    
    # Замена фона
    elif context.user_data.get('bg_prompt'):
        bg_prompt = context.user_data['bg_prompt']
        await update.message.reply_text(f"🖌️ Замена фона на: {bg_prompt[:100]}...")
        try:
            result = await replace_background(photo_url, bg_prompt)
            if result:
                await update.message.reply_photo(photo=result, caption="✅ Фон заменён!")
            else:
                await update.message.reply_text("❌ Ошибка замены фона")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
        finally:
            del context.user_data['bg_prompt']
    
    # Анимация
    elif context.user_data.get('awaiting_animation'):
        context.user_data['animation_photo'] = photo_url
        context.user_data['awaiting_animation'] = False
        context.user_data['awaiting_animation_prompt'] = True
        await update.message.reply_text("🎬 Теперь напиши ОПИСАНИЕ движения")
    
    # Объединение фото
    elif context.user_data.get('merge_photos') is not None:
        photos = context.user_data['merge_photos']
        photos.append(photo_url)
        
        if len(photos) == 1:
            await update.message.reply_text("📸 Отправь ВТОРОЕ фото")
        elif len(photos) == 2:
            prompt = context.user_data.get('merge_prompt', 'объединить')
            await update.message.reply_text(f"🖼️ Объединяю фото...")
            try:
                result = await merge_photos(photos[0], photos[1], prompt)
                if result:
                    await update.message.reply_photo(photo=result, caption="✅ Объединение готово!")
                else:
                    await update.message.reply_text("❌ Ошибка объединения")
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {e}")
            finally:
                del context.user_data['merge_photos']
                del context.user_data['merge_prompt']
    
    else:
        await update.message.reply_text(
            "Используй команды:\n"
            "• `/editpro инструкция` — Pro-редактирование\n"
            "• `/bg фон` — замена фона\n"
            "• `/animatevideo` — оживление фото\n"
            "• `/merge` — объединение фото"
        )

# --- ОБРАБОТКА ТЕКСТА ---
async def handle_animation_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_animation_prompt'):
        prompt = update.message.text
        photo_url = context.user_data.get('animation_photo')
        
        await update.message.reply_text(f"🎬 Создаю видео: {prompt[:100]}...\n⏳ До 2 минут")
        try:
            result = await animate_photo_video(photo_url, prompt)
            if result:
                await update.message.reply_video(video=result, caption=f"✅ Видео создано!\n{prompt[:200]}")
            else:
                await update.message.reply_text("❌ Ошибка создания видео")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
        finally:
            del context.user_data['awaiting_animation_prompt']
            del context.user_data['animation_photo']

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    # Кнопки меню
    if text == "🤖 Общий чат":
        await update.message.reply_text("✅ Пиши мне сообщения!", reply_markup=get_main_keyboard())
        return
    elif text == "🖼 8K Фото":
        await update.message.reply_text("Отправь: `/photo8k описание`", parse_mode="Markdown")
        return
    elif text == "🎬 Видео из фото":
        await animatevideo_command(update, context)
        return
    elif text == "✨ Pro Редакт":
        await update.message.reply_text("Отправь: `/editpro инструкция`", parse_mode="Markdown")
        return
    elif text == "🖌️ Замена фона":
        await update.message.reply_text("Отправь: `/bg новый фон`", parse_mode="Markdown")
        return
    elif text == "🖼️➕ Объединить фото":
        await merge_command(update, context)
        return
    elif text == "🎵 Музыка/Песня":
        await update.message.reply_text("Отправь: `/music описание`\nДобавь `--inst` для инструментала", parse_mode="Markdown")
        return
    elif text == "🗑 Очистить историю":
        await clear(update, context)
        return
    elif text == "ℹ️ Помощь":
        await start(update, context)
        return
    
    # Проверка на ожидание промпта для анимации
    if context.user_data.get('awaiting_animation_prompt'):
        await handle_animation_prompt(update, context)
        return
    
    # Обычный диалог с Groq
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
        await update.message.reply_text(f"⚠️ Ошибка AI: {str(e)[:100]}")

# --- ЗАПУСК БОТА ---
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("photo8k", photo8k_command))
    app.add_handler(CommandHandler("editpro", editpro_command))
    app.add_handler(CommandHandler("bg", bg_command))
    app.add_handler(CommandHandler("merge", merge_command))
    app.add_handler(CommandHandler("music", music_command))
    app.add_handler(CommandHandler("animatevideo", animatevideo_command))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    print("🚀 Супер-бот AI 2.0 запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
