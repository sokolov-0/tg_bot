# admin_handlers.py
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from asgiref.sync import sync_to_async
from django.conf import settings
from bot.models import Clients
from bot.vpn_service import create_vpn_key
from mybot.settings import ADMIN_IDS
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from bot.instructions import INSTRUCTION_TEXT


logger = logging.getLogger(__name__)

def get_tariff_keyboard(user_id):
    tariff_keyboard = [
        [
            InlineKeyboardButton("1 месяц - 100р", callback_data=f"tariff_1month_{user_id}"),
            InlineKeyboardButton("3 месяца - 250р", callback_data=f"tariff_3months_{user_id}")
        ],
        [InlineKeyboardButton("6 месяцев - 500р", callback_data=f"tariff_6months_{user_id}")]
    ]
    return InlineKeyboardMarkup(tariff_keyboard)

def get_payment_confirmation_keyboard(user_id, tariff_display, amount):
    keyboard = [
        [
            InlineKeyboardButton(f"Платеж успешен ({amount}р, {tariff_display})", callback_data=f"payment_success_{user_id}"),
            InlineKeyboardButton("Платеж не прошел", callback_data=f"payment_fail_{user_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def notify_admin(user, context: ContextTypes.DEFAULT_TYPE):
    """
    Уведомляет админов о новой заявке.
    Если запись клиента уже создана, можно добавить информацию о выбранном тарифе.
    """
    try:
        client_obj = await sync_to_async(Clients.objects.get)(user_id=user.id)
    except Clients.DoesNotExist:
        client_obj = None

    admin_keyboard = [
        [
            InlineKeyboardButton("Одобрить", callback_data=f"admin_approve_{user.id}"),
            InlineKeyboardButton("Отклонить", callback_data=f"admin_reject_{user.id}")
        ]
    ]
    admin_markup = InlineKeyboardMarkup(admin_keyboard)
    message = f"Заявка: пользователь @{user.username or user.first_name} (ID: {user.id}) запросил VPN доступ."

    # Если запись клиента найдена и у неё есть тариф, добавляем его в сообщение
    if client_obj is not None and hasattr(client_obj, 'tariff') and client_obj.tariff:
        # Можно использовать тариф, если он установлен
        message += f"\nВыбранный тариф: {client_obj.tariff}"
    # Если клиент_obj отсутствует, не обращаемся к его атрибуту tariff

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=message,
                reply_markup=admin_markup
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления админу {admin_id}: {e}")


async def handle_admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query.from_user.id not in ADMIN_IDS:
        await update.callback_query.answer(
            "У вас нет прав для этого действия.", show_alert=True
        )
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
        # === Получаем объект клиента ===
        try:
            client_obj = await sync_to_async(Clients.objects.get)(user_id=user_id)
        except Clients.DoesNotExist:
            logger.error(f"Клиент {user_id} не найден.")
            await query.edit_message_text("Ошибка: заявка не найдена.")
            return ConversationHandler.END

       # === Ставим только статус, без .save(), иначе сработает renew_subscription() преждевременно ===
        updated = await sync_to_async(
            Clients.objects.filter(user_id=user_id, status="pending").update
        )(status="approved")
        if not updated:
            return await query.edit_message_text(
                "⚠️ Эту заявку уже обработал другой администратор."
            )

        logger.info(f"Заявка {user_id} одобрена, даты: {client_obj.subscription_start_date}–{client_obj.subscription_end_date}")

        # === Отправляем тарифы ===
        tariff_markup = get_tariff_keyboard(user_id)
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="Ваша заявка одобрена 🤝!\nПожалуйста, выберите тариф для подключения ⬇️⬇️:",
                reply_markup=tariff_markup
            )
            await query.edit_message_text("Заявка одобрена. Тарифы отправлены пользователю.")
        except Exception as e:
            logger.error(f"Ошибка при отправке тарифов пользователю: {e}")
            await query.edit_message_text("Ошибка при отправке тарифов.")
        return

    elif decision == "reject":
        # простое обновление статуса, без логики дат
        updated = await sync_to_async(
            Clients.objects.filter(user_id=user_id, status="pending").update
        )(status="rejected")
        if not updated:
            return await query.edit_message_text(
                "⚠️ Эту заявку уже обработал другой администратор."
            )
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="😪 Ваша заявка отклонена администрацией. Попробуйте в следующий раз ."
            )
            await query.edit_message_text("Заявка отклонена и пользователь уведомлен.")
        except Exception as e:
            logger.error(f"Ошибка при уведомлении об отклонении: {e}")
            await query.edit_message_text("Ошибка при уведомлении пользователя.")
        return

    else:
        await query.edit_message_text("Неверное решение.")
        return

from django.db import transaction

async def handle_payment_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, result, user_id_str = query.data.split("_")
    user_id = int(user_id_str)

    if query.from_user.id not in ADMIN_IDS:
        return await query.answer("Нет прав.", show_alert=True)

    if result == "success":
        # ———————————————  
        # 1) Атомарно обновляем статус, только если он "awaiting_verification"
        updated = await sync_to_async(
            Clients.objects.filter(user_id=user_id, payment_status="awaiting_verification").update
        )(payment_status="paid")
        if not updated:
            return await query.edit_message_text("⚠️ Этот платёж уже обработан другим администратором.")
        # ———————————————

        # 2) Перезагружаем свежий клиент из БД
        client_obj = await sync_to_async(Clients.objects.get)(user_id=user_id)

        # 3) Рассчитываем новый период подписки
        months = {"1 месяц": 1, "3 месяца": 3, "6 месяцев": 6}.get(client_obj.tariff, 0)
        today = timezone.now().date()
        if client_obj.subscription_end_date and client_obj.subscription_end_date > today:
            new_start = client_obj.subscription_end_date
        else:
            new_start = today
        new_end = new_start + relativedelta(months=months)

        # 4) Сохраняем даты в БД
        await sync_to_async(
            Clients.objects.filter(user_id=user_id).update
        )(
            subscription_start_date=new_start,
            subscription_end_date=new_end
        )

        # 5) Загрузка обновлённого объекта (чтобы увидеть access_url)
        client_obj = await sync_to_async(Clients.objects.get)(user_id=user_id)

        # 6) Генерируем ключ **только если** его реально нет
        if not client_obj.access_url:
            key_data = await create_vpn_key(name=client_obj.name, user_id=client_obj.user_id)
            if not key_data:
                return await query.edit_message_text("Ошибка создания VPN-ключа.")
            # Сохраняем параметры ключа
            await sync_to_async(
                Clients.objects.filter(user_id=user_id).update
            )(
                vpn_id=str(key_data["id"]),
                access_url=key_data["accessUrl"],
                password=key_data["password"],
                port=key_data["port"],
                method=key_data["method"]
            )
            access_url = key_data["accessUrl"]
        else:
            access_url = client_obj.access_url

        # 7) Отправляем пользователю данные
        text = (
            "✅ Платёж подтверждён!\n\n"
            f"Ваш VPN доступ активен до {new_end.strftime('%d.%m.%Y')}.\n\n"
            f"{INSTRUCTION_TEXT}"
        )
        await context.bot.send_message(chat_id=user_id, text=text)

        key_msg = (
            "🔑 Ваш ключ для копирования(просто кликните на него, чтобы скопировать📲 ):\n"
            f"```\n{access_url}\n```"
        )
        await context.bot.send_message(
            chat_id=user_id,
            text=key_msg,
            parse_mode="Markdown"
        )
        await query.edit_message_text("Платёж подтверждён, клиенту отправлены данные.")
    else:
        # аналогично для отказа: только UPDATE и return, без повторного создания
        updated = await sync_to_async(
            Clients.objects.filter(user_id=user_id, payment_status="awaiting_verification").update
        )(payment_status="failed")
        if not updated:
            return await query.edit_message_text("⚠️ Этот платёж уже обработан другим администратором.")
        await context.bot.send_message(chat_id=user_id, text="Платёж не прошёл ❌. Обратитесь в поддержку командой /help ⚙️.")
        await query.edit_message_text("Платёж отклонён.")



async def notify_admin_payment(client_obj, context: ContextTypes.DEFAULT_TYPE):
    """
    Уведомляет администраторов о том, что пользователь нажал кнопку «Я оплатил».
    Сообщение включает выбранный тариф и сумму для оплаты.
    """
    # Определяем сумму и отображаемое название тарифа на основе выбранного тарифа
    tariff_map = {
        "1 месяц": ("1 месяц", "100р"),
        "3 месяца": ("3 месяца", "250р"),
        "6 месяцев": ("6 месяцев", "500р")
    }
    tariff_display, amount = tariff_map.get(client_obj.tariff, ("Неизвестно", "0"))
    message = (
        f"Поступил платеж от пользователя {client_obj.name} (ID: {client_obj.user_id}).\n"
        f"Выбранный тариф: {tariff_display}.\n"
        f"Сумма для оплаты: {amount}.\n"
        "Проверьте перевод в банковском приложении и подтвердите результат."
    )
    keyboard = [
        [
            InlineKeyboardButton("Платеж успешен", callback_data=f"payment_success_{client_obj.user_id}"),
            InlineKeyboardButton("Платеж не прошел", callback_data=f"payment_fail_{client_obj.user_id}")
        ]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=message,
                reply_markup=markup
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления админу {admin_id}: {e}")
