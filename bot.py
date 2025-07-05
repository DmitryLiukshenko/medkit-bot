import os
import logging
import calendar
from datetime import date, timedelta, time as dtime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)
from db import init_db, Session, Medicine

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка токена
load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    logger.error("BOT_TOKEN не найден. Убедитесь, что он в .env")
    exit(1)

# Подписчики (для уведомлений, если понадобится)
SUBSCRIBERS = set()

# Conversation states для добавления лекарства
NAME, DOSAGE, QUANTITY, EXPIRATION = range(4)

# Утилита разбора аргументов (если понадобится для других команд)
def get_args(text: str):
    parts = text.split(' ', 1)
    return parts[1].strip() if len(parts) > 1 else None

# Парсинг даты: YYYY-MM-DD, MM-YYYY или YYYY-MM
def parse_expiration(exp_str: str) -> date:
    exp_str = exp_str.strip()
    if exp_str.count('-') == 2:
        return date.fromisoformat(exp_str)
    if exp_str.count('-') == 1:
        p1, p2 = exp_str.split('-')
        if len(p1) == 2 and len(p2) == 4:
            month, year = int(p1), int(p2)
        elif len(p1) == 4 and len(p2) == 2:
            year, month = int(p1), int(p2)
        else:
            raise ValueError("Неверный формат даты")
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, last_day)
    raise ValueError("Неверный формат даты")

# Ежедневная проверка сроков годности
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

# Команда /start с кнопками
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    SUBSCRIBERS.add(chat_id)
    logger.info(f"Новый подписчик: {chat_id}")
    keyboard = [
        [InlineKeyboardButton("➕ Добавить лекарство", callback_data='add')],
        [InlineKeyboardButton("📋 Показать список", callback_data='list')],
        [InlineKeyboardButton("✏️ Редактировать", callback_data='edit')],
        [InlineKeyboardButton("🗑️ Удалить", callback_data='delete')],
        [InlineKeyboardButton("📊 Статистика", callback_data='stats')],
        [InlineKeyboardButton("❓ Помощь", callback_data='help')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 Привет! Выберите действие ниже:",
        reply_markup=reply_markup
    )

# Обработчик нажатий кнопок
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == 'add':
        await query.edit_message_text("✏️ Начинаем добавлять лекарство. Напишите /add, чтобы начать диалог.")
    elif data == 'list':
        session = Session()
        meds = session.query(Medicine).order_by(Medicine.id).all()
        session.close()
        if not meds:
            await query.edit_message_text("🗒️ Аптечка пуста.")
            return
        lines = [f"{m.id}. {m.name} ({m.dosage}) — {m.quantity} шт., истекает {m.expiration}" for m in meds]
        await query.edit_message_text("\n".join(lines))
    elif data == 'edit':
        await query.edit_message_text("✏️ Чтобы изменить запись, используйте команду:\n/edit ID;кол-во;дата")
    elif data == 'delete':
        await query.edit_message_text("🗑️ Чтобы удалить лекарство, используйте команду:\n/delete ID")
    elif data == 'stats':
        await stats(query, context)
    elif data == 'help':
        await help_command(query, context)

# Многошаговый ввод для добавления лекарства

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
        expiration=exp_date
    )
    session.add(med)
    session.commit()
    session.close()

    await update.message.reply_text(
        f"✅ Лекарство добавлено: {med.name} ({med.dosage}), "
        f"{med.quantity} шт., срок годности: {med.expiration}"
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Добавление отменено.")
    return ConversationHandler.END

# Другие команды (list, edit, delete, stats, help) - оставляем как есть

async def list_medicines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    meds = session.query(Medicine).order_by(Medicine.id).all()
    session.close()
    if not meds:
        return await update.message.reply_text("🗒️ Аптечка пуста.")
    lines = [f"{m.id}. {m.name} ({m.dosage}) — {m.quantity} шт., истекает {m.expiration}" for m in meds]
    await update.message.reply_text("\n".join(lines))

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

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🆘 <b>Справка по командам:</b>\n\n"
        "<b>/add</b> - добавить новое лекарство (можно через диалог с кнопками)\n"
        "<b>/edit</b> ID;кол-во;дата - изменить запись по ID\n"
        "<b>/delete</b> ID - удалить лекарство по ID\n"
        "<b>/list</b> - показать все лекарства\n"
        "<b>/stats</b> - вывести статистику аптечки\n"
        "<b>/start</b> - показать меню с кнопками\n"
        "<b>/help</b> - показать эту справку\n"
        "В диалоге добавления можно отменить командой /cancel"
    )
    await update.message.reply_text(msg, parse_mode="HTML")

# Запуск бота
if __name__ == '__main__':
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    # Регистрируем хендлеры команд
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('list', list_medicines))
    app.add_handler(CommandHandler('edit', edit_medicine))
    app.add_handler(CommandHandler('delete', delete_medicine))
    app.add_handler(CommandHandler('stats', stats))
    app.add_handler(CommandHandler('help', help_command))

    # ConversationHandler для /add (многошаговый ввод)
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('add', add_start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            DOSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_dosage)],
            QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_quantity)],
            EXPIRATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_expiration)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    app.add_handler(conv_handler)

    # Обработчик кнопок
    app.add_handler(CallbackQueryHandler(button_handler))

    # Планирование ежедневной проверки срока годности в 09:00
    app.job_queue.run_daily(daily_check, time=dtime(hour=9, minute=0))
    logger.info("JobQueue активен, задача напоминания запланирована")

    app.run_polling()
