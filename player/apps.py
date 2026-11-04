from django.apps import AppConfig


class PlayerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'player'

    def ready(self):
        from pathlib import Path

        from django.conf import settings

        template_dir = Path(__file__).resolve().parent / 'features' / 'library_hearts' / 'templates'
        dirs = settings.TEMPLATES[0]['DIRS']
        path = str(template_dir)
        if path not in [str(item) for item in dirs]:
            dirs.append(path)

