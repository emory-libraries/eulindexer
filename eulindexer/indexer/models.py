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

import logging
import urllib2

from django.db import models
from django.utils import simplejson

logger = logging.getLogger(__name__)

class IndexError(models.Model):
    'Database model for tracking errors when the indexer fails to process an item.'
    site = models.CharField(max_length=100) 
    object_id = models.CharField(max_length=255)
    time = models.DateTimeField(auto_now=True)
    note = models.CharField(max_length=255)  # any error message text or extra info
    # retry count?

    def __unicode__(self):
        return '%s (%s) %s' % (self.object_id, self.site, self.time)


class IndexerSettings(object):
    def __init__(self, site_url):
        self.site_url = site_url
        self.CMODEL_list = []
        self.solr_url = ''
        self.load_configuration()

    def load_configuration(self):
        # load the index configuration from the specified site url
        response = urllib2.urlopen(self.site_url)
        index_config = simplejson.loads(response.read())
        logger.debug('Index configuration for %s:\n%s' % (self.site_url, index_config))
        
        if 'SOLR_URL' in index_config:
            self.solr_url = index_config['SOLR_URL']
        
        if 'CONTENT_MODELS' in index_config:
            self.CMODEL_list = index_config['CONTENT_MODELS']

        # FIXME: is it an error if either/both of these are not present?

        logger.info('Loaded index configuration for %s:\n\tSOLR url:\t%s\n\tContent Models:\t%s' % \
                        (self.site_url, self.solr_url, self.CMODEL_list))

    def CMODEL_match_check(self, list_of_cmodels):
        match_found = False

        for clist in self.CMODEL_list:
            match_found = True
            for cmodel in clist:
                if not cmodel in list_of_cmodels:
                    match_found = False
                    break


        return match_found
