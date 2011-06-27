# file eulindexer/indexer/manage.py
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

class IndexerSettings(object):
    def __init__(self, app_url):
        self.app_url = app_url
        self.CMODEL_list = []

    def _set_solr_url(self, val):
        print 'here'
        self.solr_url = val

    def app_url(self):
        return app_url

    def solr_url(self):
        return solr_url

    def _set_CMODEL_list(self, val):
        self.CMODEL_list.append(val)

    def list_CMODELS(self):
        return self.CMODEL_list

    def CMODEL_match_check(self, list_of_cmodels):
        match_found = False

        for clist in self.list_CMODELS():
            match_found = True
            for cmodel in clist:
                if not cmodel in list_of_cmodels:
                    match_found = False
                    break


        return match_found
