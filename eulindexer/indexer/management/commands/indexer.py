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
from eulindexer.indexer.models import SiteIndex, IndexError, \
     init_configured_indexes, RecoverableIndexError

logger = logging.getLogger(__name__)

class Command(BaseCommand):

    to_index = {}
    # delay before indexing
    # - since an object may be updated by several API calls in sequence, delay a bit
    #   so that hopefully we only index it once for a single group of updates
    # TODO: make delay configurable
    index_delay = 4  # time delay after the *first* modification message before indexing should be done
    index_delta = timedelta(seconds=index_delay)
    index_max_tries = 3  # number of times to try indexing an item, if a recoverable error happens

    fedora_server = None
    stomp_port = None
    listener = None

    # connection error handling/retry settings (TODO: these should probably be configurable)
    # FIXME: django settings and/or command options?
    retry_reconnect_wait = 5
    # if we lose the connection to fedora, how long do we wait between attemps to reconnect?
    max_reconnect_retries = 5
    # how many times do we try to reconnect to fedora before we give up?
    
    option_list = BaseCommand.option_list + (
        make_option('--max-reconnect-retries', type='int', dest='max_reconnect_retries',
                    default=max_reconnect_retries,
                    help='How many times to try reconnecting to Fedora if the connection ' +
                    	 'is lost (default: %default)'),
        make_option('--retry-reconnect-wait', type='int', dest='retry_reconnect_wait',
                    default=retry_reconnect_wait,
                    help='How many seconds to wait between reconnect attempts if the ' +
                    	 'connection to Fedora is lost (default: %default)'),
        make_option('--index-max-tries', type='int', dest='index_max_tries',
                    default=index_max_tries,
                    help='Number of times to attempt indexing an item when a potentially ' +
                    	 'recoverable error is encountered'),

    )

    def init_listener(self):
        if self.fedora_server is None or self.stomp_port is None:
            fedora_info = urlparse(settings.FEDORA_ROOT)
            self.fedora_server, set, fedora_port = fedora_info.netloc.partition(':')
            self.stomp_port = 61613    # TODO: make configurable?

        self.listener = Stomp(settings.INDEXER_STOMP_SERVER, settings.INDEXER_STOMP_PORT)
        self.listener.connect()
        logger.info('Connected to Fedora message queue on %s:%i' % \
                    (self.fedora_server, self.stomp_port))
        self.listener.subscribe(settings.INDEXER_STOMP_CHANNEL, {'ack': 'client'})  #  can we use auto-ack ?

    def handle(self, *args, **options):
        # verbosity should be set by django BaseCommand standard options
        v_normal = 1	    # 1 = normal, 0 = minimal, 2 = all
        if 'verbosity' in options:
            verbosity = int(options['verbosity'])
        else:
            verbosity = v_normal

        # override retry/wait default settings if specified
        if 'retry_reconnect_wait' in options:
            self.retry_reconnect_wait = options['retry_reconnect_wait']
        if 'max_reconnect_retries' in options:
            self.max_reconnect_retries = options['max_reconnect_retries']
        if 'index-max-tries' in options:
            self.index_max_tries = options['index-max-tries']

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

        self.indexes = init_configured_indexes()
    
        if verbosity > v_normal:
            self.stdout.write('Indexing the following sites:\n')
            for site, index in self.indexes.iteritems():
                self.stdout.write('\t%s\n' % site)
                self.stdout.write(index.config_summary())

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

            #Process the index queue for any items that need it.
            self.process_queue()


    def reconnect_listener(self):
        '''Attempt to reconnect the listener, e.g. if Fedora is
        shutdown.  Waits the configured time between attemps to
        reconnect; will try to reconnect a configured number of times
        before giving up.'''
        
        # wait the configured time and try to re-establish the listener
        retry_count = 1
        while(retry_count <= self.max_reconnect_retries):
            sleep(self.retry_reconnect_wait)
            try:
                self.listener = None
                self.init_listener()
                # if listener init succeeded, return for normal processing
                return
    
            # if fedora is still not available, attempting to
            # listen will generate a socket error
            except socketerror:
                logger.error('Reconnect attempt %d of %d failed; waiting %ds before trying again' % \
                             (retry_count, self.max_reconnect_retries, self.retry_reconnect_wait))
                retry_count += 1
        
        # if we reached the max retry without connecting, bail out
        # TODO: better error reporting - should this send an admin email?
        raise CommandError('Failed to reconnect to Fedora after %d retries' % \
                           (retry_count - 1))
    

    def process_message(self, pid, method):
        # process an update message from fedora
        
        # when an object is purged from fedora, remove it from the index
        if method == 'purgeObject':
            # since we don't know which index (if any) this object was indexed in,
            # delete it from all configured indexes
            for index in self.indexes.itervalues():
                # pid is the required solr id in the base DigitalObject; assuming people won't change that
                index.solr_interface.delete({'pid': pid})
                # TODO: index error if we get a SolrError here
            logger.info('Deleting %s from all configured Solr indexes' % pid)
            # commit?
            
        # ingest, modify object or modify datastream
        else:
            # if the object isn't already in the queue to be indexed, check if it should be
            if pid not in self.to_index:
                # get content models from resource index
                obj_cmodels = list(self.repo.risearch.get_objects('info:fedora/%s' % pid, modelns.hasModel))
                # may include generic content models, but should not be a problem

                # check if the content models match one of the object types we are indexing
                for site, index in self.indexes.iteritems():
                    if index.indexes_item(obj_cmodels):
                        self.to_index[pid] = {'time': datetime.now(), 'site': site, 'tries': 0}
                        break

    def process_queue(self):
        '''Loop through items that have been queued for indexing; if
        the configured delay time has passed, then attempt to index
        them, and log any indexing errors.'''
        #check if there are any items that should be indexed now
        if self.to_index:
            logger.debug('Objects queued to be indexed: %s' % ', '.join(self.to_index.keys()))

            queue_remove = []	
            for pid in self.to_index.iterkeys():
                try:
                    # if we've waited the configured delay time, attempt to index
                    if datetime.now() - self.to_index[pid]['time'] >= self.index_delta:
                        logger.debug('Triggering index for %s' % pid)
                        # tell the site index to index the item - returns True on success
                        if self.indexes[self.to_index[pid]['site']].index_item(pid):
                            queue_remove.append(pid)
                        
                except RecoverableIndexError as rie:
                    # If the index attempt resulted in error that we
                    # can potentially recover from, keep the item in
                    # the queue and attempt to index it again.

                    # Increase the count of index attempts, so we know when to stop.
                    self.to_index[pid]['tries'] += 1
                    
                    # quit when we reached the configured number of index attempts
                    if self.to_index[pid]['tries'] >= self.index_max_tries:
                        logging.error("Failed to index %s (%s) after %d tries: %s" % \
                                     (pid, self.to_index[pid]['site'], self.to_index[pid]['tries'], rie))
                        
                        err = IndexError(object_id=pid, site=self.to_index[pid]['site'],
                                         detail='Failed to index after %d attempts: %s' % \
                                         (self.to_index[pid]['tries'], rie))
                        err.save()
                        # we've hit the index retry limit, so remove from the queue
                        queue_remove.append(pid)
                        
                    else:
                        logging.warn("Recoverable error attempting to index %s (%s), %d tries: %s" % \
                                     (pid, self.to_index[pid]['site'], self.to_index[pid]['tries'], rie))

                        # update the index time - wait the configured index delay before
                        # attempting to reindex again
                        self.to_index[pid]['time'] = datetime.now()
                    
                except Exception as e:
                    logging.error("Failed to index %s (%s): %s" % \
                                      (pid, self.to_index[pid]['site'], e))

                    # Add a prefix to the detail error message if we
                    # can identify what type of error this is.
                    detail_type = ''
                    if isinstance(e, SolrError):
                        detail_type = 'Solr Error: '
                    msg = '%s%s' % (detail_type, e)
                    err = IndexError(object_id=pid, site=self.to_index[pid]['site'],
                                     detail=msg)
                    err.save()

                    # any exception not caught in the recoverable error block should be
                    # removed from the index queue
                    queue_remove.append(pid)


            # clear out any pids that were indexed successfully OR
            # errored from the list of objects still to be indexed
            for pid in queue_remove:
                del self.to_index[pid]
                            
