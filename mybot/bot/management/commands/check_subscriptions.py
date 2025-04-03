import logging
import asyncio
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
import httpx
from telegram import Bot
from django.conf import settings
from bot.models import Clients
from babel.dates import format_date
from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)
VPN_BASE_URL = "https://185.125.203.136:58845/ABPwPgIi2fiDV1uS0LKi5Q/access-keys/"

class Command(BaseCommand):
    help = "Проверяет подписки пользователей: отправляет уведомления за день до окончания подписки и отключает пользователей, не продливших подписку."

    async def send_notification(self, bot, client):
        """Отправляет уведомление пользователю о завершении подписки."""
        try:
            formatted_date = format_date(client.subscription_end_date, format="d MMMM yyyy", locale="ru")
            message_text = (
                f"⚠️ Ваш срок подписки истекает завтра ({formatted_date}).\n"
                "Чтобы продолжить пользоваться VPN, пожалуйста, продлите подписку.\n"
                "💳 Доступные тарифы:\n"
                "1 месяц - 100р\n"
                "3 месяца - 250р\n"
                "6 месяцев - 500р"
            )
            await bot.send_message(chat_id=client.user_id, text=message_text)
            self.stdout.write(f"[Уведомление] Клиент {client.user_id}: подписка истекает {formatted_date}")
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления клиенту {client.user_id}: {e}")

    async def get_expiring_clients(self, date):
        """Получает клиентов, у которых подписка истекает именно в 'date'."""
        return await sync_to_async(list)(Clients.objects.filter(status="approved", subscription_end_date=date))

    async def get_expired_clients(self, date):
        """Получает клиентов, у которых подписка закончилась раньше чем 'date'."""
        return await sync_to_async(list)(Clients.objects.filter(status="approved", subscription_end_date__lt=date))

    async def handle_async(self):
        today = timezone.now().date()
        bot = Bot(token=settings.TOKEN)

        # Уведомление за день до окончания подписки:
        # Если сегодня 31.03.2025, then notify_date = 01.04.2025.
        notify_date = today + timedelta(days=1)
        expiring_clients = await self.get_expiring_clients(notify_date)
        tasks = [self.send_notification(bot, client) for client in expiring_clients]
        await asyncio.gather(*tasks)

        # Отключение пользователей, у которых подписка истекла:
        # Если сегодня 02.04.2025, выбираются клиенты, у которых subscription_end_date < 02.04.2025 (например, 01.04.2025)
        expired_clients = await self.get_expired_clients(today)
        for client in expired_clients:
            if client.vpn_id:
                delete_url = f"{VPN_BASE_URL}{client.vpn_id}"
                try:
                    response = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: httpx.delete(delete_url, verify=False)
                    )
                    if response.status_code == 204:
                        self.stdout.write(f"[Отключение] Клиент {client.user_id} отключен (vpn_id: {client.vpn_id})")
                    else:
                        self.stdout.write(f"[Ошибка] Не удалось отключить клиента {client.user_id}, статус: {response.status_code}")
                except Exception as e:
                    logger.error(f"Ошибка при отключении клиента {client.user_id}: {e}")
            else:
                self.stdout.write(f"[Отключение] Клиент {client.user_id} не имеет vpn_id")
            
            # Обновляем статус клиента на 'pending'
            client.status = "pending"
            await sync_to_async(client.save)()
            self.stdout.write(f"[Обновление] Клиент {client.user_id} переведен в статус 'pending'")

    def handle(self, *args, **options):
        asyncio.run(self.handle_async())
