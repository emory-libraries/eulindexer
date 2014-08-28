# urls.py
from django.conf.urls import patterns, include
from django.contrib import admin
from django.views.generic.base import RedirectView

admin.autodiscover()

urlpatterns = patterns('',
    (r'^$', RedirectView.as_view(url='admin/')),
    (r'^admin/', include(admin.site.urls)),
)
