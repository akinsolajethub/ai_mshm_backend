import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
import django
django.setup()
from apps.accounts.models import User
count, _ = User.objects.filter(email="owoadeshefiq12@gmail.com").delete()
print("deleted", count)
