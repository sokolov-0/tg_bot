from django.db import models

class Clients(models.Model):
    user_id = models.BigIntegerField(verbose_name="ID пользователя")
    vpn_id = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=100, verbose_name="Имя пользователя")
    password = models.CharField(max_length=255, verbose_name="Пароль")
    port = models.IntegerField(verbose_name="Порт", null=True, blank=True, default=0)
    method = models.CharField(max_length=100, verbose_name="Метод шифрования")
    access_url = models.TextField(blank=True, null=True)
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

    def __str__(self):
        return f"Clients {self.vpn_id} - {self.name}"

