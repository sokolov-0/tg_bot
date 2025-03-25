from django.db import models

class Clients(models.Model):
    vpn_id = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=100, verbose_name="Имя пользователя")
    password = models.CharField(max_length=255, verbose_name="Пароль")
    port = models.IntegerField(verbose_name="Порт")
    method = models.CharField(max_length=100, verbose_name="Метод шифрования")
    access_url = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    def __str__(self):
        return f"Clients {self.vpn_id} - {self.name}"

