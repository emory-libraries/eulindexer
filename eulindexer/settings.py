# Django settings for eulindexer

import os

# Get the directory of this file for relative dir paths.
# Django sets too many absolute paths.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = True

# If you set this to False, Django will not format dates, numbers and
# calendars according to the current locale
USE_L10N = True

# Absolute filesystem path to the directory that will hold user-uploaded files.
# Example: "/home/media/media.lawrence.com/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, '..', 'media')

# Absolute path to the directory static files should be collected to.
# Don't put anything in this directory yourself; store your static files
# in apps' "static/" subdirectories and in STATICFILES_DIRS.
# Example: "/home/media/media.lawrence.com/static/"
STATIC_ROOT = os.path.join(BASE_DIR, '..', 'static')

# URL prefix for static files.
# Example: "http://media.lawrence.com/static/"
STATIC_URL = '/static/'

# URL prefix for admin static files -- CSS, JavaScript and images.
# Make sure to use a trailing slash.
# Examples: "http://foo.com/static/admin/", "/static/admin/".
ADMIN_MEDIA_PREFIX = '/static/admin/'

# Additional locations of static files
STATICFILES_DIRS = (
    # Put strings here, like "/home/html/static" or "C:/www/django/static".
    # Always use forward slashes, even on Windows.
    # Don't forget to use absolute paths, not relative paths.

    # local sitemedia, if/when we need any
    #os.path.join(BASE_DIR, '..', 'sitemedia'),
)

# List of finder classes that know how to find static files in
# various locations.
STATICFILES_FINDERS = (
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
#    'django.contrib.staticfiles.finders.DefaultStorageFinder',
)

# List of callables that know how to import templates from various sources.
TEMPLATE_LOADERS = (
    'django.template.loaders.filesystem.Loader',
    'django.template.loaders.app_directories.Loader',
#    'django.template.loaders.eggs.load_template_source',
)
TEMPLATE_DIRS = (
    # Put strings here, like "/home/html/django_templates" or "C:/www/django/templates".
    # Always use forward slashes, even on Windows.
    # Don't forget to use absolute paths, not relative paths.
    os.path.join(BASE_DIR, '..', 'templates'),
)


TEMPLATE_CONTEXT_PROCESSORS = (
    # defaults:
    "django.contrib.auth.context_processors.auth",
    "django.core.context_processors.debug",
    "django.core.context_processors.i18n",
    "django.core.context_processors.media",
    "django.core.context_processors.request",
    "django.core.context_processors.static",
    "django.contrib.messages.context_processors.messages",
)

ROOT_URLCONF = 'eulindexer.urls'

MIDDLEWARE_CLASSES = (
    'django.middleware.common.CommonMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
)

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.admin',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.staticfiles',
    'eulfedora',
    'eulindexer.indexer',
    'djcelery',
]

REPO_DOCUMENT_CLASS = 'fedora.models.DocumentObject'

# Celery Config - standard stuff that will not change from project to project
import djcelery
djcelery.setup_loader()

CELERY_RESULT_BACKEND='amqp'
# NOTE: should be possible to configure a default queue, but not sure
# where that needs to be done
CELERY_DEFAULT_QUEUE = 'eulindexer'


#celery backend for rabbitmq
CELERY_BACKEND_TYPE = 'amqp'


# explicitly assign a differently-named default queue to prevent
# collisions with other projects using celery (allow celery to create queue for us)
# NOTE: setting after including localsettings to allow local override
CELERY_ROUTES = {
    'eulindexer.indexer.tasks.index_object': {'queue': CELERY_DEFAULT_QUEUE},
    'eulindexer.indexer.tasks.reindex_object': {'queue': CELERY_DEFAULT_QUEUE}
}

from localsettings import *

# After importing localsettings, if SITE_URL_PREFIX is not blank,
# prefix all statically defined urls above.
try:
    if SITE_URL_PREFIX:
        STATIC_URL = SITE_URL_PREFIX + STATIC_URL
        ADMIN_MEDIA_PREFIX = SITE_URL_PREFIX + ADMIN_MEDIA_PREFIX
except NameError:
    pass


django_nose = None
try:
    # NOTE: errors if DATABASES is not configured (in some cases),
    # so this must be done after importing localsettings
    import django_nose
except ImportError:
    pass

# - only if django_nose is installed, so it is only required for development
if django_nose is not None:
    INSTALLED_APPS.append('django_nose')
    TEST_RUNNER = 'django_nose.NoseTestSuiteRunner'
    NOSE_PLUGINS = [
        # 'eulfedora.testutil.EulfedoraSetUp',
        # ...
    ]
    # NOSE_ARGS = ['--with-eulfedorasetup']
