# vpn_service.py Взаимодействие с API VPN-сервиса
import logging
import httpx
from asgiref.sync import sync_to_async
from django.conf import settings
from bot.models import Clients

logger = logging.getLogger(__name__)
VPN_BASE_URL = settings.VPN_BASE_URL

async def create_vpn_key(name: str, user_id: int) -> dict:
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

        defaults = {
            "name": key_data.get("name") or name,
            "password": key_data.get("password", ""),
            "port": key_data.get("port", 0),
            "method": key_data.get("method", ""),
            "access_url": key_data.get("accessUrl", ""),
        }

        # Обновляем или создаем запись по user_id
        vpn_key, created = await sync_to_async(Clients.objects.update_or_create)(
            user_id=user_id,
            defaults={**defaults, "vpn_id": str(key_data.get("id"))}
        )
        logger.info(f"VPN-ключ сохранен: {vpn_key}")

        return key_data
