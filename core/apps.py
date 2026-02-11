from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        # Import lazily to avoid touching app registry before startup is complete.
        from django.db.models.signals import post_migrate

        from .bootstrap import bootstrap_after_migrate

        post_migrate.connect(
            bootstrap_after_migrate,
            sender=self,
            dispatch_uid="core.bootstrap_after_migrate",
        )
