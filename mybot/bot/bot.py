import logging
import mysql.connector
from functools import lru_cache
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ConversationHandler, ContextTypes
from telegram.error import BadRequest
from django.conf import settings
from .models import Client

DB_CONFIG = settings.DB_CONFIG
ADMIN_IDS = settings.ADMIN_IDS
CHANNEL_ID = settings.CHANNEL_ID
YOUR_CHAT_ID = settings.YOUR_CHAT_ID
TOKEN = settings.TOKEN

# Состояния для ConversationHandler
GET_SERVICE, GET_INFO = range(2)

# Логирование
logging.basicConfig(filename='bot.log', level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Проверка, является ли пользователь администратором
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# Кэширование проверки подписки на 10 минут
@lru_cache(maxsize=1000)
async def is_user_subscribed(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        chat_member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return chat_member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"Ошибка при проверке подписки: {e}")
        return False

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    is_subscribed = await is_user_subscribed(user_id, context)

    if not is_subscribed:
        await update.message.reply_text("Пожалуйста, подпишитесь на наш канал, чтобы продолжить.")
        return ConversationHandler.END

    # Уведомление администратора о новом подписчике
    try:
        await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=f"Новый подписчик: {update.message.from_user.username} (ID: {user_id})")
    except BadRequest as e:
        logger.error(f"Ошибка при отправке уведомления администратору: {e}")
    except Exception as e:
        logger.error(f"Неизвестная ошибка: {e}")

    keyboard = [[InlineKeyboardButton("Получить услугу", callback_data='get_service')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)
    return GET_SERVICE

# Обработка нажатия кнопки "Получить услугу"
async def get_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Пожалуйста, введите ваше имя:")
    return GET_INFO

# Получение информации от пользователя
async def get_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        await update.message.reply_text("Пожалуйста, введите корректные данные.")
        return GET_INFO

    user_info = update.message.text
    user_id = update.message.from_user.id

    # Сохранение информации в базу данных
    Client.objects.create(user_id=user_id, info=user_info)

    # Уведомление администратора
    try:
        await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=f"Новый запрос от пользователя {user_id}: {user_info}")
    except BadRequest as e:
        logger.error(f"Ошибка при отправке уведомления администратору: {e}")
    except Exception as e:
        logger.error(f"Неизвестная ошибка: {e}")

    # Подтверждение клиенту
    await update.message.reply_text("Ожидайте, информация принята.")
    return ConversationHandler.END

# Команда /clients для администратора
async def clients(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    if not is_admin(user_id):
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    # Получение списка клиентов из базы данных
    clients_list = Client.objects.all()

    logger.info(f"Список клиентов: {clients_list}")  # Логирование списка клиентов

    if not clients_list:
        await update.message.reply_text("Список клиентов пуст.")
        return

    # Создание inline-кнопок для каждого клиента
    keyboard = [[InlineKeyboardButton(client[1], callback_data=f'client_{client[0]}')] for client in clients_list]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите клиента:", reply_markup=reply_markup)

# Обработка выбора клиента
async def select_client(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    # Получение client_id из callback_data
    client_id = query.data.split('_')[1]
    context.user_data['client_id'] = client_id

    # Запрос текста сообщения
    await query.edit_message_text("Введите текст ответа:")
    return GET_INFO

# Отправка сообщения клиенту
async def send_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        await update.message.reply_text("Пожалуйста, введите текст ответа.")
        return GET_INFO

    response_text = update.message.text
    client_id = context.user_data.get('client_id')

    if not client_id:
        await update.message.reply_text("Ошибка: клиент не выбран.")
        return ConversationHandler.END

    # Отправка сообщения клиенту
    try:
        await context.bot.send_message(chat_id=client_id, text=response_text)
        await update.message.reply_text("Ответ отправлен.")
    except BadRequest as e:
        logger.error(f"Ошибка при отправке ответа клиенту: {e}")
        await update.message.reply_text("Ошибка: не удалось отправить сообщение.")
    except Exception as e:
        logger.error(f"Неизвестная ошибка: {e}")
        await update.message.reply_text("Произошла неизвестная ошибка.")

    return ConversationHandler.END

# Команда /cancel
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Диалог завершен.")
    return ConversationHandler.END

# Обработка ошибок
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

# Основная функция
def main() -> None:
    application = Application.builder().token(settings.TOKEN).build()


    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            GET_SERVICE: [CallbackQueryHandler(get_service, pattern='^get_service$')],
            GET_INFO: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_info)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('clients', clients))
    application.add_handler(CallbackQueryHandler(select_client, pattern='^client_'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, send_response))
    application.add_error_handler(error_handler)

    application.run_polling()

if __name__ == '__main__':
    main()