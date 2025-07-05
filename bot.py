import os
import logging
import calendar
from datetime import date, timedelta, time as dtime
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)
from db import init_db, Session, Medicine  # Импорт базы и модели

# --- Настройка логирования ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Загрузка токена из файла .env ---
load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    logger.error("BOT_TOKEN не найден. Убедитесь, что он в .env")
    exit(1)

# --- Множество подписчиков для уведомлений ---
SUBSCRIBERS = set()

# --- Состояния для ConversationHandler (многошагового диалога добавления лекарства) ---
NAME, DOSAGE, QUANTITY, EXPIRATION = range(4)

# --- Вспомогательная функция для извлечения аргументов команды ---
def get_args(text: str):
    parts = text.split(' ', 1)
    return parts[1].strip() if len(parts) > 1 else None

# --- Функция для парсинга срока годности из разных форматов в дату ---
def parse_expiration(exp_str: str) -> date:
    exp_str = exp_str.strip()
    if exp_str.count('-') == 2:  # Формат ГГГГ-ММ-ДД
        return date.fromisoformat(exp_str)
    if exp_str.count('-') == 1:  # Форматы ММ-ГГГГ или ГГГГ-ММ
        p1, p2 = exp_str.split('-')
        if len(p1) == 2 and len(p2) == 4:  # ММ-ГГГГ
            month, year = int(p1), int(p2)
        elif len(p1) == 4 and len(p2) == 2:  # ГГГГ-ММ
            year, month = int(p1), int(p2)
        else:
            raise ValueError("Неверный формат даты")
        last_day = calendar.monthrange(year, month)[1]  # последний день месяца
        return date(year, month, last_day)
    raise ValueError("Неверный формат даты")

# --- Задача для ежедневной проверки лекарств с истекающим сроком ---
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

