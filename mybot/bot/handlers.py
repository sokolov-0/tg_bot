# handlers.py Обработчики для пользователей
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from asgiref.sync import sync_to_async
from django.conf import settings
from bot.models import Clients
from bot.vpn_service import create_vpn_key
from bot.utils import is_user_subscribed
from telegram.ext import ConversationHandler
from bot.admin_handlers import notify_admin 



logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
GET_STATE_USER_REQUEST = 1
GET_STATE_TARIFF = 2

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    logger.info(f"/start вызван пользователем: {user_id}")

    # Проверка подписки (если требуется)
    if not await is_user_subscribed(user_id, context):
        await update.message.reply_text(
            "Пожалуйста, подпишитесь на наш канал https://t.me/ArtBasilioLife, чтобы продолжить."
        )
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton("Подать заявку", callback_data="user_request")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Нажмите кнопку, чтобы подать заявку на VPN доступ.", reply_markup=reply_markup)
    return GET_STATE_USER_REQUEST

# Обработка заявки пользователя
async def handle_user_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = query.from_user

    # Сохраняем или обновляем заявку в БД
    await sync_to_async(Clients.objects.update_or_create)(
        user_id=user.id,
        defaults={
            "name": user.username or user.first_name,
            "status": "pending"
        }
    )
    await query.edit_message_text("Ваша заявка отправлена на рассмотрение. Ожидайте ответа от администратора.")
    
    # Отправляем уведомление администратору
    await notify_admin(user, context)
    return ConversationHandler.END

# Обработка выбора тарифа
# Обработка выбора тарифа
async def handle_tariff_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")

    if len(data) < 3:
        await query.edit_message_text("Ошибка: некорректные данные тарифа.")
        return ConversationHandler.END

    tariff, user_id_str = data[1], data[2]
    
    try:
        user_id = int(user_id_str)
    except ValueError:
        await query.edit_message_text("Ошибка: неверный ID пользователя.")
        return ConversationHandler.END

    try:
        client_obj = await sync_to_async(Clients.objects.get)(user_id=user_id)
    except Clients.DoesNotExist:
        await query.edit_message_text("Ошибка: клиент не найден.")
        return ConversationHandler.END

    access_url = client_obj.access_url

    if not access_url:
        await query.edit_message_text("Ошибка: не найден accessUrl. Обратитесь в поддержку.")
        return ConversationHandler.END

    await sync_to_async(Clients.objects.filter(user_id=user_id).update)(
        tariff=tariff
    )

    from bot.instructions import INSTRUCTION_TEXT
    tariff2 = ''
    if tariff=='1month':
        tariff2 = 'Один месяц.'
    elif tariff=='3months':
        tariff2 = 'Три месяца.'
    elif tariff=='6months':
        tariff2 = 'Полгода.'
    
    message = (
        f"Ваша заявка одобрена!\n\nТариф: {tariff2}\n\n"
        f"Инструкция по подключению:\n{INSTRUCTION_TEXT}\n\n"
        f"Ваш accessUrl:\n{access_url}"
    )

    try:
        await context.bot.send_message(chat_id=user_id, text=message)
        await query.edit_message_text("Инструкция и данные для подключения отправлены вам в личные сообщения.")
    except Exception as e:
        logger.error(f"Ошибка при отправке данных пользователю: {e}")
        await query.edit_message_text("Ошибка при отправке данных пользователю.")
    
    return ConversationHandler.END

# Команда /cancel
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Диалог завершен.")
    return ConversationHandler.END
