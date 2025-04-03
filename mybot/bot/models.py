from django.db import models
from datetime import timedelta
from django.utils import timezone
from dateutil.relativedelta import relativedelta

class Clients(models.Model):
    user_id = models.BigIntegerField(verbose_name="ID пользователя")
    vpn_id = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=100, verbose_name="Имя пользователя")
    password = models.CharField(max_length=255, verbose_name="Пароль")
    port = models.IntegerField(verbose_name="Порт", null=True, blank=True, default=0)
    method = models.CharField(max_length=100, verbose_name="Метод шифрования")
    access_url = models.TextField(blank=True, null=True)
    tariff = models.CharField(max_length=50, blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected')
        ],
        default='pending',
        verbose_name="Статус заявки"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    subscription_start_date = models.DateField(blank=True, null=True)
    subscription_end_date = models.DateField(blank=True, null=True)

    def set_subscription_period(self):
        """Устанавливает дату окончания подписки на основе выбранного тарифа."""
        if self.subscription_start_date and self.tariff:
            if self.tariff == "1 месяц":
                self.subscription_end_date = self.subscription_start_date + relativedelta(months=1)
            elif self.tariff == "3 месяца":
                self.subscription_end_date = self.subscription_start_date + relativedelta(months=3)
            elif self.tariff == "6 месяцев":
                self.subscription_end_date = self.subscription_start_date + relativedelta(months=6)

            # Можно добавить другие тарифы по необходимости


    def save(self, *args, **kwargs):
        # Если подписка оформлена и указан тариф, автоматически вычисляем дату окончания
        if self.subscription_start_date and self.tariff:
            self.set_subscription_period()
        super().save(*args, **kwargs)

