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
from telegram.ext import CallbackQueryHandler
from bot.admin_handlers import get_tariff_keyboard 

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




async def handle_renewal_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        data = query.data.split("_")
        action, user_id = data[1], int(data[2])
    except (IndexError, ValueError):
        await query.edit_message_text("Ошибка обработки запроса")
        return
    
    try:
        if action == "yes":
            tariff_markup = get_tariff_keyboard(user_id)
            await context.bot.send_message(
                chat_id=user_id,
                text="Выберите тариф для продления подписки:",
                reply_markup=tariff_markup
            )
            await query.edit_message_text("✅ Вы выбрали продлить подписку.")
        else:
            await query.edit_message_text("❌ Вы отказались от продления подписки.")
            # Здесь можно добавить логику отключения
    except Exception as e:
        logger.error(f"Ошибка в обработке продления: {e}")
        await query.edit_message_text("⚠️ Произошла ошибка при обработке запроса")



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

    # Определяем выбранный тариф
    tariff_map = {
        "1month": ("1 месяц", "Один месяц"),
        "3months": ("3 месяца", "Три месяца"),
        "6months": ("6 месяцев", "Полгода")
    }
    
    if tariff_code not in tariff_map:
        await query.edit_message_text("Ошибка: недопустимый тариф.")
        return ConversationHandler.END
        
    tariff_text, tariff_display = tariff_map[tariff_code]

    try:
        # Получаем и обновляем запись клиента
        client_obj = await sync_to_async(Clients.objects.get)(user_id=user_id)
        client_obj.tariff = tariff_text
        client_obj.status = "approved"  # Критически важная строка!
        
        # Сохраняем изменения (автоматически вызовется renew_subscription)
        await sync_to_async(client_obj.save)()
        
    except Clients.DoesNotExist:
        await query.edit_message_text("Ошибка: клиент не найден.")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка обновления подписки: {e}")
        await query.edit_message_text("Ошибка при обновлении подписки.")
        return ConversationHandler.END

    # Форматирование дат для сообщения
    start_date = client_obj.subscription_start_date.strftime('%-d %B %Y г.') if client_obj.subscription_start_date else "не установлена"
    end_date = client_obj.subscription_end_date.strftime('%-d %B %Y г.') if client_obj.subscription_end_date else "не установлена"

    # Проверка access_url
    if not client_obj.access_url:
        await query.edit_message_text("Ошибка: не найден accessUrl. Обратитесь в поддержку.")
        return ConversationHandler.END

    # Отправка сообщения пользователю
    try:
        from bot.instructions import INSTRUCTION_TEXT
        message = (
            f"✅ Подписка обновлена!\n\n"
            f"Тариф: {tariff_display}\n"
            f"Новый период: с {start_date} до {end_date}\n\n"
            f"{INSTRUCTION_TEXT}\n\n"
            f"🔑 Ваш accessUrl:\n{client_obj.access_url}"
        )
        
        await context.bot.send_message(chat_id=user_id, text=message)
        await query.edit_message_text("Данные для подключения отправлены в личные сообщения.")
        
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")
        await query.edit_message_text("Ошибка при отправке данных.")

    return ConversationHandler.END

 
# Команда /cancel
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Диалог завершен.")
    return ConversationHandler.END
