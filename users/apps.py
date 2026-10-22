from django.apps import AppConfig


class UsersConfig(AppConfig):
    name = 'users'

    def ready(self):
        # Load signals.py so new users get a wallet and a welcome email
        import users.signals  # noqa: F401
