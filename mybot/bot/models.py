from django.db import models
from datetime import timedelta
from django.utils import timezone
from dateutil.relativedelta import relativedelta

class Clients(models.Model):
    user_id = models.BigIntegerField(verbose_name="ID пользователя")
    vpn_id = models.CharField(max_length=255, unique=True,null=True, blank=True)
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

    payment_status = models.CharField(
        max_length=30,
        choices=[
            ('not_paid', 'Not Paid'),
            ('awaiting_verification', 'Awaiting Verification'),
            ('paid', 'Paid'),
            ('failed', 'Failed')
        ],
        default='not_paid',
        verbose_name="Статус платежа"
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    subscription_start_date = models.DateField(blank=True, null=True)
    subscription_end_date   = models.DateField(blank=True, null=True)

    