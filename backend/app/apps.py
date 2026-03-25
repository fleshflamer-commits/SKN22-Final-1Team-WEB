from importlib import import_module

from django.apps import AppConfig as DjangoAppConfig
from django.apps import apps as django_apps
from django.utils.module_loading import module_has_submodule


class AppConfig(DjangoAppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app"
    label = "mirrai_app"

    def import_models(self):
        self.models = django_apps.all_models[self.label]
        if module_has_submodule(self.module, "models_django"):
            self.models_module = import_module(f"{self.name}.models_django")
