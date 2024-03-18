from django.urls import path

from telegram_provider import views

app_name = "telegram_provider"
urlpatterns = [
    path("", views.TelegramInbound.as_view(), name="telegram_inbound"),
]
