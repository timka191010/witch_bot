import os
from database import init_db, save_application, get_all_applications, clear_all_applications, get_application
from datetime import datetime, timedelta
import asyncio
from aiohttp import web
import signal
import sys
from threading import Thread
import time

# Создаём базу при запуске
init_db()

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, \
    ConversationHandler

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Состояния
NAME, AGE, FAMILY_STATUS, CHILDREN, HOBBIES, THEMES, GOAL, SOURCE = range(8)

# Админы по умолчанию
DEFAULT_ADMINS = [7271900005, 703873503]

# Получаем админов из переменной окружения или используем дефолтных
admin_ids_env = os.getenv('ADMIN_IDS', '')
if admin_ids_env:
    ADMIN_IDS = [int(id) for id in admin_ids_env.split(',') if id]
else:
    ADMIN_IDS = DEFAULT_ADMINS

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ССЫЛКА НА ЗАКРЫТЫЙ ЧАТ КЛУБА
CLUB_CHAT_LINK = os.getenv('CHAT_LINK', 'https://t.me/+S32BT0FT6w0xYTBi')

# База данных анкет - теперь в PostgreSQL
user_data = {}


class PollingWatchdog:
    """Следит за активностью polling и перезапускает при зависании"""
    def __init__(self, timeout=300):  # 5 минут без активности = перезапуск
        self.timeout = timeout
        self.last_update = time.time()
        self.running = True
        
    def reset(self):
        """Сбрасывает таймер при получении обновления"""
        self.last_update = time.time()
        
    def check(self):
        """Проверяет, не завис ли polling"""
        while self.running:
            time.sleep(60)  # Проверяем каждую минуту
            elapsed = time.time() - self.last_update
            if elapsed > self.timeout:
                logger.error(f"⚠️ Polling завис! Нет активности {int(elapsed)} секунд. Перезапускаем...")
                os._exit(1)  # Принудительный выход — Render автоматически перезапустит


watchdog = PollingWatchdog(timeout=300)  # 5 минут


def signal_handler(sig, frame):
    """Обработчик для graceful shutdown"""
    logger.info("🛑 Получен сигнал остановки")
    watchdog.running = False
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def get_upcoming_birthdays(ankets, limit=5):
    """Находит ближайшие дни рождения (МСК timezone UTC+3)"""
    # Используем UTC+3 (Moscow timezone)
    msk_tz = timedelta(hours=3)
    today = (datetime.utcnow() + msk_tz).date()
    
    birthdays = []
    
    for ank in ankets:
        try:
            birth_str = ank['age'].strip()
            birth_date = None
            
            # Пробуем парсить разные форматы даты
            for fmt in ['%d.%m.%Y', '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%y', '%d/%m/%y']:
                try:
                    birth_date = datetime.strptime(birth_str, fmt)
                    break
                except:
                    continue
            
            if birth_date:
                # Вычисляем следующий день рождения
                next_birthday = birth_date.replace(year=today.year)
                
                # Если ДР уже прошёл в этом году, берём следующий год
                if next_birthday.date() < today:
                    next_birthday = birth_date.replace(year=today.year + 1)
                
                days_until = (next_birthday.date() - today).days
                age = next_birthday.year - birth_date.year
                
                birthdays.append({
                    'name': ank['name'],
                    'date': birth_date.strftime('%d.%m'),
                    'days_until': days_until,
                    'age': age
                })
        except Exception as e:
            logger.error(f"Ошибка парсинга даты для {ank.get('name', 'Unknown')}: {e}")
            continue
    
    # Сортируем по количеству дней до ДР
    birthdays.sort(key=lambda x: x['days_until'])
    
    return birthdays[:limit]


async def health_check(request):
    return web.Response(text="OK")


