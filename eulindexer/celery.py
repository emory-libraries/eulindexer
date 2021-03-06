from __future__ import absolute_import

import os

from celery import Celery

# set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'eulindexer.settings')

from django.conf import settings

app = Celery('eulindexer', backend=getattr(settings, 'CELERY_BACKEND_TYPE', None), broker=getattr(settings, 'BROKER_URL', None))

# Using a string here means the worker will not have to
# pickle the object when using Windows.
app.config_from_object('django.conf:settings')
app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)