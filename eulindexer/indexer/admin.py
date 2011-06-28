# file eulindexer/indexer/admin.py
# 
#   Copyright 2010,2011 Emory University Libraries
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

from django.contrib import admin
from eulindexer.indexer.models import IndexError

class IndexErrorAdmin(admin.ModelAdmin):
    date_hierarchy = 'time'
    list_display = ('object_id', 'site', 'time', 'detail')
    list_filter = ('site',)
    # only allow the the note/details field to be modified via admin site
    readonly_fields = ('object_id', 'site')

    # TODO: details field should probably have a textarea widget

    # disallow adding index errors via admin site
    def has_add_permission(self, request):
        return False

admin.site.register(IndexError, IndexErrorAdmin)
