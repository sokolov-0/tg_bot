import logging
from functools import lru_cache
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    CallbackQueryHandler, ConversationHandler, ContextTypes
)
from telegram.error import BadRequest
from django.conf import settings
from .models import Clients  # Модель для хранения VPN-ключей и/или заявок
import httpx
import asyncio
from asgiref.sync import sync_to_async

VPN_BASE_URL = "https://185.125.203.136:58845/ABPwPgIi2fiDV1uS0LKi5Q/access-keys/"

# Состояния для ConversationHandler (пользовательская часть)
STATE_USER_REQUEST = 1  # пользователь нажал "Подать заявку"
GET_INFO = 2  # новое состояние для получения информации
# Логирование
logging.basicConfig(
    filename='bot.log', 
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Настройки из settings
DB_CONFIG = settings.DB_CONFIG
ADMIN_IDS = settings.ADMIN_IDS # Обязательно список
CHANNEL_ID = settings.CHANNEL_ID
YOUR_CHAT_ID = settings.YOUR_CHAT_ID  # ID, куда отправлять уведомления для админа
TOKEN = settings.TOKEN

# Функция для создания VPN-ключа через VPN-сервис
async def create_vpn_key(name: str) -> dict:
    async with httpx.AsyncClient(verify=False) as client:
        try:
            post_response = await client.post(VPN_BASE_URL)
            post_response.raise_for_status()
            key_data = post_response.json()
        except Exception as e:
            logger.error(f"Ошибка при создании VPN-ключа (POST): {e}")
            return {}

        try:
            key_id = key_data.get("id")
            if not key_id:
                logger.error("Ошибка: key_id отсутствует в ответе API")
                return {}
            put_url = f"{VPN_BASE_URL}{key_id}/name"
            put_response = await client.put(put_url, json={"name": name})
            put_response.raise_for_status()
            try:
                updated_data = put_response.json()
                key_data.update(updated_data)
            except Exception:
                logger.warning("PUT запрос вернул пустой ответ, продолжаем с данными из POST запроса.")
        except Exception as e:
            logger.warning(f"Не удалось задать имя для ключа: {e}")

        # Если API не возвращает дополнительные поля, можно установить их вручную или использовать данные из POST‑ответа
        defaults = {
            "name": key_data.get("name") or name,
            "password": key_data.get("password", ""),  # задайте значение по умолчанию, если необходимо
            "port": key_data.get("port", 0),  # значение по умолчанию, если API не возвращает порт
            "method": key_data.get("method", ""),
            "access_url": key_data.get("accessUrl", ""),
        }

        try:
            vpn_key, created = await sync_to_async(Clients.objects.update_or_create)(
                vpn_id=str(key_data.get("id")),
                defaults=defaults
            )
            logger.info(f"VPN-ключ сохранен: {vpn_key}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении VPN-ключа в базе: {e}")

        return key_data


# Проверка подписки пользователя на канал (если необходимо)
@lru_cache(maxsize=1000)
async def is_user_subscribed(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        chat_member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return chat_member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"Ошибка при проверке подписки: {e}")
        return False

# Команда /start – пользователь начинает диалог
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info(f"/start вызван пользователем: {update.message.from_user.id}")
    user_id = update.message.from_user.id

    # (Опционально) проверка подписки
    if not await is_user_subscribed(user_id, context):
        await update.message.reply_text(
            "Пожалуйста, подпишитесь на наш канал https://t.me/ArtBasilioLife, чтобы продолжить."
        )
        return ConversationHandler.END

    # Предлагаем подать заявку на получение VPN-ключа
    keyboard = [[InlineKeyboardButton("Подать заявку", callback_data="user_request")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Нажмите кнопку, чтобы подать заявку на VPN доступ.", reply_markup=reply_markup)
    return STATE_USER_REQUEST

# Обработка нажатия пользователем кнопки "Подать заявку"
async def handle_user_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user = query.from_user
    # Сохраняем или обновляем заявку в базе с информацией о пользователе
    await sync_to_async(Clients.objects.update_or_create)(
        user_id=user.id,
        defaults={
            "name": user.username or user.first_name,
            "status": "pending"  # заявка подана и ожидает одобрения
        }
    ) 

     # Сообщаем пользователю, что заявка отправлена
    await query.edit_message_text("Ваша заявка отправлена на рассмотрение. Ожидайте ответа от администратора.")

    

    # Отправляем уведомление администратору с заявкой
    admin_keyboard = [
        [
            InlineKeyboardButton("Одобрить", callback_data=f"admin_approve_{user.id}"),
            InlineKeyboardButton("Отклонить", callback_data=f"admin_reject_{user.id}")
        ]
    ]
    admin_reply = InlineKeyboardMarkup(admin_keyboard)
    try:
        await context.bot.send_message(
            chat_id=YOUR_CHAT_ID,
            text=f"Заявка: пользователь @{user.username or user.first_name} (ID: {user.id}) запросил VPN доступ.",
            reply_markup=admin_reply
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке заявки администратору: {e}")

    return ConversationHandler.END

# Обработка решения администратора
async def handle_admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data
    parts = data.split("_")
    if len(parts) < 3:
        await query.edit_message_text("Неверные данные заявки.")
        return

    decision, user_id_str = parts[1], parts[2]
    try:
        user_id = int(user_id_str)
    except ValueError:
        await query.edit_message_text("Неверный ID пользователя.")
        return

    # Используем await, чтобы вызвать асинхронно
    if decision == "approve":
        # Получаем заявку (объект Clients) по user_id
        try:
            client_obj = await sync_to_async(Clients.objects.get)(user_id=user_id)
        except Clients.DoesNotExist:
            await query.edit_message_text("Ошибка: заявка не найдена в базе.")
            return


        key_data = await create_vpn_key(name=client_obj.name)
        if not key_data:
            await query.edit_message_text("Ошибка: не удалось создать VPN-ключ.")
            return

        # Обновляем запись заявки с данными VPN-ключа и меняем статус на "approved"
        vpn_id = str(key_data.get("id"))
        access_url = key_data.get("accessUrl", "")
        password = key_data.get("password", "")
        port = key_data.get("port", 0)
        method = key_data.get("method", "")

        await sync_to_async(Clients.objects.filter(user_id=user_id).update)(
            vpn_id=vpn_id,
            access_url=access_url,
            password=password,
            port=port,
            method=method,
            status="approved"
        )

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Ваша заявка одобрена!\nВаш ключ активации VPN-сервиса:\n\n{access_url}"
            )
            await query.edit_message_text("Заявка одобрена и ключ отправлен пользователю.")
        except Exception as e:
            logger.error(f"Ошибка при отправке ключа пользователю: {e}")
            await query.edit_message_text("Ошибка при отправке ключа пользователю.")
    elif decision == "reject":
        # Обновляем заявку, устанавливая статус "rejected"
        await sync_to_async(Clients.objects.filter(user_id=user_id).update)(status="rejected")
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="Ваша заявка на VPN доступ отклонена администрацией."
            )
            await query.edit_message_text("Заявка отклонена и уведомление отправлено пользователю.")
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления об отклонении: {e}")
            await query.edit_message_text("Ошибка при отправке уведомления об отклонении.")
    else:
        await query.edit_message_text("Неверное решение.")

    
# Получение информации от пользователя (если используется, можно убрать, если не нужно)
async def get_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        await update.message.reply_text("Пожалуйста, введите корректные данные.")
        return ConversationHandler.END

    user_info = update.message.text
    user_id = update.message.from_user.id

    # Пример сохранения дополнительной информации, если требуется
    #await sync_to_async(Clients.objects.create)(user_id=user_id, info=user_info)


    try:
        await context.bot.send_message(
            chat_id=YOUR_CHAT_ID, 
            text=f"Новый запрос от пользователя {user_id}: {user_info}"
        )
    except BadRequest as e:
        logger.error(f"Ошибка при отправке уведомления администратору: {e}")
    except Exception as e:
        logger.error(f"Неизвестная ошибка: {e}")

    await update.message.reply_text("Ожидайте, информация принята.")
    return ConversationHandler.END

# Команда /cancel
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Диалог завершен.")
    return ConversationHandler.END

# Обработка ошибок
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

# Основная функция
def main() -> None:
    application = Application.builder().token(settings.TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            STATE_USER_REQUEST: [CallbackQueryHandler(handle_user_request, pattern='^user_request$')],
            # GET_INFO можно использовать, если требуется ввод дополнительной информации от пользователя
            GET_INFO: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_info)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(handle_admin_decision, pattern='^admin_'))
    # Можно добавить другие обработчики по необходимости
    application.add_error_handler(error_handler)

    application.run_polling()

if __name__ == '__main__':
    main()
