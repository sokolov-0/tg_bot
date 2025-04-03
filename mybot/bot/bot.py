# bot.py
import logging
from telegram.ext import Application, CommandHandler, ConversationHandler, CallbackQueryHandler
from django.conf import settings

from bot.handlers import start, handle_user_request, handle_tariff_selection, cancel
from bot.admin_handlers import handle_admin_decision
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
    # Глобальный обработчик для тарифов, чтобы поймать callback даже после завершения разговора
    application.add_handler(CallbackQueryHandler(handle_tariff_selection, pattern='^tariff_'))

    application.run_polling()

if __name__ == '__main__':
    main()
