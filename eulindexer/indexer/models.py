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

from django.conf import settings
from django.db import models
from django.utils import simplejson

from sunburnt import sunburnt, SolrError

logger = logging.getLogger(__name__)

class IndexError(models.Model):
    'Database model for tracking errors when the indexer fails to process an item.'
    site = models.CharField(max_length=100) 
    object_id = models.CharField(max_length=255)
    time = models.DateTimeField(auto_now=True)
    detail = models.CharField(max_length=255, 
        help_text='Error message or any other details about what went wrong')
    # possibly add retry count?

    def __unicode__(self):
        return '%s (%s) %s' % (self.object_id, self.site, self.time)


class SiteIndex(object):
    def __init__(self, site_url):
        self.site_url = site_url
        self.solr_url = ''
        self.solr_interface = None
        self.content_models = []
        self.load_configuration()

    def load_configuration(self):
        # load the index configuration from the specified site url
        response = urllib2.urlopen(self.site_url)
        index_config = simplejson.loads(response.read())
        logger.debug('Index configuration for %s:\n%s' % (self.site_url, index_config))
        
        if 'SOLR_URL' in index_config:
            self.solr_url = index_config['SOLR_URL']

            # Instantiate a connection to this solr instance.
            try:
                self.solr_interface = sunburnt.SolrInterface(self.solr_url)
            except Exception as se:
                logger.error('Unable to initialize SOLR (%s) settings for application url %s' % (self.solr_url, self.site_url))
                raise
        
        if 'CONTENT_MODELS' in index_config:
            # the configuration returns a list of content model lists
            # convert to a list of sets for easier comparison
            self.content_models = [set(cm_list) for cm_list in index_config['CONTENT_MODELS']]

        # FIXME: is it an error if either/both of these are not present?

        # log a summary of the configuration of the configuration that was loaded
        logger.info(self.config_summary())

    def config_summary(self):
        '''Returns a string summarizing the configuration for this SiteIndex.'''
        summary = 'Index configuration for %s' % self.site_url
        summary += '\n  Solr url: %s' % self.solr_url
        # list each group of cmodels on one line, so it easier to see how they are grouped
        summary += '\n  Content Models:\n\t%s' % '\n\t'.join(', '.join(group) for group in self.content_models)
        return summary

    def indexes_item(self, content_models):
        '''Check if this :class:`SiteIndex` instance indexes a
        particular item.  Currently compares by a list of content
        models.

        :param content_models: a list of content models for the item
        :returns: True if the specified content models indicate that
          the item should be indexed by this SiteIndex; otherwise, False.
        '''
        content_models = set(content_models)
        # check each set of content models
        for cm_set in self.content_models:
            # if every content model in our list is included, we want to index it
            if cm_set.issubset(content_models):
                return True

        # if no match was found, we don't index this object
        return False


def init_configured_indexes():
    '''Initialize a :class:`SiteIndex` for each site configured
    in Django settings.  Returns a dictionary of site name (matching
    the keys in INDEXER_SITE_URLS) and :class:`IndexerSettings`
    objects.'''
    indexes = {}
    for site, url in settings.INDEXER_SITE_URLS.iteritems():
        indexes[site] = SiteIndex(url)
    return indexes
    
