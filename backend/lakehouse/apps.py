from django.apps import AppConfig


class LakehouseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "lakehouse"
    verbose_name = "Lakehouse playground"
