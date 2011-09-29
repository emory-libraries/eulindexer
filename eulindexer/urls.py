# urls.py
from django.conf.urls.defaults import *
from django.contrib import admin
from django.views.generic.simple import redirect_to

admin.autodiscover()

urlpatterns = patterns('',
    (r'^$', redirect_to, {'url': 'admin/'}),
    (r'^admin/', include(admin.site.urls)),
)
