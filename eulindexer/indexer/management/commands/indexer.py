# file eulindexer/indexer/management/commands/indexer.py
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

from datetime import datetime, timedelta
import logging
import os
import urllib2
from optparse import make_option
from socket import error as socketerror
from stompest.simple import Stomp
from stompest.error import StompFrameError
from sunburnt import sunburnt, SolrError
from time import sleep
from urlparse import urlparse

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from eulfedora.rdfns import model as modelns
from eulfedora.models import DigitalObject
from eulfedora.server import Repository

from django.utils import simplejson
from eulindexer.indexer.models import IndexerSettings

logger = logging.getLogger(__name__)

class Command(BaseCommand):

    to_index = {}
    # delay before indexing
    # - since an object may be updated by several API calls in sequence, delay a bit
    #   so that hopefully we only index it once for a single group of updates
    # TODO: make delay configurable
    index_delay = 4  # time delay after the *first* modification message before indexing should be done
    index_delta = timedelta(seconds=index_delay)

    fedora_server = None
    stomp_port = None
    listener = None

    # connection error handling/retry settings (TODO: these should probably be configurable)
    # FIXME: django settings and/or command options?
    retry_wait = 5
    # if we lose the connection to fedora, how long do we wait between attemps to reconnect?
    max_retries = 5
    # how many times do we try to reconnect to fedora before we give up?
    
    option_list = BaseCommand.option_list + (
        make_option('--max_retries', type='int', dest='max_retries', default=max_retries,
                    help='How many times to try reconnecting to Fedora if the connection ' +
                    	 'is lost (default: %default)'),
        make_option('--retry_wait', type='int', dest='retry_wait', default=max_retries,
                    help='How many seconds to wait between reconnect attempts if the ' +
                    	 'connection to Fedora is lost (default: %default)'),

    )

    def init_listener(self):
        if self.fedora_server is None or self.stomp_port is None:
            fedora_info = urlparse(settings.FEDORA_ROOT)
            self.fedora_server, set, fedora_port = fedora_info.netloc.partition(':')
            self.stomp_port = 61613    # TODO: make configurable?

        self.listener = Stomp(self.fedora_server, self.stomp_port)
        self.listener.connect()
        logger.info('Connected to Fedora message queue on %s:%i' % \
                    (self.fedora_server, self.stomp_port))
        self.listener.subscribe('/topic/fedora.apim.update', {'ack': 'client'})  #  can we use auto-ack ?

    def init_cmodel_settings(self, *args, **options):
        self.index_settings = []
        for url in settings.APPLICATION_URLS:
            indexer_setting = IndexerSettings(url)
            self.index_settings.append(indexer_setting)
            response = urllib2.urlopen(url)
            json_value = response.read()
            parsed_json = simplejson.loads(json_value)
            for item, item_value in parsed_json.iteritems():
                if(item == 'SOLR_URL'):
                    indexer_setting.solr_url = item_value
                    logger.info('SOLR URL for %s is: %s' % (url, item_value))
                if(item == 'CONTENT_MODELS'):
                    indexer_setting.CMODEL_list = item_value
                    logger.info('content model for %s is: %s' % (url, item_value))

            indexer_setting.schema = urllib2.urlopen(indexer_setting.solr_url + 'admin/file/?file=schema.xml').read()


    def handle(self, *args, **options):
        # verbosity should be set by django BaseCommand standard options
        v_normal = 1	    # 1 = normal, 0 = minimal, 2 = all
        if 'verbosity' in options:
            verbosity = int(options['verbosity'])
        else:
            verbosity = v_normal

        # override retry/wait default settings if specified
        if 'retry_wait' in options:
            self.retry_wait = options['retry_wait']
        if 'max_retries' in options:
            self.max_retries = options['max_retries']

        # check for required settings

        self.repo = Repository()
        try:
            self.init_listener()
        except socketerror:
            # if we can't connect on start-up, bail out
            # FIXME: is this appropriate behavior? or should we wait and try to connect?
            raise CommandError('Error connecting to %s:%s ' % (self.fedora_server, self.stomp_port) +
                               '- check that Fedora is running and that messaging is enabled ' +
                               'and  configured correctly')

        # body is atom entry... category data includes which  datastream modified when appropriate


        self.init_cmodel_settings()

        if verbosity > 1:
            self.stdout.write('Indexing the following content models, solr indexes, and application combinations:')
            for index_setting in self.index_settings:
                self.stdout.write('\t%s\t\t[ %s ]\t\t[ %s ]' % (index_setting.CMODEL_list, index_setting.solr_url, index_setting.app_url))

        while (True):
            # check if there is a new message, but timeout after 3 seconds so we can process
            # any recently updated objects
            data_available = self.listener.canRead(timeout=self.index_delay)

            # When Fedora is shut down, canRead returns True but we
            # get an exception on the receiveFrame call - catch that
            # error and try to reconnect
            try:

                # if there is a new message, process it
                if data_available:
                    frame = self.listener.receiveFrame()
                    # TODO: use message body instead of headers?  (includes datastream id for modify datastream API calls)
                    pid = frame['headers']['pid']
                    method = frame['headers']['methodName']
                    logger.info('Received message: %s - %s' % (method, pid))
                    self.listener.ack(frame)

                    self.process_message(pid, method)

            except StompFrameError as sfe:
                # this most likely indicates that Fedora is no longer available
                # peirodically attempt to reconnect (within some limits)
                
                logger.error('Received Stomp frame error "%s"' % sfe)
                # wait and try to re-establish the listener
                # - will either return on success or raise a CommandError if
                # it can't connect within the specified time/number of retries
                self.reconnect_listener()


    def reconnect_listener(self):
        '''Attempt to reconnect the listener, e.g. if Fedora is
        shutdown.  Waits the configured time between attemps to
        reconnect; will try to reconnect a configured number of times
        before giving up.'''
        
        # wait the configured time and try to re-establish the listener
        retry_count = 1
        while(retry_count <= self.max_retries):
            sleep(self.retry_wait)
            try:
                self.listener = None
                self.init_listener()
                # if listener init succeeded, return for normal processing
                return
    
            # if fedora is still not available, attempting to
            # listen will generate a socket error
            except socketerror:
                logger.error('Reconnect attempt %d of %d failed; waiting %ds before trying again' % \
                             (retry_count, self.max_retries, self.retry_wait))
                retry_count += 1
        
        # if we reached the max retry without connecting, bail out
        # TODO: better error reporting - should this send an admin email?
        raise CommandError('Failed to reconnect to Fedora after %d retries' % \
                           (retry_count - 1))


    def process_message(self, pid, method):
        # process an update message from fedora
        
        # when an object is purged from fedora, remove it from the index
        if method == 'purgeObject':
            # FIXME: how to make this more generic? (not solr-specific)
            solr = sunburnt.SolrInterface(settings.SOLR_SERVER_URL, settings.SOLR_SCHEMA)
            solr.delete({'PID': pid})
            logger.info('Deleting %s from index' % pid)
            # commit?
            
            # ingest, modify object or modify datastream
        else:
            # if the object isn't already in the queue to be indexed, check if it should be
            if pid not in self.to_index:
                # get content models from resource index
                obj_cmodels = list(self.repo.risearch.get_objects('info:fedora/%s' % pid, modelns.hasModel))

                #UGLY temporary hack. . .
                obj_cmodels.remove('info:fedora/fedora-system:FedoraObject-3.0')
                
                # includes generic content models

                # check if the content models match one of the object types we are indexing
                for index_setting in self.index_settings:
                    if index_setting.CMODEL_match_check(obj_cmodels):
                        self.to_index[pid] = {'time': datetime.now(), 'app_url': index_setting.app_url, 'solr_url': index_setting.solr_url}
                        break

                        
        # check if there are any items that should be indexed now
        if self.to_index:
            logger.debug('objects to be indexed: %r' % self.to_index)

            indexed = []
            for pid in self.to_index.iterkeys():
                try:
                    was_indexed = self.process_index_item(pid)
                    if(was_indexed):
                        indexed.append(pid)
                except Exception as e:
                    logging.error("Failed to index %s for url %s with details: %s" % (pid, self.to_index[pid]['app_url'], e))

            # clear out any pids that were indexed from the list of objects still to be indexed
            for pid in indexed:
                del self.to_index[pid]

    def process_index_item(self, pid):
        '''Attempt to process an item in the index list. If this fails,
        kick up an error to eventually handle so that processing does
        not stop for other items.

        :param pid - the pid of the object to index in the self.to_index queue.
        '''

        # if we've waited the configured delay time, go ahead and index
        #TODO: Fixme BUG: Will never index unless a second item is sent to be indexed . . .
        # TODO: should this be a celery task?
        if datetime.now() - self.to_index[pid]['time'] >= self.index_delta:
            logger.info('triggering index for %s' % pid)
            try:
                response = urllib2.urlopen(self.to_index[pid]['app_url'] + pid)
                json_value = response.read()
            except Exception as connectionError:
                logger.error('Error connecting to %s for %s: %s' % (self.to_index[pid]['app_url'],pid, connectionError))
                raise


            index_data = simplejson.loads(json_value)
            try:
                #TODO: Add caching to the solr schema
                solr_interface = sunburnt.SolrInterface(self.to_index[pid]['solr_url'], self.to_index[pid]['solr_url'] + 'admin/file/?file=schema.xml')
                solr_interface.add(index_data)
                #TODO: Pool updates of similar content items to reduce commits?
                solr_interface.commit()
            except SolrError as se:
                logger.error('Error indexing for %s: %s' % (pid, se))
                raise
                # possible errors: status 404 - solr not running/path incorrectly configured
                # schema error prints nicely, 404 is ugly...

            #Return that item was indeed processed.
            return True

        #Item not processed due to time likely, return false.
        else:
            return False
            
