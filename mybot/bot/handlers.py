# handlers.py Обработчики для пользователей
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from asgiref.sync import sync_to_async
from django.conf import settings
from bot.models import Clients
from bot.vpn_service import create_vpn_key
from bot.utils import is_user_subscribed
from bot.admin_handlers import notify_admin
from django.utils import timezone

logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
GET_STATE_USER_REQUEST = 1
GET_STATE_TARIFF = 2

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    logger.info(f"/start вызван пользователем: {user_id}")
    keyboard = [[InlineKeyboardButton("Подать заявку", callback_data="user_request")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Нажмите кнопку, чтобы подать заявку на VPN доступ.", reply_markup=reply_markup)
    return GET_STATE_USER_REQUEST

# Обработка заявки пользователя
async def handle_user_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    await sync_to_async(Clients.objects.update_or_create)(
        user_id=user.id,
        defaults={
            "name": user.username or user.first_name,
            "status": "pending"
        }
    )
    await query.edit_message_text("Ваша заявка отправлена на рассмотрение. Ожидайте ответа от администратора.")
    await notify_admin(user, context)
    return ConversationHandler.END

# Обработка выбора тарифа
async def handle_tariff_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    if len(data) < 3:
        await query.edit_message_text("Ошибка: некорректные данные тарифа.")
        return ConversationHandler.END

    tariff_code, user_id_str = data[1], data[2]
    try:
        user_id = int(user_id_str)
    except ValueError:
        await query.edit_message_text("Ошибка: неверный ID пользователя.")
        return ConversationHandler.END

    # Преобразуем код тарифа в понятное значение и в текст для сообщения
    if tariff_code == "1month":
        tariff_text = "1 месяц"
        tariff_display = "Один месяц."
    elif tariff_code == "3months":
        tariff_text = "3 месяца"
        tariff_display = "Три месяца."
    elif tariff_code == "6months":
        tariff_text = "6 месяцев"
        tariff_display = "Полгода."
    else:
        tariff_text = tariff_code
        tariff_display = tariff_code

    try:
        client_obj = await sync_to_async(Clients.objects.get)(user_id=user_id)
    except Clients.DoesNotExist:
        await query.edit_message_text("Ошибка: клиент не найден.")
        return ConversationHandler.END

    # Устанавливаем тариф и дату начала подписки, если еще не установлены.
    client_obj.tariff = tariff_text
    if not client_obj.subscription_start_date:
        client_obj.subscription_start_date = timezone.now().date()
    # При сохранении автоматически установится subscription_end_date, если модель реализует эту логику.
    await sync_to_async(client_obj.save)()

    # Если даты подписки не установлены, задаем значения по умолчанию для вывода (чтобы избежать ошибки)
    start_date_str = (
        client_obj.subscription_start_date.strftime('%-d %B %Y г.')
        if client_obj.subscription_start_date else "не установлена"
    )
    end_date_str = (
        client_obj.subscription_end_date.strftime('%-d %B %Y г.')
        if client_obj.subscription_end_date else "не установлена"
    )

    # Проверяем наличие access_url
    access_url = client_obj.access_url
    if not access_url:
        await query.edit_message_text("Ошибка: не найден accessUrl. Обратитесь в поддержку.")
        return ConversationHandler.END

    # Формируем сообщение
    from bot.instructions import INSTRUCTION_TEXT
    message = (
        f"Ваша заявка одобрена!\n\nТариф: {tariff_display}\n"
        f"Подписка активирована с {start_date_str} до {end_date_str}\n\n"
        f"Инструкция по подключению:\n{INSTRUCTION_TEXT}\n\n"
        f"✅✅✅ Ваш accessUrl:\n{access_url}"
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
