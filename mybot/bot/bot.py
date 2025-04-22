# bot.py
import logging
import asyncio
from telegram.ext import (
    Application, CommandHandler, ConversationHandler, CallbackQueryHandler
)
from django.conf import settings
from bot.handlers import (
    start,
    handle_user_request,
    handle_tariff_selection,
    cancel,
    handle_renewal_choice,
    help_command,
    subscription,
    handle_payment_choice
)
from bot.admin_handlers import handle_admin_decision, handle_payment_confirmation
from bot.utils import GET_STATE_USER_REQUEST, GET_STATE_TARIFF

logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
TOKEN = settings.TOKEN

def main() -> None:
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            GET_STATE_USER_REQUEST: [
                CallbackQueryHandler(handle_user_request, pattern='^user_request$')
            ],
            GET_STATE_TARIFF: [
                CallbackQueryHandler(handle_tariff_selection, pattern='^tariff_')
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(handle_admin_decision, pattern='^admin_'))
    application.add_handler(CallbackQueryHandler(handle_payment_confirmation, pattern='^payment_'))
    application.add_handler(CallbackQueryHandler(handle_renewal_choice, pattern=r"^renew_(yes|no)_\d+$"))
    application.add_handler(CallbackQueryHandler(handle_tariff_selection, pattern='^tariff_'))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('subscription', subscription))
    application.add_handler(CallbackQueryHandler(handle_user_request, pattern='^user_request$'))
    application.add_handler(CallbackQueryHandler(handle_payment_choice, pattern='^user_paid_'))

    # Создаем новый event loop, чтобы он был доступен как текущий
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def set_commands():
        commands = [
            ("start", "🚀 Запуск бота"),
            ("help", "⚙️ Информация техподдержки"),
            ("subscription", "📊 Статус подписки")
        ]
        await application.bot.set_my_commands(commands)

    loop.run_until_complete(set_commands())
    application.run_polling()

if __name__ == '__main__':
    main()
