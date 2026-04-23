import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
import django
django.setup()

from django.test import Client

c = Client()
resp = c.post('/api/v1/auth/login/',
    data={'email': 'ifebanks02@gmail.com', 'password': 'testpass123'},
    content_type='application/json',
    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
print('Status:', resp.status_code)
print('Response:', resp.json())