async def run_health_server():
    """Запускает HTTP-сервер для Render"""
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv('PORT', 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🌐 Health server running on port {port}")


async def watchdog_updater(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обновляет watchdog при каждом сообщении"""
    watchdog.reset()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data[user_id] = {}

    welcome_msg = """
🌙 *Приветствую тебя, странница!* 🌙

Я — *Ведьма Селена*, страж клубa *ВЕДЬМЫ НЕ СТАРЕЮТ*. 
Только избранные переступят наш порог...

✨ Назови своё **настоящее имя**:
    """

    await update.message.reply_text(welcome_msg, parse_mode='Markdown')
    return NAME


async def name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data[user_id]['name'] = update.message.text

    msg = """
🔮 *Имя, полное магии...* 🔮

Раскрой тайну **даты своего рождения (ДД.ММ.ГГГГ обязательно в таком формате!)**:
    """
    await update.message.reply_text(msg, parse_mode='Markdown')
    return AGE


async def age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data[user_id]['age'] = update.message.text

    keyboard = [
        [InlineKeyboardButton("🪄 Замужем", callback_data="married")],
        [InlineKeyboardButton("🌹 Свободна", callback_data="single")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    msg = """
🕯️ *Твои годы — мудрость веков...* 🕯️

*Сердце принадлежит кому-то?* Выбери судьбу:
    """
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=reply_markup)
    return FAMILY_STATUS


async def family_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    status = "Замужем" if query.data == "married" else "Свободна"
    user_data[user_id]['family_status'] = status

    msg = """
💍 *Судьба сердца записана в звёздах...* 💍

*Наследники магии?* Укажи возраст и пол (или "нет детей"):
    """
    await query.edit_message_text(msg, parse_mode='Markdown')
    return CHILDREN


async def children(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data[user_id]['children'] = update.message.text

    msg = """
🌿 *Магия течёт через наследников...* 🌿

*Чары и увлечения?* Что зажигает душу?
    """
    await update.message.reply_text(msg, parse_mode='Markdown')
    return HOBBIES


async def hobbies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data[user_id]['hobbies'] = update.message.text

    msg = """
🔥 *Страсти — пламя силы!* 🔥

*Что будет интересно?* Выезды, мастер-классы, тренинги:
    """
    await update.message.reply_text(msg, parse_mode='Markdown')
    return THEMES


async def themes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data[user_id]['themes'] = update.message.text

    msg = """
🪄 *Мудрость твоих желаний...* 🪄

**Цель вступления в клуб?**
    """
    await update.message.reply_text(msg, parse_mode='Markdown')
    return GOAL


async def goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data[user_id]['goal'] = update.message.text

    msg = """
🌟 *Последняя тайна, сестра...* 🌟

**От кого ты узнала о нашем клубе?** Кто указал тебе путь?
    """
    await update.message.reply_text(msg, parse_mode='Markdown')
    return SOURCE


async def source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data[user_id]['source'] = update.message.text

    # Сохраняем полную анкету
    anketa = {
        'user_id': user_id,
        'name': user_data[user_id]['name'],
        'age': user_data[user_id]['age'],
        'family_status': user_data[user_id]['family_status'],
        'children': user_data[user_id]['children'],
        'hobbies': user_data[user_id]['hobbies'],
        'themes': user_data[user_id]['themes'],
        'goal': user_data[user_id]['goal'],
        'source': user_data[user_id]['source']
    }
    
    # Сохраняем в базу данных PostgreSQL
    save_application(anketa)
    
    # Получаем номер анкеты
    all_ankets = get_all_applications()
    anketa_number = len(all_ankets)

    # Подтверждение пользователю
    confirm = """
🧙‍♀️ *Анкета принята, сестра!* 🧙‍♀️

Твоя судьба теперь в руках ковена... 
Мы изучим твою заявку и скоро дадим ответ. 🌙

*Да пребудет с тобой магия!* ✨
    """
    await update.message.reply_text(confirm, parse_mode='Markdown')

    # Отправляем ВСЕМ админам с кнопками
    admin_msg = f"""🧙‍♀️ *НОВАЯ АНКЕТА #{anketa_number}* 🧙‍♀️

👤 **Имя:** {anketa['name']}
🕯️ **Дата рождения:** {anketa['age']}
💍 **Семейное положение:** {anketa['family_status']}
👶 **Дети:** {anketa['children']}
✨ **Увлечения:** {anketa['hobbies']}
🔮 **Интересные темы (мк, выезды и тд ):** {anketa['themes']}
🎯 **Цель:** {anketa['goal']}
🌟 **Откуда узнала:** {anketa['source']}

📱 **ID:** `{user_id}`"""

    # Кнопки для админов
    keyboard = [
        [InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{user_id}")],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{user_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Рассылаем всем админам
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, admin_msg, parse_mode='Markdown', reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Не удалось отправить админу {admin_id}: {e}")

    del user_data[user_id]
    return ConversationHandler.END


# ОБРАБОТКА ОДОБРЕНИЯ/ОТКЛОНЕНИЯ
async def approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Проверяем, что это админ
    if not is_admin(query.from_user.id):
        await query.answer("❌ Доступ запрещён", show_alert=True)
        return

    # Парсим callback_data
    action, user_id = query.data.split('_')
    user_id = int(user_id)

    if action == "approve":
        # Отправляем пользователю приглашение
        approval_msg = f"""
🌟 *Поздравляю, сестра!* 🌟

Клуб *ВЕДЬМЫ НЕ СТАРЕЮТ* принял тебя в свой круг! 

Твоя магия достойна нашего сообщества. Переходи по ссылке и присоединяйся к нам:

🔮 {CLUB_CHAT_LINK}

*Добро пожаловать в семью!* 🧙‍♀️✨
        """

        try:
            await context.bot.send_message(user_id, approval_msg, parse_mode='Markdown')
            await query.edit_message_text(
                f"{query.message.text}\n\n✅ *ОДОБРЕНО* — приглашение отправлено!",
                parse_mode='Markdown'
            )
        except Exception as e:
            await query.edit_message_text(
                f"{query.message.text}\n\n⚠️ *Ошибка отправки* (пользователь заблокировал бота)",
                parse_mode='Markdown'
            )

    elif action == "reject":
        # Отправляем пользователю мягкий отказ
        rejection_msg = """
🌙 *Дорогая странница...* 🌙

Клуб *ВЕДЬМЫ НЕ СТАРЕЮТ* благодарит тебя за интерес к нашему сообществу.

К сожалению, в данный момент мы не можем принять твою заявку. Но не расстраивайся — каждая ведьма находит свой путь в своё время. 

Возможно, звёзды сложатся иначе, и мы встретимся позже. 🕯️

*Пусть магия сопровождает тебя!* ✨
        """

        try:
            await context.bot.send_message(user_id, rejection_msg, parse_mode='Markdown')
            await query.edit_message_text(
                f"{query.message.text}\n\n❌ *ОТКЛОНЕНО* — отказ отправлен",
                parse_mode='Markdown'
            )
        except Exception as e:
            await query.edit_message_text(
                f"{query.message.text}\n\n⚠️ *Ошибка отправки* (пользователь заблокировал бота)",
                parse_mode='Markdown'
            )


# АДМИН ПАНЕЛЬ
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.message else update.callback_query.from_user.id
    
    if not is_admin(user_id):
        if update.message:
            await update.message.reply_text("❌ Доступ запрещён")
        else:
            await update.callback_query.answer("❌ Доступ запрещён", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton("📋 Все анкеты", callback_data="all_ankets")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("🎂 Ближайшие ДР", callback_data="upcoming_birthdays")],
        [InlineKeyboardButton("🗑️ Очистить базу", callback_data="clear_db")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    admin_text = "🧙‍♀️ *АДМИН ПАНЕЛЬ ВЕДЬМ* 🧙‍♀️"

    if update.message:
        await update.message.reply_text(admin_text, parse_mode='Markdown', reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text(admin_text, parse_mode='Markdown', reply_markup=reply_markup)


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.answer("❌ Доступ запрещён", show_alert=True)
        return

    # Кнопка "Назад" для всех экранов
    back_button = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin")]]

    if query.data == "back_to_admin":
        await admin_panel(update, context)
        return

    elif query.data == "all_ankets":
        ankets = get_all_applications()  # Загружаем из базы данных
        
        if not ankets:
            msg = "📭 *Анкет пока нет*"
        else:
            msg = f"🧙‍♀️ *ВСЕ АНКЕТЫ ({len(ankets)})* 🧙‍♀️\n\n"
            # Показываем последние 10 анкет
            for ank in ankets[:10]:
                msg += f"**#{ank['id']}** {ank['name']} ({ank['age']})\n"
                msg += f"💍 {ank['family_status']} | 🌟 {ank['source']}\n\n"

        reply_markup = InlineKeyboardMarkup(back_button)
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=reply_markup)

    elif query.data == "clear_db":
        ankets = get_all_applications()
        count = len(ankets)
        clear_all_applications()  # Очищаем базу данных
        msg = f"🧹 *База очищена! Удалено {count} анкет*"
        reply_markup = InlineKeyboardMarkup(back_button)
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=reply_markup)

    elif query.data == "stats":
        ankets = get_all_applications()  # Загружаем из базы данных
        
        if not ankets:
            msg = "📭 *Нет данных для статистики*"
        else:
            total = len(ankets)
            married = sum(1 for a in ankets if 'Замужем' in a['family_status'])
            kids = sum(1 for a in ankets if 'нет детей' not in str(a['children']).lower())

            msg = f"""
📊 *СТАТИСТИКА КЛУБА* 📊
👥 Всего анкет: **{total}**
💍 Замужем: **{married}** ({married / total * 100:.0f}%)
👶 С детьми: **{kids}** ({kids / total * 100:.0f}%)
            """
        
        reply_markup = InlineKeyboardMarkup(back_button)
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=reply_markup)

    elif query.data == "upcoming_birthdays":
        ankets = get_all_applications()  # Загружаем из базы данных
        
        if not ankets:
            msg = "📭 *Анкет пока нет*"
        else:
            birthdays = get_upcoming_birthdays(ankets, limit=10)
            
            if not birthdays:
                msg = "🎂 *Не удалось распознать даты рождения*\n\nПроверьте формат: ДД.ММ.ГГГГ"
            else:
                msg = "🎂 *БЛИЖАЙШИЕ ДНИ РОЖДЕНИЯ* 🎂\n\n"
                
                for i, bd in enumerate(birthdays, 1):
                    if bd['days_until'] == 0:
                        msg += f"🎉 **{bd['name']}** — *СЕГОДНЯ!* ({bd['date']}, {bd['age']} лет)\n\n"
                    elif bd['days_until'] == 1:
                        msg += f"🎈 **{bd['name']}** — *завтра* ({bd['date']}, {bd['age']} лет)\n\n"
                    else:
                        msg += f"{i}. **{bd['name']}** — через {bd['days_until']} дн. ({bd['date']}, будет {bd['age']} лет)\n\n"
        
        reply_markup = InlineKeyboardMarkup(back_button)
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=reply_markup)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧹 *Магия отменена... Возвращайся, когда будешь готова.* 🧹",
                                    parse_mode='Markdown')
    return ConversationHandler.END


def main():
    TOKEN = os.getenv('BOT_TOKEN', '8420325182:AAG7rRYb1iZ-b5pqZaznuUA0X_quHibbJq0')

    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, age)],
            FAMILY_STATUS: [CallbackQueryHandler(family_status, pattern='^(married|single)$')],
            CHILDREN: [MessageHandler(filters.TEXT & ~filters.COMMAND, children)],
            HOBBIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, hobbies)],
            THEMES: [MessageHandler(filters.TEXT & ~filters.COMMAND, themes)],
            GOAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, goal)],
            SOURCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, source)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('admin', admin_panel))
    application.add_handler(CallbackQueryHandler(admin_callback, pattern='^(all_ankets|clear_db|stats|upcoming_birthdays|back_to_admin)$'))
    application.add_handler(CallbackQueryHandler(approval_callback, pattern='^(approve|reject)_'))
    
    # Добавляем watchdog handler для всех сообщений
    application.add_handler(MessageHandler(filters.ALL, watchdog_updater), group=999)

    print("🤖 Бот Ведьм запущен!")
    print("🐕 Watchdog активирован - автоперезапуск при зависании")
    print("🕐 Timezone: UTC+3 (МСК)")
    
    # Запускаем watchdog в отдельном потоке
    watchdog_thread = Thread(target=watchdog.check, daemon=True)
    watchdog_thread.start()
    
    # Запускаем HTTP-сервер параллельно
    loop = asyncio.get_event_loop()
    loop.create_task(run_health_server())
    
    # Сбрасываем watchdog при старте
    watchdog.reset()
    
    # Запускаем polling с увеличенными таймаутами
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        pool_timeout=30,
        read_timeout=30,
        write_timeout=30,
        connect_timeout=30
    )


if __name__ == '__main__':
    main()
