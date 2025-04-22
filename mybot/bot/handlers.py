# handlers.py
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from asgiref.sync import sync_to_async
from django.conf import settings
from bot.models import Clients
from bot.vpn_service import create_vpn_key
from bot.admin_handlers import notify_admin, get_tariff_keyboard  # notify_admin для заявок
from django.utils import timezone
from babel.dates import format_date

logger = logging.getLogger(__name__)

GET_STATE_USER_REQUEST = 1
GET_STATE_TARIFF = 2

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id

    # Если у пользователя уже есть активная подписка — предложить сразу продлить
    today = timezone.now().date()
    try:
        client = await sync_to_async(Clients.objects.get)(user_id=user_id)
    except Clients.DoesNotExist:
        client = None

    if client and client.subscription_end_date and client.subscription_end_date >= today:
        end_str = client.subscription_end_date.strftime('%-d %B %Y')
        text = (
            f"У вас уже есть активная подписка до {end_str}.\n"
            "Хотите продлить её на новый период?"
        )
        keyboard = [
            [InlineKeyboardButton("✅ Да", callback_data=f"renew_yes_{user_id}")],
            [InlineKeyboardButton("❌ Нет", callback_data=f"renew_no_{user_id}")]
        ]
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return GET_STATE_TARIFF

    welcome_text = (
         "Добро пожаловать! 👋\n\n"
         "ArtBasilioBot – бот VPN‑сервиса …\n\n"
         "Нажмите кнопку ниже, чтобы подать заявку. ⬇️"
     )
    keyboard = [[InlineKeyboardButton("Подать заявку", callback_data="user_request")]]
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard))
    return GET_STATE_USER_REQUEST


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    support_text = (
        "Если у вас возникли проблемы, пожалуйста, свяжитесь с технической поддержкой:\n\n"
        "Аккаунт поддержки: @sokolov_000000\n"
        "Часы работы: с 09:00 до 18:00 по МСК\n"
    )
    await update.message.reply_text(support_text)

async def subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    try:
        client = await sync_to_async(Clients.objects.get)(user_id=user_id)
    except Clients.DoesNotExist:
        await update.message.reply_text("У вас пока нет активной подписки. Подайте заявку.")
        return

    today = timezone.now().date()
    if client.subscription_end_date:
        days_left = (client.subscription_end_date - today).days
        formatted_end = format_date(client.subscription_end_date, format="d MMMM yyyy", locale="ru")
    else:
        days_left, formatted_end = None, "не установлена"

    if days_left is None:
        reply_text = "У вас пока не оформлена подписка."
    elif days_left > 0:
        reply_text = (
            f"Ваша подписка активна и истекает {formatted_end}.\n"
            f"До окончания подписки осталось {days_left} дней.\n"
        )
        if days_left < 2:
            reply_text += "Хотите продлить подписку?"
            keyboard = [
                [InlineKeyboardButton("✅ Да", callback_data=f"renew_yes_{user_id}")],
                [InlineKeyboardButton("❌ Нет", callback_data=f"renew_no_{user_id}")]
            ]
            await update.message.reply_text(reply_text, reply_markup=InlineKeyboardMarkup(keyboard))
            return
    else:
        reply_text = "❌ Ваша подписка закончилась, чтобы продолжить, подайте новую заявку."
        keyboard = [[InlineKeyboardButton("Подать заявку", callback_data="user_request")]]
        await update.message.reply_text(reply_text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    await update.message.reply_text(reply_text)

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
    await notify_admin(user, context)  # уведомление для админов о новой заявке
    return ConversationHandler.END

async def handle_tariff_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _, code, user_id_str = query.data.split("_")
    user_id = int(user_id_str)

    tariff_map = {
        "1month": ("1 месяц", "100р"),
        "3months": ("3 месяца", "250р"),
        "6months": ("6 месяцев", "500р")
    }
    tariff_text, tariff_amount = tariff_map[code]

    client = await sync_to_async(Clients.objects.get)(user_id=user_id)
    client.tariff = tariff_text
    client.status = "approved"
    await sync_to_async(client.save)()  # сохраняем только тариф и статус

    # Инструкция по оплате
    payment_instructions = (
        f"Вы выбрали тариф {tariff_text} — {tariff_amount}.\n\n"
        "Переведите нужную сумму на счёт Т‑банка, укажите в комментарии свой Telegram-ник.\n"
        "После перевода нажмите «Я оплатил»."
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("Я оплатил", callback_data=f"user_paid_{user_id}")]])
    await context.bot.send_message(chat_id=user_id, text=payment_instructions, reply_markup=markup)
    await query.edit_message_text("Инструкция по оплате отправлена в ЛС.")
    return ConversationHandler.END


async def handle_payment_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает нажатие кнопки "Я оплатил".
    Обновляет статус платежа и уведомляет администраторов о поступлении платежа.
    """
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    try:
        # Ожидаем данные вида: "user_paid_{user_id}"
        if len(data) < 3:
            await query.edit_message_text("Ошибка данных платежа.")
            return ConversationHandler.END
        user_id = int(data[2])
    except (IndexError, ValueError):
        await query.edit_message_text("Ошибка данных платежа.")
        return ConversationHandler.END

        # Обновляем статус платежа через update()
    updated = await sync_to_async(
        Clients.objects.filter(user_id=user_id).update
    )(payment_status="awaiting_verification")
    if not updated:
        await query.edit_message_text("Ошибка: клиент не найден.")
        return ConversationHandler.END

    # Получаем свежий объект клиента для уведомления админов
    client_obj = await sync_to_async(Clients.objects.get)(user_id=user_id)

    await query.edit_message_text(
        "Спасибо! Ваш платеж отмечен как выполненный. Ожидайте подтверждения администратором."
    )



    from bot.admin_handlers import notify_admin_payment
    await notify_admin_payment(client_obj, context)

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
    if action == "yes":
        tariff_markup = get_tariff_keyboard(user_id)
        await context.bot.send_message(chat_id=user_id, text="Выберите тариф для продления подписки:", reply_markup=tariff_markup)
        await query.edit_message_text("✅ Вы выбрали продлить подписку.")
    else:
        await query.edit_message_text("⚠️ Вы отказались от продления подписки. Доступ будет отключен.")
        logger.info(f"Клиент {user_id} отказался от продления подписки.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Диалог завершен.")
    return ConversationHandler.END
