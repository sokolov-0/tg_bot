# check_subscriptions.py:
import logging
import asyncio
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
import httpx
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from django.conf import settings
from bot.models import Clients
from babel.dates import format_date
from asgiref.sync import sync_to_async
from bot.admin_handlers import get_tariff_keyboard

logger = logging.getLogger(__name__)
VPN_BASE_URL = settings.VPN_BASE_URL

class Command(BaseCommand):
    help = ("Проверяет подписки пользователей и отправляет уведомления:\n"
            " – если подписка истекает завтра, спрашивает, хотите продлить подписку;\n"
            " – если подписка закончилась, отключает клиента и уведомляет о необходимости подать новую заявку.")

    async def send_renewal_notification(self, bot, client):
        """Отправляет уведомление с вопросом о продлении подписки."""
        try:
            formatted_date = format_date(client.subscription_end_date, format="d MMMM yyyy", locale="ru")
            message_text = (
                f"⚠️ Ваша подписка истекает завтра ({formatted_date}).\n"
                "Хотите продлить подписку?"
            )
            # Кнопки для выбора: "Да" и "Нет"
            keyboard = [
                [InlineKeyboardButton("✅ Да", callback_data=f"renew_yes_{client.user_id}")],
                [InlineKeyboardButton("❌ Нет", callback_data=f"renew_no_{client.user_id}")]
            ]
            markup = InlineKeyboardMarkup(keyboard)
            await bot.send_message(chat_id=client.user_id, text=message_text, reply_markup=markup)
            self.stdout.write(f"[Уведомление] Клиент {client.user_id}: подписка истекает {formatted_date}")
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления клиенту {client.user_id}: {e}")

    async def send_expired_notification(self, bot, client):
        """
        Отправляет уведомление клиенту, что его подписка закончилась,
        и предлагает подать новую заявку (аналогично кнопке /start).
        """
        try:
            message_text = (
                "❌ Ваша подписка закончилась, вы больше не можете пользоваться VPN.\n"
                "Чтобы продолжить, пожалуйста, подайте новую заявку."
            )
            keyboard = [
                [InlineKeyboardButton("Подать заявку", callback_data="user_request")]
            ]
            markup = InlineKeyboardMarkup(keyboard)
            await bot.send_message(chat_id=client.user_id, text=message_text, reply_markup=markup)
            self.stdout.write(f"[Уведомление] Клиент {client.user_id}: уведомление об окончании подписки отправлено.")
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления об окончании подписки клиенту {client.user_id}: {e}")

    async def get_expiring_clients(self, date):
        """Возвращает список клиентов с подпиской, истекающей ровно в 'date'."""
        return await sync_to_async(list)(Clients.objects.filter(status="approved", subscription_end_date=date))

    async def get_expired_clients(self, date):
        """Возвращает список клиентов, у которых подписка закончилась (<= 'date')."""
        return await sync_to_async(list)(Clients.objects.filter(status="approved", subscription_end_date__lte=date))

    async def handle_async(self):
        today = timezone.now().date()
        bot = Bot(token=settings.TOKEN)

        # 1. Уведомление клиентам, у которых подписка истекает завтра:
        notify_date = today + timedelta(days=1)
        expiring_clients = await self.get_expiring_clients(notify_date)
        self.stdout.write(f"[DEBUG] Найдено {len(expiring_clients)} клиентов с подпиской, истекающей {notify_date}")
        for client in expiring_clients:
            await self.send_renewal_notification(bot, client)

        # 2. Обработка клиентов с истекшей подпиской (<= сегодня):
        expired_clients = await self.get_expired_clients(today)
        for client in expired_clients:
            # 1) удаляем ключ на стороне VPN
            if client.vpn_id:
                delete_url = f"{VPN_BASE_URL}{client.vpn_id}"
                try:
                    resp = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: httpx.delete(delete_url, verify=False)
                    )
                    if resp.status_code == 204:
                        self.stdout.write(f"[Отключение] Клиент {client.user_id} отключен (vpn_id: {client.vpn_id})")
                    else:
                        self.stdout.write(f"[Ошибка] Не удалось отключить клиента {client.user_id}, статус {resp.status_code}")
                except Exception as e:
                    logger.error(f"Ошибка при отключении клиента {client.user_id}: {e}")

            # 2) Очищаем локально все поля ключа
            client.vpn_id           = ""
            client.access_url       = ""
            client.password         = ""
            client.port             = 0
            client.method           = ""
            client.payment_status   = "not_paid"
            client.status           = "pending"
            client.tariff = ""
            # при желании можно и subscription_start_date/subscription_end_date занулять,
            # но обычно они остаются для истории

            await sync_to_async(client.save)()
            self.stdout.write(f"[Обновление] Клиент {client.user_id}: сброшен ключ и переведен в 'pending'")

            # 3) шлём пользователю уведомление о том, что нужно заново подать заявку
            await self.send_expired_notification(bot, client)


    def handle(self, *args, **options):
        asyncio.run(self.handle_async())
