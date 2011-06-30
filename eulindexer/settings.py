from os import path

# Get the directory of this file for relative dir paths.
# Django sets too many absolute paths.
BASE_DIR = path.dirname(path.abspath(__file__))

# List of callables that know how to import templates from various sources.
TEMPLATE_LOADERS = (
    'django.template.loaders.filesystem.Loader',
    'django.template.loaders.app_directories.Loader',
#    'django.template.loaders.eggs.load_template_source',
)

TEMPLATE_CONTEXT_PROCESSORS = (
    'django.core.context_processors.media',
    'django.contrib.auth.context_processors.auth',
)

ROOT_URLCONF = 'eulindexer.urls'

MIDDLEWARE_CLASSES = (
    'django.middleware.common.CommonMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
)

INSTALLED_APPS = (
    'django.contrib.auth',
    'django.contrib.admin',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'eulfedora',
    'eulindexer.indexer',
)

REPO_DOCUMENT_CLASS = 'fedora.models.DocumentObject'

from localsettings import *

import sys
try:
    sys.path.extend(EXTENSION_DIRS)
except NameError:
    pass # EXTENSION_DIRS not defined. This is OK; we just won't use it.
del sys


try:
    # use xmlrunner if it's installed; default runner otherwise. download
    # it from http://github.com/danielfm/unittest-xml-reporting/ to output
    # test results in JUnit-compatible XML.
    import xmlrunner
    TEST_RUNNER='xmlrunner.extra.djangotestrunner.XMLTestRunner'
    TEST_OUTPUT_DIR='test-results'
    TEST_OUTPUT_DESCRIPTIONS = False
    TEST_OUTPUT_VERBOSE = False
except ImportError:
    pass

