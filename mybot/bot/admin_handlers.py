# admin_handlers.py Обработка действий администратора
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from asgiref.sync import sync_to_async
from django.conf import settings
from bot.models import Clients
from bot.vpn_service import create_vpn_key
from mybot.settings import ADMIN_IDS

logger = logging.getLogger(__name__)
YOUR_CHAT_ID = settings.YOUR_CHAT_ID

def get_tariff_keyboard(user_id):
    tariff_keyboard = [
        [
            InlineKeyboardButton("1 месяц - 100р", callback_data=f"tariff_1month_{user_id}"),
            InlineKeyboardButton("3 месяца - 250р", callback_data=f"tariff_3months_{user_id}")
        ],
        [InlineKeyboardButton("6 месяцев - 500р", callback_data=f"tariff_6months_{user_id}")]
    ]
    return InlineKeyboardMarkup(tariff_keyboard)



async def handle_admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query.from_user.id not in ADMIN_IDS:
        await update.callback_query.answer("У вас нет прав для выполнения этого действия.", show_alert=True)
        return

    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    if len(data) < 3:
        await query.edit_message_text("Неверные данные заявки.")
        return

    decision, user_id_str = data[1], data[2]
    try:
        user_id = int(user_id_str)
    except ValueError:
        await query.edit_message_text("Неверный ID пользователя.")
        return

    if decision == "approve":
        try:
            client_obj = await sync_to_async(Clients.objects.get)(user_id=user_id)
            logger.info(f"Данные пользователя {user_id}: {client_obj.__dict__}")
        except Clients.DoesNotExist:
            logger.error(f"Ошибка: клиент {user_id} не найден в базе данных.")
            await query.edit_message_text("Ошибка: заявка не найдена в базе.")
            
            return ConversationHandler.END
        # Создаем VPN-ключ и сохраняем данные
        
        key_data = await create_vpn_key(name=client_obj.name, user_id=client_obj.user_id)


        if not key_data:
            await query.edit_message_text("Ошибка: не удалось создать VPN-ключ.")
            return

         # Сохраняем данные в БД
        await sync_to_async(Clients.objects.filter(user_id=user_id).update)(
            vpn_id=str(key_data.get("id")),
            access_url=key_data.get("accessUrl", ""),
            password=key_data.get("password", ""),
            port=key_data.get("port", 0),
            method=key_data.get("method", ""),
            status="approved"
        )

        # После одобрения предлагаем выбрать тариф
        
        tariff_markup = get_tariff_keyboard(user_id)
        
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="Ваша заявка одобрена!\nВыберите тариф для подключения:",
                reply_markup=tariff_markup
            )
            await query.edit_message_text("Заявка одобрена. Тариф отправлен пользователю.")
        except Exception as e:
            logger.error(f"Ошибка при отправке выбора тарифа пользователю: {e}")
            await query.edit_message_text("Ошибка при отправке данных пользователю.")
    elif decision == "reject":
        await sync_to_async(Clients.objects.filter(user_id=user_id).update)(status="rejected")
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="Ваша заявка на VPN доступ отклонена администрацией."
            )
            await query.edit_message_text("Заявка отклонена и уведомление отправлено пользователю.")
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления об отклонении: {e}")
            await query.edit_message_text("Ошибка при отправке уведомления.")
    else:
        await query.edit_message_text("Неверное решение.")

async def notify_admin(user, context: ContextTypes.DEFAULT_TYPE):
    admin_keyboard = [
        [
            InlineKeyboardButton("Одобрить", callback_data=f"admin_approve_{user.id}"),
            InlineKeyboardButton("Отклонить", callback_data=f"admin_reject_{user.id}")
        ]
    ]
    admin_markup = InlineKeyboardMarkup(admin_keyboard)
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"Заявка: пользователь @{user.username or user.first_name} (ID: {user.id}) запросил VPN доступ.",
                reply_markup=admin_markup
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления админу {admin_id}: {e}")
