from telegram.ext import (
    Application, CommandHandler, ConversationHandler, CallbackQueryHandler
)
from bot.handlers import start, handle_user_request, handle_tariff_selection, cancel, help_command, subscription, handle_payment_choice, handle_renewal_choice
from bot.admin_handlers import handle_admin_decision, handle_payment_confirmation
from bot.utils import GET_STATE_USER_REQUEST, GET_STATE_TARIFF
import logging, asyncio
from django.conf import settings

import logging

logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def error_handler(update, context):
    logger.exception("Unhandled exception:", exc_info=context.error)

def main():
    application = Application.builder().token(settings.TOKEN).build()

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
        fallbacks=[
            CommandHandler('cancel', cancel),
            CommandHandler('subscription', subscription),  # ✅ ДОБАВЛЕНО
            CommandHandler('start', start),  # ✅ опционально
            ],
        allow_reentry=True
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('subscription', subscription))
    application.add_handler(CallbackQueryHandler(handle_admin_decision, pattern='^admin_'))
    application.add_handler(CallbackQueryHandler(handle_payment_confirmation, pattern='^payment_'))
    application.add_handler(CallbackQueryHandler(handle_tariff_selection, pattern='^tariff_'))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CallbackQueryHandler(handle_user_request, pattern='^user_request$'))
    application.add_handler(CallbackQueryHandler(handle_payment_choice, pattern='^user_paid_'))
    application.add_handler(CallbackQueryHandler(handle_renewal_choice, pattern=r"^renew_(yes|no)_\d+$"))

    application.add_error_handler(error_handler)

    # Регистрируем команды у бота
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    async def set_bot_commands():
        await application.bot.set_my_commands([
            ("start", "🚀 Запустить бота"),
            ("help", "⚙️ Техподдержка"),
            ("subscription", "📊 Статус подписки")
        ])
    loop.run_until_complete(set_bot_commands())

    application.run_polling()

if __name__ == '__main__':
    main()
