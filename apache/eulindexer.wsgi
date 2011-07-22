import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'eulindexer.settings'
os.environ['HTTP_PROXY'] = 'http://skoda.library.emory.edu:3128/'
os.environ['VIRTUAL_ENV'] = '/home/httpd/eulindexer/env/'

# Note that you shouldn't need to set sys.path here if in the apache config
# you pass the python-path option to WSGIDaemonProcess as described in the
# sample config.

from django.core.handlers.wsgi import WSGIHandler
application = WSGIHandler()
