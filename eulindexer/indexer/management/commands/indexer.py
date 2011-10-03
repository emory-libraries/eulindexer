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

'''
The **indexer** should be started via manage.py::

  $ python manage.py indexer

The **indexer** will load index configurations from the sites
configured in ``localsettings.py``, initialize Solr connections, and
start listening to the configured Fedora STOMP port for changes that
should trigger an index update.

Available options (use ``python manage.py indexer -h`` for more
details)::

  --max-reconnect-retries
     The number of times the indexer should attempt to reconnect to
     Fedora if the connection is lost.

  --retry-reconnect-wait
     The time that the indexer should wait between attempts to
     reconnect to Fedora if the connection is lost.

  --index-max-tries
  
     The number of times the indexer will attempt to index an item
     when a potentially recoverable error is encountered.

----
'''

from datetime import datetime, timedelta
import logging
import os
import urllib2
from optparse import make_option
import signal
from socket import error as socketerror
from stompest.simple import Stomp
from stompest.error import StompFrameError
from sunburnt import sunburnt, SolrError
from time import sleep
from urlparse import urlparse

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django import conf

from eulfedora.rdfns import model as modelns
from eulfedora.models import DigitalObject
from eulfedora.server import Repository

from django.utils import simplejson
from eulindexer.indexer.models import SiteIndex, IndexError, \
     init_configured_indexes, RecoverableIndexError

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    """Service that listens for Fedora STOMP updates and processes those objects
       against the configured site indexes."""
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
                    	 'is lost (default: %default; -1 for no maximum)'),
        make_option('--retry-reconnect-wait', type='int', dest='retry_reconnect_wait',
                    default=retry_reconnect_wait,
                    help='How many seconds to wait between reconnect attempts if the ' +
                    	 'connection to Fedora is lost (default: %default)'),
        make_option('--index-max-tries', type='int', dest='index_max_tries',
                    default=index_max_tries,
                    help='Number of times to attempt indexing an item when a potentially ' +
                    	 'recoverable error is encountered'),

    )

    # flag will be set to True when a SIGINT has been received
    interrupted = False
    
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

    def init_indexes(self):
        # initialize all indexes configured in django settings
        self.indexes, init_errors = init_configured_indexes()
        if init_errors:
            msg = 'Error loading index configuration for the following sites:\n'
            for site, err in init_errors.iteritems():
                msg += '\t%s:\t%s\n' % (site, err)
                self.stdout.write(msg + '\n')
                
        if self.verbosity > self.v_normal:
            self.stdout.write('Indexing the following sites:\n')
            for site, index in self.indexes.iteritems():
                self.stdout.write('\t%s\n%s\n' % (site, index.config_summary()))


    def handle(self, *args, **options):
        # bind a handler for interrupt signal
        signal.signal(signal.SIGINT, self.interrupt_handler)
        signal.signal(signal.SIGHUP, self.hangup_handler)
        
        # verbosity should be set by django BaseCommand standard options
        self.v_normal = 1	    # 1 = normal, 0 = minimal, 2 = all
        if 'verbosity' in options:
            self.verbosity = int(options['verbosity'])
        else:
            self.verbosity = self.v_normal

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

        # load site index configurations
        self.init_indexes()

        while (True):
            # if we've received an interrupt, don't check for new messages
            if self.interrupted:
                # if we're interrupted but still have items queued for update,
                # sleep instead of listening to the queue
                if self.to_index:
                    sleep(self.index_delay)

            # no interrupt - normal behavior
            # check if there is a new message, but timeout after 3 seconds so we can process
            # any recently updated objects
            else:
                # check if there is a new message, but timeout after 3 seconds so we can process
                # any recently updated objects
                try:
                    data_available = self.listener.canRead(timeout=self.index_delay)
                except Exception as err:
                    # signals like SIGINT/SIGHUP get propagated to the socket 
                    if self.interrupted:
                        pass
                    else:
                        logger.error('Error during Stomp listen: %s' % err)
                    data_available = False

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

            # if we've received an interrupt and there is nothing queued to index,
            # quit
            if self.interrupted and not self.to_index:
                return



    def reconnect_listener(self):
        '''Attempt to reconnect the listener, e.g. if Fedora is
        shutdown.  Waits the configured time between attemps to
        reconnect; will try to reconnect a configured number of times
        before giving up.'''
        
        # wait the configured time and try to re-establish the listener
        retry_count = 1
        while(retry_count <= self.max_reconnect_retries or self.max_reconnect_retries == -1):
            sleep(self.retry_reconnect_wait)
            try:
                self.listener = None
                self.init_listener()
                # if listener init succeeded, return for normal processing
                logger.error('Reconnect attempt %d succeeded' % retry_count)
                return
    
            # if fedora is still not available, attempting to
            # listen will generate a socket error
            except socketerror:
                try_detail = ''
                if self.max_reconnect_retries != -1:
                    try_detail = 'of %d ' % self.max_reconnect_retries
                logger.error('Reconnect attempt %d %sfailed; waiting %ds before trying again' % \
                             (retry_count, try_detail, self.retry_reconnect_wait))
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
            for site, index in self.indexes.iteritems():
                try:
                    index.delete_item(pid)
                except Exception as e:
                    logging.error("Failed to purge %s (%s): %s" % \
                                      (pid, site, e))

                    # Add a prefix to the detail error message if we
                    # can identify what type of error this is.
                    detail_type = ''
                    if isinstance(e, SolrError):
                        detail_type = 'Solr Error: '
                    action_str = 'Purge: '
                    msg = '%s%s%s' % (detail_type, action_str, e)
                    err = IndexError(object_id=pid, site=site, detail=msg)
                    err.save()
            logger.info('Deleting %s from all configured Solr indexes' % pid)
            # commit?
            
        # ingest, modify object or modify datastream
        else:
            # if the object isn't already in the queue to be indexed, check if it should be
            if pid not in self.to_index:
                # get content models from resource index
                obj_cmodels = list(self.repo.risearch.get_objects('info:fedora/%s' % pid,
                                                                  modelns.hasModel))
                # may include generic content models, but should not be a problem

                # find which configured site(s) index the item
                for site, index in self.indexes.iteritems():
                    if index.indexes_item(obj_cmodels):
                        if pid not in self.to_index:
                            # first site found - create a queue item and add to the list
                            self.to_index[pid] = QueueItem(site)
                        else:
                            # subsequent site - add the site to the existing queue item
                            self.to_index[pid].add_site(site)

    def process_queue(self):
        '''Loop through items that have been queued for indexing; if
        the configured delay time has passed, then attempt to index
        them, and log any indexing errors.'''
        #check if there are any items that should be indexed now
        if self.to_index:
            logger.debug('Objects queued to be indexed: %s' % ', '.join(self.to_index.keys()))

            queue_remove = []
            for pid in self.to_index.iterkeys():
                # if we've waited the configured delay time, attempt to index
                if datetime.now() - self.to_index[pid].time >= self.index_delta:
                    logger.debug('Triggering index for %s' % pid)

                    # a single object could be indexed by multiple sites; index all of them
                    for site in self.to_index[pid].sites_to_index:
                        self.index_item(pid, self.to_index[pid], site)
                    
                    if not self.to_index[pid].sites_to_index:
                        # if all configured sites indexed successfully
                        # or failed and should not be re-indexed,
                        # store pid to be removed from the queue
                        queue_remove.append(pid)


            # clear out any pids that were indexed successfully OR
            # errored from the list of objects still to be indexed
            for pid in queue_remove:
                del self.to_index[pid]

    def index_item(self, pid, queueitem, site):
        '''Index an item in a single configured site index and handle
        any errors, updating the queueitem retry count and marking
        sites as indexed according to success or any errors.

        :param pid: pid for the item to be indexed
        :param queueitem: :class:`QueueItem`
        :param site: name of the site index to use
        '''
        try:
            # tell the site index to index the item - returns True on success
            if self.indexes[site].index_item(pid):
                # mark the site index as complete on the queued item
                self.to_index[pid].site_complete(site)
                
        except RecoverableIndexError as rie:
            # If the index attempt resulted in error that we
            # can potentially recover from, keep the item in
            # the queue and attempt to index it again.
            
            # Increase the count of index attempts, so we know when to stop.
            self.to_index[pid].tries += 1
                    
            # quit when we reached the configured number of index attempts
            if self.to_index[pid].tries >= self.index_max_tries:
                logging.error("Failed to index %s (%s) after %d tries: %s" % \
                              (pid, site, self.to_index[pid].tries, rie))
                
                err = IndexError(object_id=pid, site=site,
                                 detail='Failed to index after %d attempts: %s' % \
                                 (self.to_index[pid].tries, rie))
                err.save()
                # we've hit the index retry limit, so set site as complete on the queue item
                self.to_index[pid].site_complete(site)
                
            else:
                logging.warn("Recoverable error attempting to index %s (%s), %d tries: %s" % \
                             (pid, site, self.to_index[pid].tries, rie))
                
                # update the index time - wait the configured index delay before
                # attempting to reindex again
                self.to_index[pid].time = datetime.now()
                
        except Exception as e:
            logging.error("Failed to index %s (%s): %s" % \
                          (pid, site, e))
            
            # Add a prefix to the detail error message if we
            # can identify what type of error this is.
            detail_type = ''
            if isinstance(e, SolrError):
                detail_type = 'Solr Error: '
            msg = '%s%s' % (detail_type, e)
            err = IndexError(object_id=pid, site=site,
                             detail=msg)
            err.save()
                
            # any exception not caught in the recoverable error block
            # should not be attempted again - set site as complete on queue item
            self.to_index[pid].site_complete(site)
                
            
                            

    def interrupt_handler(self, signum, frame):
        '''Gracefully handle a SIGINT, if possible.  Reports status if
        main loop is currently part-way through pages for a volume,
        sets a flag so main script loop can exit cleanly, and restores
        the default SIGINT behavior, so that a second interrupt will
        stop the script.
        '''
        if signum == signal.SIGINT:
            # restore default signal handler so a second SIGINT can be used to quit
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            # set interrupt flag so main loop knows to quit as soon as it can
            self.interrupted = True

            if self.verbosity >= self.v_normal:
                self.stdout.write('SIGINT received\n')

            # report if indexer currently has items queued for indexing
            if self.to_index:
                msg = '\n%d item(s) currently queued for indexing.\n' % len(self.to_index.keys())
                msg += 'Indexer will stop listening for updates and exit after currently queued items have been indexed.\n'
                msg += '(Ctrl-C / Interrupt again to quit immediately)\n'
                self.stdout.write(msg)
                
            self.stdout.flush()

    def hangup_handler(self, signum, frame):
        '''On SIGHUP, reload site index configurations and
        reinitialize connections to Solr.
        '''
        if signum == signal.SIGHUP:
            # it would be even better if we could reload django settings here, 
            # but I can't figure out a way to do that...
            
            if self.verbosity >= self.v_normal:
                self.stdout.write('SIGHUP received; reloading site index configurations.')
            # reload site indexes
            self.init_indexes()



class QueueItem(object):
    # simple object to track an item queued for indexing
    
    def __init__(self, *sites):
        # time queued for indexing
        self.time = datetime.now()
        # number of attemps to index this item
        self.tries = 0
        # name of the sites that the queued item should be indexed in
        self.sites = set(sites)
        # sites where indexing has been completed (either success or
        # failure that should not be retried)
        self.complete_sites = set()
        
    def add_site(self, site):
        # add a site to the set of sites this queued item should be indexed in
        self.sites.add(site)

    def site_complete(self, site):
        # mark a site as complete
        self.complete_sites.add(site)

    @property
    def sites_to_index(self):
        # sites still to be indexed - configured sites without complete sites
        return self.sites - self.complete_sites

    def __unicode__(self):
        return u'%s sites=%s (%d tries)' % \
               (self.time, ', '.join(self.sites), self.tries)
    
    def __repr__(self):
        return u'<QueueItem: %s >' % unicode(self)
