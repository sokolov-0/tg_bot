import logging
import mysql.connector
from functools import lru_cache
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ConversationHandler, ContextTypes
from telegram.error import BadRequest
from django.conf import settings
from .models import Clients
import httpx
import asyncio

VPN_BASE_URL = "https://185.125.203.136:58845/ABPwPgIi2fiDV1uS0LKi5Q/access-keys/"

async def create_vpn_key(name: str = "Активирован") -> dict:
    """
    Создает новый ключ доступа через VPN-сервис и возвращает данные ключа.
    """
    async with httpx.AsyncClient(verify=False) as client:
        # Отправляем POST-запрос для создания нового ключа
        try:
            post_response = await client.post(VPN_BASE_URL)
            post_response.raise_for_status()
            key_data = post_response.json()
        except Exception as e:
            logger.error(f"Ошибка при создании VPN-ключа: {e}")
            return {}
        
        # Присваиваем имя, используя переданное значение
        try:
            key_id = key_data.get("id")
            if not key_id:
                logger.error("Ошибка: key_id отсутствует в ответе API")
                return {}
            if key_id:
                put_url = f"{VPN_BASE_URL}{key_id}/name"
                put_response = await client.put(put_url, json={"name": name})
                put_response.raise_for_status()
                # Обновляем данные ключа, если API возвращает обновленные данные
                key_data.update(put_response.json())
        except Exception as e:
            logger.warning(f"Не удалось задать имя для ключа: {e}")
            # Если присвоение имени не критично – можно продолжить
        
        try:
            # Предполагаем, что key_data содержит все необходимые поля:
            vpn_key, created = Clients.objects.update_or_create(
                vpn_id=key_data.get("id"),
                defaults={
                    "name": key_data.get("name", name),
                    "password": key_data.get("password", ""),
                    "port": key_data.get("port", 0),
                    "method": key_data.get("method", ""),
                    "access_url": key_data.get("accessUrl", "")
                }
            )
            logger.info(f"VPN-ключ сохранен: {vpn_key}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении VPN-ключа в базе: {e}")

        return key_data

    



DB_CONFIG = settings.DB_CONFIG
ADMIN_IDS = [795347299]
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
    logger.info(f"/start вызван пользователем: {update.message.from_user.id}")
    user_id = update.message.from_user.id
    is_subscribed = await is_user_subscribed(user_id, context)

    if not is_subscribed:
        await update.message.reply_text("Пожалуйста, подпишитесь на наш канал https://t.me/ArtBasilioLife, чтобы продолжить.")
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

    username = query.from_user.username if query.from_user.username else "Активирован"


    # Вызов функции создания VPN-ключа
    key_data = await create_vpn_key(name=username)
    if not key_data:
        await query.edit_message_text("Ошибка: не удалось создать VPN-ключ.")
        return ConversationHandler.END

    # Формируем сообщение с информацией ключа
    # Здесь можно выбрать нужное поле, например accessUrl
    access_url = key_data.get("accessUrl", "Нет данных")
    message = f"Ваш ключ активации VPN-сервиса:\n\n{access_url}"

    await query.edit_message_text(message)
    return ConversationHandler.END


# Получение информации от пользователя
async def get_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        await update.message.reply_text("Пожалуйста, введите корректные данные.")
        return GET_INFO

    user_info = update.message.text
    user_id = update.message.from_user.id

    # Сохранение информации в базу данных
    Clients.objects.create(user_id=user_id, info=user_info)

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
    clients_list = Clients.objects.all()

    logger.info(f"Список клиентов: {clients_list}")  # Логирование списка клиентов

    if not clients_list:
        await update.message.reply_text("Список клиентов пуст.")
        return

    # Создание inline-кнопок для каждого клиента
    keyboard = [[InlineKeyboardButton(client.name, callback_data=f'client_{client.user_id}')] for client in clients_list]
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