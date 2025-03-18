from django.core.management.base import BaseCommand
from bot.bot import main  # Импортируйте основную функцию из вашего файла bot.py

class Command(BaseCommand):
    help = "Запускает Telegram-бота"

    def handle(self, *args, **options):
        self.stdout.write("Запуск бота...")
        main()
