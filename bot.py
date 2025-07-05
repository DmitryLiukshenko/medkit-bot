# 📦 Импорты стандартных и сторонних библиотек
import os
import logging
import calendar
from datetime import date, timedelta, time as dtime

# 📦 Загрузка переменных окружения (например, BOT_TOKEN из .env)
from dotenv import load_dotenv

# 📦 Telegram Bot API
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# 📦 Импорт функций и моделей из локального модуля БД
from db import init_db, Session, Medicine

# Логирование для отладки и мониторинга
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка переменной окружения BOT_TOKEN из файла .env
load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    logger.error("BOT_TOKEN не найден. Убедитесь, что он в .env")
    exit(1)

# Временное хранилище подписчиков (chat_id)
SUBSCRIBERS = set()

# Разбор аргументов после команды
def get_args(text: str):
    parts = text.split(' ', 1)
    return parts[1].strip() if len(parts) > 1 else None

# Парсинг даты (поддержка форматов: ГГГГ-ММ-ДД, ММ-ГГГГ и ГГГГ-ММ)
def parse_expiration(exp_str: str) -> date:
    exp_str = exp_str.strip()
    if exp_str.count('-') == 2:
        return date.fromisoformat(exp_str)  # Полный формат
    if exp_str.count('-') == 1:
        p1, p2 = exp_str.split('-')
        # Обработка ММ-ГГГГ и ГГГГ-ММ
        if len(p1) == 2 and len(p2) == 4:
            month, year = int(p1), int(p2)
        elif len(p1) == 4 and len(p2) == 2:
            year, month = int(p1), int(p2)
        else:
            raise ValueError("Неверный формат даты")
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, last_day)  # Возвращаем последний день месяца
    raise ValueError("Неверный формат даты")

# Проверка всех лекарств, срок которых истекает через 7 дней
async def daily_check(context: ContextTypes.DEFAULT_TYPE):
    today = date.today()
    week_later = today + timedelta(days=7)
    session = Session()
    meds = (
        session.query(Medicine)
        .filter(Medicine.expiration >= today, Medicine.expiration <= week_later)
        .order_by(Medicine.expiration)
        .all()
    )
    session.close()
    if not meds:
        return
    lines = [f"{m.name} ({m.dosage}) — истекает {m.expiration}" for m in meds]
    msg = "⚠️ Срок годности истекает в течение недели:\n" + "\n".join(lines)
    for chat_id in SUBSCRIBERS:
        await context.bot.send_message(chat_id=chat_id, text=msg)

#/start — приветствие и подписка на уведомления
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    SUBSCRIBERS.add(chat_id)
    logger.info(f"Новый подписчик: {chat_id}")
    greeting = (
        "👋 Привет! Я MedKitBot. Я напомню, если срок годности лекарства близок.\n"
        "Команды:\n"
        "/add Название;дозировка;кол-во;ГГГГ-ММ-ДД или ММ-ГГГГ\n"
        "/list — показать все лекарства\n"
        "/edit ID;кол-во;дата — обновить запись\n"
        "/delete ID — удалить запись\n"
        "/stats - вывести список моей аптечки"
    )
    await update.message.reply_text(greeting)

#/add — добавление лекарства
async def add_medicine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = get_args(update.message.text)
    if not args:
        return await update.message.reply_text("❌ Формат: /add Название;дозировка;кол-во;дата")
    parts = [x.strip() for x in args.split(';')]
    if len(parts) != 4:
        return await update.message.reply_text("❌ Формат: /add Название;дозировка;кол-во;дата")
    name, dosage, qty_str, exp_str = parts
    if not qty_str.isdigit():
        return await update.message.reply_text("❌ Количество должно быть числом")
    try:
        exp_date = parse_expiration(exp_str)
    except ValueError:
        return await update.message.reply_text("❌ Неверный формат даты")
    session = Session()
    med = Medicine(name=name, dosage=dosage, quantity=int(qty_str), expiration=exp_date)
    session.add(med)
    session.commit()
    await update.message.reply_text(
        f"✅ Добавлено: {med.name} (ID {med.id}) — {med.quantity} шт., истекает {med.expiration}"
    )
    session.close()

#/list — вывод списка всех лекарств
async def list_medicines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    meds = session.query(Medicine).order_by(Medicine.id).all()
    session.close()
    if not meds:
        return await update.message.reply_text("🗒️ Аптечка пуста.")
    lines = [f"{m.id}. {m.name} ({m.dosage}) — {m.quantity} шт., истекает {m.expiration}" for m in meds]
    await update.message.reply_text("\n".join(lines))

#/edit — изменение количества и даты лекарства
async def edit_medicine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = get_args(update.message.text)
    if not args:
        return await update.message.reply_text("❌ Формат: /edit ID;кол-во;дата")
    parts = [x.strip() for x in args.split(';')]
    if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
        return await update.message.reply_text("❌ ID и количество должны быть числами")
    med_id_str, qty_str, exp_str = parts
    try:
        exp_date = parse_expiration(exp_str)
    except ValueError:
        return await update.message.reply_text("❌ Неверный формат даты")
    session = Session()
    med = session.get(Medicine, int(med_id_str))
    if not med:
        session.close()
        return await update.message.reply_text("❌ Запись не найдена")
    med.quantity = int(qty_str)
    med.expiration = exp_date
    session.commit()
    session.close()
    await update.message.reply_text(f"✏️ Обновлено: {med.name} — {med.quantity} шт., истекает {med.expiration}")

#/delete - удаление записи
async def delete_medicine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = get_args(update.message.text)
    if not args or not args.isdigit():
        return await update.message.reply_text("❌ Формат: /delete ID")
    session = Session()
    med = session.get(Medicine, int(args))
    if not med:
        session.close()
        return await update.message.reply_text("❌ Запись не найдена")
    session.delete(med)
    session.commit()
    session.close()
    await update.message.reply_text(f"🗑️ Удалён: {med.name}")

#/stats - статистика по аптечке
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today()
    in_7_days = today + timedelta(days=7)
    in_30_days = today + timedelta(days=30)

    session = Session()
    all_meds = session.query(Medicine).all()
    session.close()

    total = len(all_meds)
    expired = sum(1 for m in all_meds if m.expiration < today)
    soon_7 = sum(1 for m in all_meds if today <= m.expiration <= in_7_days)
    soon_30 = sum(1 for m in all_meds if today <= m.expiration <= in_30_days)

    msg = (
        f"📊 Статистика аптечки:\n"
        f"Всего лекарств: {total}\n"
        f"Просроченных: {expired}\n"
        f"С истекающим сроком (7 дней): {soon_7}\n"
        f"С истекающим сроком (30 дней): {soon_30}"
    )
    await update.message.reply_text(msg)

# Запуск приложения
if __name__ == '__main__':
    init_db()  # Инициализация базы данных
    app = ApplicationBuilder().token(TOKEN).build()

    # Регистрация команд
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('add', add_medicine))
    app.add_handler(CommandHandler('list', list_medicines))
    app.add_handler(CommandHandler('edit', edit_medicine))
    app.add_handler(CommandHandler('delete', delete_medicine))
    app.add_handler(CommandHandler('stats', stats))

    # Планирование напоминаний ежедневно в 9:00
    app.job_queue.run_daily(daily_check, time=dtime(hour=9, minute=0))
    logger.info("JobQueue активен, задача напоминания запланирована")

    # Запуск бота
    app.run_polling()
