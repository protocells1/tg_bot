import os
from dotenv import load_dotenv

load_dotenv()

print("=== БОТ НАЧАЛ ЗАГРУЗКУ ===")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

print(f"TELEGRAM_TOKEN: {'OK' if TELEGRAM_TOKEN else 'MISSING'}")
print(f"GROQ_API_KEY: {'OK' if GROQ_API_KEY else 'MISSING'}")
print(f"OPENROUTER_API_KEY: {'OK' if OPENROUTER_API_KEY else 'MISSING'}")

print("=== БОТ ЗАГРУЗИЛСЯ ===")

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Бот работает!")

def main():
    print("Создаю приложение...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    print("Запускаю polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
