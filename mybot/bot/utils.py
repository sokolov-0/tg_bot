# utils.py Вспомогательные функции
import logging
from functools import lru_cache
from telegram.ext import ContextTypes
from django.conf import settings

logger = logging.getLogger(__name__)
CHANNEL_ID = settings.CHANNEL_ID

@lru_cache(maxsize=1000)
async def is_user_subscribed(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        chat_member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return chat_member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"Ошибка при проверке подписки: {e}")
        return False

# Константы для состояний диалога
GET_STATE_USER_REQUEST = 1
GET_STATE_TARIFF = 2
