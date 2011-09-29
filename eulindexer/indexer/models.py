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

import httplib2
import logging
import socket
import urllib2
import warnings

from django.conf import settings
from django.db import models
from django.utils import simplejson
from httplib2 import iri2uri
from sunburnt import sunburnt, SolrError
import time

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
    
class SiteUnavailable(IOError):
    '''Custom Exception for error condition when a :class:`SiteIndex`
    instance fails to load the site configuration.'''
    pass

class SolrUnavailable(SiteUnavailable):
    '''Subclass of :class:`SiteUnavailable`; indicates the site is
    unavailable because the Solr connection cannot be established'''
    pass


class SiteIndex(object):
    def __init__(self, site_url):
        self.site_url = site_url
        self.solr_url = ''
        self.solr_interface = None
        self.content_models = []
        self.load_configuration()

    def load_configuration(self):
        # load the index configuration from the specified site url
        try:
            response = urllib2.urlopen(self.site_url)
            index_config = simplejson.loads(response.read())
            logger.debug('Index configuration for %s:\n%s' % (self.site_url, index_config))
        except urllib2.URLError as err:
            raise SiteUnavailable(err)
        
        if 'SOLR_URL' in index_config:
            solr_url = index_config['SOLR_URL']
            # work around weirdness in sunburnt or httplib (not sure which).
            # sunburnt (as of 0.5) utf8 encodes index data, but if you pass
            # it a unicode url then it passes that unicode straight through
            # to httplib. when httplib tries to concatenate the unicode url
            # with string index data, python coerces the index data into a
            # unicode object, assumes it's ascii, and throws an exception
            # when it's not. the upshot is that if you pass sunburnt a
            # unicode url, you can't have unicode index data. our solr url
            # comes from a json object and is thus always represented as a
            # unicode object. coerce it into a string (by way of iri2uri in
            # case there are actual non-ascii chars in the iri) so that we
            # can include unicode in our index data.
            solr_url = str(iri2uri(solr_url))
            self.solr_url = solr_url

            # Instantiate a connection to this solr instance.
            try:
                # initialize a solr connection with a customized http connection
                http_opts = {}
                # if a cert file is configured, add it to http options
                if hasattr(settings, 'SOLR_CA_CERT_PATH'):
                    http_opts['ca_certs'] = settings.SOLR_CA_CERT_PATH
                # create a new http connection with the configured options to pass
                # to sunburnt init
                solr_opts = {'http_connection': httplib2.Http(**http_opts)}
                self.solr_interface = sunburnt.SolrInterface(self.solr_url, **solr_opts)
                
            except socket.error as err:
                logger.error('Unable to initialize SOLR connection at (%s) for application url %s' % (self.solr_url, self.site_url))
                raise SolrUnavailable(err)
        
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

    def distinct_content_models(self):
        '''Return a distinct list of all content models that are part of
        any combination of content indexed by this site.'''
        all_cmodels = set()
        for cm in self.content_models:
            all_cmodels |= cm
        return all_cmodels

    def index_item(self, pid):
        '''Actually index an item - request the indexdata from the
        associated site url and update the configured Solr interface.
        Errors could occur at several points: reading the index data
        from the configured indexdata service, parsing the result as
        JSON, or sending the data to Solr.  Any of these will result
        in an exception being raised; errors that are potentially
        recoverable will be raised as some variant of
        :class:`RecoverableIndexError`.

        :param pid - the pid of the object to index; expected to be a
	        key in in the current :attr:`to_index` queue.
        :returns: True when indexing completes successfully
        '''
        indexdata_url = '%s/%s/' % (self.site_url.rstrip('/'), pid)
        logger.debug('Requesting index data for %s at %s' % (pid, indexdata_url))

        try:
            start = time.time()
            response = urllib2.urlopen(indexdata_url)
            json_value = response.read()
            logger.debug('%s %d : %f sec' % (indexdata_url,
                                            response.code,
                                            time.time() - start))
        except Exception as connection_error:
            logger.error('Error connecting to %s for %s: %s' % \
                         (indexdata_url, pid, connection_error))
            # wrap exception and add more detail about what went wrong for db error log
            raise IndexDataReadError('Failed to load index data for %s from %s : %s' % \
                                     (pid, indexdata_url, connection_error))
        
        # it's possible we get data back but it can't be parsed as JSON
        try:
            index_data = simplejson.loads(json_value)
        except ValueError:
            raise Exception('Could not load index data for %s as JSON: %s' % \
                            (pid, json_value))

        try:
            start = time.time()
            self.solr_interface.add(index_data)
            logger.debug('Updated Solr: %f sec' % (time.time() - start))
        except SolrError as se:
            logger.error('Error indexing for %s: %s' % (pid, se))
            raise
	    # possible errors: status 404 - solr not running/path incorrectly configured
            # schema error prints nicely, 404 is ugly...

        # Return that item was successfully indexed
        return True

    def delete_item(self, pid):
        '''Delete an item (identified by pid) from the Solr index.
        Uses the unique field from the configured Solr schema (e.g.,
        ``pid`` or ``PID``) to remove the specified item from the
        index.  If an error occurs on deletion, a
        :class:`sunburnt.SolrError` may be raised.
        
        :param pid - the pid of the object to remove from the index
        '''
        logger.info('Deleting %s=%s' % \
                    (self.solr_interface.schema.unique_field.name, pid))
        self.solr_interface.delete({self.solr_interface.schema.unique_field.name: pid})
        
def init_configured_indexes():
    '''Initialize a :class:`SiteIndex` for each site configured
    in Django settings.

    :returns: a tuple of two dictionaries; the first is a dictionary
       of site name (matching the keys in INDEXER_SITE_URLS) and
       :class:`IndexerSettings` objects; the second is a dictionary of
       any sites that could not be loaded, with the error message.
    '''
    indexes = {}
    errors = {}
    for site, url in settings.INDEXER_SITE_URLS.iteritems():
        try:
            indexes[site] = SiteIndex(url)
        except SolrUnavailable as err:
            errors[site] = 'Solr unavailable: %s' % (err)
        except SiteUnavailable as err:
            errors[site] = err
    return indexes, errors


class RecoverableIndexError(Exception):
    '''Custom Exception wrapper class for an index errors where a
    recovery is possible and the index should be retried.'''
    pass

class IndexDataReadError(RecoverableIndexError):
    '''Custom exception for failure to retrieve the index data for an item; should be considered
    as possibly recoverable, since the site may be temporarily available.'''
    pass


