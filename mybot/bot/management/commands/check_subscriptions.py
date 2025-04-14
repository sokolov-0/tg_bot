# check_subscriptions.py
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
    help = "Проверяет подписки пользователей и отправляет уведомления."

    async def send_renewal_notification(self, bot, client):
        """Отправляем уведомление с кнопками Да/Нет"""
        try:
            formatted_date = format_date(client.subscription_end_date, format="d MMMM yyyy", locale="ru")
            message_text = (
                f"⚠️ Ваша подписка истекает завтра ({formatted_date}).\n"
                "Хотите продлить подписку?"
            )

            keyboard = [
                [InlineKeyboardButton("✅ Да", callback_data=f"renew_yes_{client.user_id}")],
                [InlineKeyboardButton("❌ Нет", callback_data=f"renew_no_{client.user_id}")]
            ]
            markup = InlineKeyboardMarkup(keyboard)

            await bot.send_message(chat_id=client.user_id, text=message_text, reply_markup=markup)
            self.stdout.write(f"[Уведомление] Клиент {client.user_id}: подписка истекает {formatted_date}")
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления клиенту {client.user_id}: {e}")

    async def handle_async(self):
        """Основной процесс проверки подписок"""
        today = timezone.now().date()
        bot = Bot(token=settings.TOKEN)

        # Уведомление за день до окончания
        notify_date = today + timedelta(days=1)
        expiring_clients = await sync_to_async(list)(
            Clients.objects.filter(status="approved", subscription_end_date=notify_date)
        )
        
        for client in expiring_clients:
            await self.send_renewal_notification(bot, client)

        # Отключение просроченных подписок
        expired_clients = await sync_to_async(list)(
            Clients.objects.filter(status="approved", subscription_end_date__lt=today)
        )
        
        for client in expired_clients:
            if client.vpn_id:
                delete_url = f"{VPN_BASE_URL}{client.vpn_id}"
                try:
                    # Используем синхронный запрос через run_in_executor
                    response = await asyncio.get_running_loop().run_in_executor(
                        None, 
                        lambda: httpx.delete(delete_url, verify=False)
                    )
                    
                    if response.status_code == 204:
                        self.stdout.write(f"[Отключение] Клиент {client.user_id} отключен (vpn_id: {client.vpn_id})")
                        client.status = "pending"
                        await sync_to_async(client.save)()
                    else:
                        self.stdout.write(f"[Ошибка] Не удалось отключить {client.user_id}. Статус: {response.status_code}")
                        logger.error(f"Ответ сервера: {response.text}")
                        
                except Exception as e:
                    logger.error(f"Ошибка при отключении клиента {client.user_id}: {e}")
                    self.stdout.write(f"[Ошибка] Не удалось отключить {client.user_id}: {str(e)}")
            else:
                self.stdout.write(f"[Отключение] Клиент {client.user_id} не имеет vpn_id")
                client.status = "pending"
                await sync_to_async(client.save)()

    def handle(self, *args, **options):
        asyncio.run(self.handle_async())