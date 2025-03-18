from django.db import models

class Client(models.Model):
    user_id = models.BigIntegerField(unique=True)
    info = models.TextField()

    def __str__(self):
        return f"Client {self.user_id}"

