from django.contrib import admin
from .models import Clients

@admin.register(Clients)
class ClientsAdmin(admin.ModelAdmin):
    list_display = ('user_id', 'vpn_id', 'name', 'password', 'port', 'method', 'access_url', 'created_at')