# --- Команда /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    SUBSCRIBERS.add(chat_id)  # Добавляем в подписчики для уведомлений
    logger.info(f"Новый подписчик: {chat_id}")
    keyboard = [  # Создаём клавиатуру с кнопками
        ["➕ Добавить", "📋 Список"],
        ["✏️ Редактировать", "🗑️ Удалить"],
        ["📊 Статистика", "❓ Помощь"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "👋 Привет! Я MedKitBot. Выберите действие:",
        reply_markup=reply_markup
    )

# --- Обработка нажатий кнопок как текстовых сообщений ---
async def handle_main_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "➕ Добавить":
        return await add_start(update, context)  # Запускаем диалог добавления
    elif text == "📋 Список":
        await list_medicines(update, context)
    elif text == "✏️ Редактировать":
        await update.message.reply_text("✏️ Используй: /edit ID;кол-во;дата")
    elif text == "🗑️ Удалить":
        await update.message.reply_text("🗑️ Используй: /delete ID")
    elif text == "📊 Статистика":
        await stats(update, context)
    elif text == "❓ Помощь":
        await help_command(update, context)

# --- Многошаговое добавление лекарства ---

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✏️ Введите название лекарства:")
    return NAME

async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text.strip()
    await update.message.reply_text("Введите дозировку (например, 500мг):")
    return DOSAGE

async def add_dosage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['dosage'] = update.message.text.strip()
    await update.message.reply_text("Введите количество (число):")
    return QUANTITY

async def add_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qty_text = update.message.text.strip()
    if not qty_text.isdigit():
        await update.message.reply_text("❌ Количество должно быть числом. Попробуйте снова:")
        return QUANTITY
    context.user_data['quantity'] = int(qty_text)
    await update.message.reply_text("Введите срок годности (ГГГГ-ММ-ДД или ММ-ГГГГ):")
    return EXPIRATION

async def add_expiration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    exp_text = update.message.text.strip()
    try:
        exp_date = parse_expiration(exp_text)
    except Exception:
        await update.message.reply_text("❌ Неверный формат даты. Попробуйте снова:")
        return EXPIRATION
    context.user_data['expiration'] = exp_date

    session = Session()
    med = Medicine(
        name=context.user_data['name'],
        dosage=context.user_data['dosage'],
        quantity=context.user_data['quantity'],
        expiration=exp_date,
        user_id=update.effective_user.id  # Привязываем лекарство к пользователю
    )
    session.add(med)
    session.commit()

    await update.message.reply_text(
        f"✅ Лекарство добавлено: {med.name} ({med.dosage}), "
        f"{med.quantity} шт., срок годности: {med.expiration}"
    )
    session.close()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Добавление отменено.")
    return ConversationHandler.END

# --- Отобразить список лекарств пользователя ---
async def list_medicines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    meds = session.query(Medicine).filter_by(user_id=update.effective_user.id).order_by(Medicine.id).all()
    session.close()
    if not meds:
        return await update.message.reply_text("🗒️ Аптечка пуста.")
    lines = [f"{m.id}. {m.name} ({m.dosage}) — {m.quantity} шт., истекает {m.expiration}" for m in meds]
    await update.message.reply_text("\n".join(lines))

# --- Редактирование лекарства ---
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
    med = session.query(Medicine).filter_by(id=int(med_id_str), user_id=update.effective_user.id).first()
    if not med:
        session.close()
        return await update.message.reply_text("❌ Запись не найдена")
    med.quantity = int(qty_str)
    med.expiration = exp_date
    session.commit()
    session.close()
    await update.message.reply_text(f"✏️ Обновлено: {med.name} — {med.quantity} шт., истекает {med.expiration}")

# --- Удаление лекарства ---
async def delete_medicine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = get_args(update.message.text)
    if not args or not args.isdigit():
        return await update.message.reply_text("❌ Формат: /delete ID")
    session = Session()
    med = session.query(Medicine).filter_by(id=int(args), user_id=update.effective_user.id).first()
    if not med:
        session.close()
        return await update.message.reply_text("❌ Запись не найдена")
    session.delete(med)
    session.commit()
    session.close()
    await update.message.reply_text(f"🗑️ Удалён: {med.name}")

# --- Статистика лекарств ---
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today()
    in_7_days = today + timedelta(days=7)
    in_30_days = today + timedelta(days=30)

    session = Session()
    all_meds = session.query(Medicine).filter_by(user_id=update.effective_user.id).all()
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

# --- Помощь /help ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🆘 <b>Справка по командам:</b>\n\n"
        "<b>/add</b> - добавить новое лекарство\n"
        "<b>/edit</b> ID;кол-во;дата - изменить запись по ID\n"
        "<b>/delete</b> ID - удалить лекарство по ID\n"
        "<b>/list</b> - показать все лекарства\n"
        "<b>/stats</b> - вывести статистику аптечки\n"
        "<b>/start</b> - показать меню с кнопками\n"
        "<b>/help</b> - показать эту справку\n"
        "В диалоге добавления можно отменить командой /cancel"
    )
    await update.message.reply_text(msg, parse_mode="HTML")

# --- Основной блок запуска бота ---
if __name__ == '__main__':
    init_db()  # Создаём таблицы, если их нет
    app = ApplicationBuilder().token(TOKEN).build()

    # Регистрируем команды
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('list', list_medicines))
    app.add_handler(CommandHandler('edit', edit_medicine))
    app.add_handler(CommandHandler('delete', delete_medicine))
    app.add_handler(CommandHandler('stats', stats))
    app.add_handler(CommandHandler('help', help_command))

    # Обработчик многошагового диалога добавления лекарства
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('add', add_start),  # Команда /add
            MessageHandler(filters.TEXT & filters.Regex("^➕ Добавить$"), add_start)  # Кнопка "➕ Добавить"
        ],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            DOSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_dosage)],
            QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_quantity)],
            EXPIRATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_expiration)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    app.add_handler(conv_handler)

    # Обработчик остальных текстовых сообщений (кнопки и команды)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_main_buttons))

    # Запуск ежедневной задачи проверки срока годности в 9:00 утра
    app.job_queue.run_daily(daily_check, time=dtime(hour=9, minute=0))
    logger.info("JobQueue активен, задача напоминания запланирована")

    # Запуск бота (постоянный опрос Telegram)
    app.run_polling()
