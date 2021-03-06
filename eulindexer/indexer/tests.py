# file eulindexer/indexer/tests.py
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

from cStringIO import StringIO
from datetime import datetime, timedelta
from mock import Mock, patch, DEFAULT
import os
import requests
from requests.auth import HTTPBasicAuth
from stompest.sync import Stomp
from stompest.error import StompFrameError, StompConnectTimeout
from sunburnt import SolrError

from django.conf import settings
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.test.utils import override_settings

from eulfedora.server import Repository
from celery import app
from eulindexer.indexer.management.commands import indexer, reindex
from eulindexer.indexer.management.commands.indexer import QueueItem
from eulindexer.indexer.models import SiteIndex, IndexError, \
    init_configured_indexes, IndexDataReadError, SiteUnavailable
from eulindexer.indexer.tasks import index_object


@override_settings(INDEXER_STOMP_SERVER='localhost',
    INDEXER_STOMP_PORT='61613',
    INDEXER_STOMP_CHANNEL='/topic/foo')
class IndexerTest(TestCase):
    '''Unit tests for the indexer manage command.'''
    # test the indexer command and its methods here

    def setUp(self):
        self.command = indexer.Command()

    def tearDown(self):
        IndexError.objects.all().delete()

    def test_startup_error(self):
        # simulate a socket error (fedora not running/configured properly)
        # on first startup - should raise a command error
        mockstomp = Mock(Stomp)
        mockstomp.side_effect = StompConnectTimeout
        with patch('eulindexer.indexer.management.commands.indexer.Stomp',
                   new=mockstomp):
            self.assertRaises(CommandError, self.command.handle, verbosity=0)

    def test_reconnect_listener(self):
        # configure fewer retries/wait period to make tests faster
        self.command.max_reconnect_retries = 3
        self.command.retry_reconnect_wait = 1

        mocklistener = Mock(Stomp)
        # raise an error every time - no reconnection
        mocklistener.connect.side_effect = StompConnectTimeout
        # simulate what happens when fedora becomes unavailable
        mocklistener.canRead.return_value = True
        mocklistener.receiveFrame.side_effect = StompFrameError

        with patch('eulindexer.indexer.management.commands.indexer.Stomp',
                   new=Mock(return_value=mocklistener)):
            self.assertRaises(CommandError, self.command.reconnect_listener)
            # listener.connect should be called the configured # of retries
            self.assertEqual(self.command.max_reconnect_retries, mocklistener.connect.call_count)

        mocklistener.reset_mock()	# reset method call count
        mocklistener.raised_error = False
        # error the first time but then connect, to simulate fedora recovery
        def err_then_connect(*args, **kwargs):
            if not mocklistener.raised_error:
                mocklistener.raised_error = True
                raise StompConnectTimeout
            else:
                return DEFAULT
        mocklistener.connect.side_effect = err_then_connect

        with patch('eulindexer.indexer.management.commands.indexer.Stomp',
                   new=Mock(return_value=mocklistener)):
            # should return without raising an exception
            self.command.reconnect_listener()
            # listener.connect should be called twice - failure, then success
            self.assertEqual(2, mocklistener.connect.call_count)

    def test_process_message_purgeobject(self):
        # test processing a purge-object message

        indexconfig1 = Mock()
        indexconfig2 = Mock()
        self.command.indexes = {
            'site1': indexconfig1,
            'site2': indexconfig2,
            }
        index_count = len(self.command.indexes)
        testpid = 'testpid:1'
        self.command.process_message(testpid, 'purgeObject')
        # delete should be called on every site index
        indexconfig1.delete_item.assert_called_with(testpid)
        indexconfig2.delete_item.assert_called_with(testpid)

    def test_process_queue(self):
        # test basic index queue processing
        # mocking the index_item method to isolate just the process_queue logic
        pid1 = 'indexer-test:test1'
        pid2 = 'indexer-test:test2'
        site = 'site1'
        index_queue = {        # sample test index queue
            pid1: QueueItem(site),
            pid2: QueueItem(site)
        }
        self.command.to_index = index_queue.copy()
        # mock the site index so we can control index success/failure
        self.command.indexes = {site: Mock(SiteIndex)}

        # configured delay not past - no items indexed
        self.command.index_delta = timedelta(days=3)
        self.command.process_queue()
        self.assertEqual(index_queue, self.command.to_index,
                         'to_index queue should remain unchanged when items are not indexed')

        # all items successfully indexed
        # configure delay so all items will be indexed
        self.command.index_delta = timedelta(days=0)
        self.command.indexes[site].index_item.return_value = True
        self.command.process_queue()
        self.assertEqual({}, self.command.to_index,
                         'to_index queue should be empty when all items are indexed')

    # @override_settings(CELERY_ALWAYS_EAGER=True)
    # def test_process_queue_multisite(self):
    #     # test support for indexing one item in multiple sites
    #     pid1 = 'indexer-test:test1'
    #     pid2 = 'indexer-test:test2'
    #     site = 'site1'
    #     site2 = 'site2'
    #     index_queue = {        # sample test index queue
    #         pid1: QueueItem(site, site2),
    #     }
    #     self.command.to_index = index_queue.copy()
    #     # mock the site indexes so we can control index success/failure
    #     self.command.indexes = {
    #         site: Mock(SiteIndex),
    #         site2: Mock(SiteIndex)
    #     }

    #     # site 1 will suceed on everything, site 2 will fail
    #     # configure delay so all items will be indexed
    #     self.command.index_delta = timedelta(days=0)
    #     self.command.indexes[site].index_item.return_value = True
    #     self.command.indexes[site2].index_item.return_value = False
    #     index_object.delay(pid1, site)
    #     index_object.delay(pid1, site2)

    #     # index_item should be called on both sites
    #     self.command.indexes[site].index_item.assert_called()
    #     self.command.indexes[site2].index_item.assert_called()

    #     # inspect updated queue item
    #     q_item = self.command.to_index[pid1]

    #     self.assert_(site in q_item.complete_sites)
    #     self.assert_(site2 not in q_item.complete_sites)
    #     self.assert_(pid1 in self.command.to_index,
    #         'item should still be queued for indexing when only one site succeeded')

    #     # reset mocks
    #     self.command.indexes[site].reset_mock()
    #     self.command.indexes[site2].reset_mock()
    #     # set *both* sites to succeed
    #     self.command.indexes[site].index_item.return_value = True
    #     self.command.indexes[site2].index_item.return_value = True
    #     # process the queue again
    #     index_object.delay(pid2, site)
    #     index_object.delay(pid2, site2)
    #     # index_item should be called on both sites
    #     self.command.indexes[site].index_item.assert_not_called()
    #     self.command.indexes[site2].index_item.assert_called()

    #     self.assertEqual({}, self.command.to_index,
    #                      'to_index queue should be empty when items are indexed in all sites')


    @override_settings(CELERY_ALWAYS_EAGER=True)
    def test_process_queue_error(self):
        # test error logging - generic error (e.g., connection errror or JSON load failure)
        
        testpid = 'pid:1'
        site = 'testproj'
        err_msg = 'Failed to index after'
        self.command.to_index = {testpid: QueueItem(site)}
        self.command.index_delta = timedelta(seconds=0)
        self.command.indexes = {site: Mock(SiteIndex)}

        # simulate error on index attempt
        self.command.indexes[site].index_item.side_effect = Exception(err_msg)
        # self.command.process_queue()
        index_object.delay(testpid, site)

        # an IndexError object should have been created for this pid
        indexerr = IndexError.objects.get(object_id=testpid)
        self.assertEqual(site, indexerr.site)
        self.assertTrue(indexerr)
                         
    @override_settings(CELERY_ALWAYS_EAGER=True)
    def test_process_queue_error_multisite(self):
        # error logging for an item indexed in multiple sites
        testpid = 'pid:1'
        site = 'testproj'
        site2 = 'generic-search'
        err_msg = 'Failed to index'
        self.command.to_index = {testpid: QueueItem(site, site2)}
        self.command.index_delta = timedelta(seconds=0)
        self.command.indexes = {
            site: Mock(SiteIndex),
            site2: Mock(SiteIndex),
        }

        # simulate error on index attempt
        self.command.indexes[site].index_item.side_effect = Exception(err_msg)
        self.command.indexes[site2].index_item.side_effect = Exception(err_msg)
        # self.command.process_queue()
        index_object.delay(testpid, site)
        index_object.delay(testpid, site2)

        # an IndexError object should have been created for this pid
        # for *each* site that errored
        indexerr = IndexError.objects.get(object_id=testpid, site=site)
        self.assertTrue(indexerr)
        # self.assertEqual()
        indexerr = IndexError.objects.get(object_id=testpid, site=site2)
        self.assertTrue(indexerr)

    @override_settings(CELERY_ALWAYS_EAGER=True, BROKER_BACKEND='memory',CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
    def test_process_queue_solrerror(self):
        # test error logging - solr error when indexing is attempted
        testpid = 'pid:2'
        site = 'testproj2'
        err_msg = 'Required fields are unspecified: "id"'
        index_queue = {testpid: QueueItem(site)}
        self.command.to_index = index_queue.copy()
        # configure time delay to 0 so indexer will attempt to index
        self.command.index_delta = timedelta(seconds=0)
        self.command.indexes = {site: Mock(SiteIndex)}

        # simulate Solr error on index attempt
        self.command.indexes[site].index_item.side_effect = SolrError(err_msg)
        index_object.delay(testpid, site)

        # an IndexError object should have been created for this pid
        indexerr = IndexError.objects.get(object_id=testpid)
        self.assertEqual(site, indexerr.site)
        self.assertTrue(indexerr)

    @override_settings(CELERY_ALWAYS_EAGER=True, BROKER_BACKEND='memory',CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
    def test_process_queue_recoverableerror(self):
        # test index retries & error logging for a potentially recoverable error
        testpid = 'pid:1'
        site = 'testproj'
        err_msg = 'Failed to load index data'
        self.command.to_index = {testpid: QueueItem(site)}
        # configure to only try twice
        self.command.index_max_tries = 2
        self.command.index_delta = timedelta(seconds=0)
        self.command.indexes = {site: Mock(SiteIndex)}

        # simulate recoverable error
        self.command.indexes[site].index_item.side_effect = indexer.RecoverableIndexError(err_msg)
        # first index attempt
        index_object.delay(testpid, site)
        # when we hit the configured max number of attempts to index, error should be logged in db
        indexerr = IndexError.objects.get(object_id=testpid)
        self.assertEqual(site, indexerr.site)
        self.assertTrue(indexerr)


    def test_idle_reconnect(self):
        mocklistener = Mock(Stomp)
        # simulate what happens when fedora becomes unavailable
        mocklistener.canRead.return_value = True
        mocklistener.receiveFrame.side_effect = StompFrameError

        with patch.object(self.command, 'reconnect_listener') as mockreconnect:
            with patch.object(self.command, 'init_listener') as mockinit:
                with patch.object(self.command, 'init_indexes'):
                    # mock init and set listener, last activity
                    self.command.listener = Mock()
                    self.command.last_activity = datetime.now() - timedelta(minutes=3)
                    self.command.interrupted = True   # stop after one loop

                    self.command.handle()
                    self.assertEqual(0, mockreconnect.call_count,
                         'reconnect should not be called if idle-reconnect is not set')
                    self.assertEqual(0, self.command.listener.disconnect.call_count,
                         'listener.disconnect should not be called if idle-reconnect is not set')

                    # with reconnect param
                    self.command.handle(idle_reconnect=1)
                    self.assertEqual(1, mockreconnect.call_count,
                         'reconnect should be called based on idle-reconnect & last activity')
                    self.assertEqual(1, self.command.listener.disconnect.call_count,
                         'listener.disconnect should be called based on idle-reconnect & last activity')


@override_settings(DEV_ENV=False, FEDORA_USER=None, FEDORA_PASSWORD=None)
class SiteIndexTest(TestCase):
    '''Tests for the SiteIndex object, which wraps the index
    configuration and indexing logic for a single site.'''

    @patch('eulindexer.indexer.models.requests')
    @patch('eulindexer.indexer.models.sunburnt')
    def test_init(self, mocksunburnt, mockrequests):
        # Test init & load configuration
        site_url = 'http://localhost:0001'
        mocksunburnt.SolrInterface.return_value = 'solr interface'

        # could also simulate urrlib and sunburnt connection errors
        # to test error handling

        # set sample fields and values to be returned from mock url call
        index_config = {
            'SOLR_URL': "http://localhost:8983/",
            'CONTENT_MODELS': [
                ['info:fedora/emory-control:Collection-1.1'],
                ['info:fedora/emory-control:EuterpeAudio-1.0']
            ]
        }
        mockrequests.codes.ok = 200
        mockrequests.Session.return_value.get.return_value.status_code = 200
        mockrequests.Session.return_value.get.return_value.json.return_value = index_config
        index = SiteIndex(site_url, 'test-site')
        self.assertEqual(site_url, index.site_url)
        # now initialized with
        mockrequests.Session.return_value.get.assert_called_with(site_url)
        self.assertEqual(index_config['SOLR_URL'], index.solr_url,
                         'SiteIndex solr url should be configured based on data returned from url call')
        for cmodel_group in index_config['CONTENT_MODELS']:
            self.assert_(set(cmodel_group) in index.content_models,
                         'each group of content models from indexdata should be present in SiteIndex content models')

        # solr connection now initialized with custom httplib2.Http instance
        # test args/kwargs discretely
        solr_args, solr_kwargs = mocksunburnt.SolrInterface.call_args
        self.assertEqual(index_config['SOLR_URL'], solr_args[0],
            'solr connection should be initialized via solr url from index configuration')
        print 'http conn = ', solr_kwargs['http_connection']
        self.assertEqual(solr_kwargs['http_connection'], mockrequests.Session.return_value)
        # self.assert_(isinstance(solr_kwargs['http_connection'], requests.Session))
        self.assertEqual('solr interface', index.solr_interface)

    @patch('eulindexer.indexer.models.requests')
    @patch('eulindexer.indexer.models.sunburnt')
    def test_request_headers(self, mocksunburnt, mockrequests):
        # non-ssl indexdata url
        mockrequests.codes.ok = 200
        mocksession = mockrequests.Session.return_value
        mocksession.get.return_value.status_code = 200
        mocksession.get.return_value.json.return_value = {}
        mocksession.headers = {}
        mocksession.auth = None
        index = SiteIndex('http://site.url', 'test-site')

        self.assert_('User-Agent' in mocksession.headers)
        self.assert_(mocksession.headers['User-Agent'].startswith('EULindexer/'))
        # auth should not be set in non-ssl
        self.assertEqual(None, mocksession.auth)

        # ssl with no credentials - no basic auth
        with patch.object(settings, 'FEDORA_USER', new=None):
            with patch.object(settings, 'FEDORA_PASSWORD', new=None):

                index = SiteIndex('https://site.url', 'test-site')
                self.assertEqual(None, mocksession.auth)

        # ssl with credentials - basic auth should be set
        with patch.object(settings, 'FEDORA_USER', new='user'):
            with patch.object(settings, 'FEDORA_PASSWORD', new='pass'):

                index = SiteIndex('https://site.url', 'test-site')
                self.assert_(isinstance(mocksession.auth, HTTPBasicAuth))

    @patch('eulindexer.indexer.models.requests')
    @patch('eulindexer.indexer.models.sunburnt')
    def test_indexes_item(self, mocksunburnt, mockrequests):
        mockrequests.codes.ok = 200
        mockrequests.Session.return_value.get.return_value.status_code = 200
        mockrequests.Session.return_value.get.return_value.json.return_value = {}
        index = SiteIndex('test-site-url', 'test-site')
        # define some content models and sets of cmodels for testing
        cmodels = {
            'item': 'info:fedora/test:item',
            'item-plus': 'info:fedora/test:item-plus',
            'group': 'info:fedora/test:group',
            'other': 'info:fedora/test:other',
        }
        index.content_models = [
            set([cmodels['item']]),
            set([cmodels['item'], cmodels['item-plus']]),
            set([cmodels['group']]),
        ]

        # single cmodel in a group
        self.assertTrue(index.indexes_item([cmodels['item']]))
        # single cmodel not included anywhere in our sets
        self.assertFalse(index.indexes_item([cmodels['other']]))
        # single cmodel - only included with another cmodel, not sufficient by itself
        self.assertFalse(index.indexes_item([cmodels['item-plus']]))

        # two cmodels matching
        self.assertTrue(index.indexes_item([cmodels['item'], cmodels['item-plus']]))
        # two cmodels - only one matches
        self.assertFalse(index.indexes_item([cmodels['item-plus'], cmodels['other']]))

        # superset - all required cmodels, plus others
        self.assertTrue(index.indexes_item([cmodels['item'], cmodels['item-plus'], cmodels['other']]))

    @patch('eulindexer.indexer.models.requests')
    @patch('eulindexer.indexer.models.sunburnt')
    def test_index_item(self, mocksunburnt, mockrequests):
        # return empty json data for index init/load config
        mockrequests.codes.ok = 200
        mocksession = mockrequests.Session.return_value
        mocksession.get.return_value.status_code = 200
        mocksession.get.return_value.json.return_value = {}
        index = SiteIndex('test-site-url', 'test-site')
        testpid = 'test:abc1'
        # replace solr interface with a mock we can inspect
        index.solr_interface = Mock()

        index_data = {'foo': 'bar', 'baz': 'qux'}
        mockresponse = mocksession.get.return_value
        mockresponse.json.return_value = index_data
        mockresponse.status_code = 200

        indexed = index.index_item(testpid)
        # solr 'add' should be called with data returned via index data webservice
        index.solr_interface.add.assert_called_with(index_data)
        self.assertTrue(indexed, 'index_item should return True on success')

        # solr error on attempt to add should be re-raised
        index.solr_interface.add.side_effect = SolrError
        self.assertRaises(SolrError, index.index_item, testpid)

        mocksession.get.side_effect = Exception
        # error on attempt to read index data should be raised as a recoverable error
        self.assertRaises(IndexDataReadError, index.index_item, testpid)

    @patch('eulindexer.indexer.models.requests')
    @patch('eulindexer.indexer.models.sunburnt')
    def test_delete_item(self, mocksunburnt, mockrequests):
        # return empty json data for index init/load config
        mocksession = mockrequests.Session.return_value
        mocksession.get.return_value.status_code = 200
        mockrequests.codes.ok = 200
        mocksession.get.return_value.json.return_value = {}
        index = SiteIndex('test-site-url', 'site name')
        index.solr_interface = Mock()
        keyfield = 'Pid'
        index.solr_interface.schema.unique_field.name = keyfield
        testpid = 'test:abc1'
        index.delete_item(testpid)
        index.solr_interface.delete.assert_called_with({keyfield: testpid})


    @patch('eulindexer.indexer.models.requests')
    @patch('eulindexer.indexer.models.sunburnt')
    def test_distinct_cmodels(self, mocksunburnt, mockrequests):
        # set empty response
        mockrequests.codes.ok = 200
        mocksession = mockrequests.Session.return_value
        mocksession.get.return_value.status_code = 200
        mocksession.get.return_value.json.return_value = {}

        index = SiteIndex('http://foo/index', 'foo')
        cmodels = {
            'coll': 'info:fedora/emory-control:Collection-1.1',
            'audio': 'info:fedora/emory-control:EuterpeAudio-1.0',
            'item': 'info:fedora/emory-control:Item-1.0',
        }
        # set some content model combinations for testing
        index.content_models =  [
            set([cmodels['coll']]),
            set([cmodels['audio']]),
            set([cmodels['coll'], cmodels['audio']]),
            set([cmodels['item']]),
            set([cmodels['audio'], cmodels['item']])
        ]
        distinct_cmodels = index.distinct_content_models()
        # each cmodel should be included once and only once
        self.assert_(cmodels['coll'] in distinct_cmodels)
        self.assert_(cmodels['audio'] in distinct_cmodels)
        self.assert_(cmodels['item'] in distinct_cmodels)
        self.assertEqual(len(cmodels.keys()), len(distinct_cmodels))

@override_settings(INDEXER_SITE_URLS={
    'site1': 'http://localhost:0001',
    'site2': 'http://localhost:0002',
    'site3': 'http://localhost:0003'})
class TestInitConfiguredIndexes(TestCase):

    _http_proxy = None

    def setUp(self):
        # proxy causes issues with connection error in some cases, so unset
        if 'HTTP_PROXY' in os.environ:
            self._http_proxy = os.environ.get('HTTP_PROXY')
            del os.environ['HTTP_PROXY']

    def tearDown(self):
        if self._http_proxy is not None:
            os.environ['HTTP_PROXY'] = self._http_proxy

    def test_connection_error(self):
        # Try to connect to an unavailable server. Not ideal handling
        # currently. Just verifying app will throw an error and not
        # start until the unreachable host is up. Should likely be
        # handled some other way eventually.
        indexes, errors = init_configured_indexes()
        self.assert_(isinstance(errors['site1'], SiteUnavailable))
        self.assert_(isinstance(errors['site2'], SiteUnavailable))
        self.assert_(isinstance(errors['site3'], SiteUnavailable))

    @patch('eulindexer.indexer.models.requests')
    @patch('eulindexer.indexer.models.sunburnt')
    def test_init(self, mocksunburnt, mockrequests):
        mockrequests.codes.ok = 200
        mockrequests.Session.return_value.get.return_value.status_code = 200
        mockrequests.Session.return_value.get.return_value.json.return_value = {}

       # Verify index settings are loaded
        indexes, errors = init_configured_indexes()
        self.assertEqual(len(settings.INDEXER_SITE_URLS.keys()),
                         len(indexes.keys()),
                         'init_configured_index should initialize one index per configured site')

        # check that site urls match - actual index configuration
        # loading is handled in index settings object
        self.assertEqual(indexes['site1'].site_url,
                         settings.INDEXER_SITE_URLS['site1'])
        self.assertEqual(indexes['site2'].site_url,
                         settings.INDEXER_SITE_URLS['site2'])
        self.assertEqual(indexes['site3'].site_url,
                         settings.INDEXER_SITE_URLS['site3'])

        # solr initialization, etc. is handled by SiteIndex class & tested there


@override_settings(INDEXER_SITE_URLS={'s1': 'http://ess.one', 's2': 'http://ess.two'})
class ReindexTest(TestCase):
    '''Unit tests for the reindex manage command.'''

    def setUp(self):
        self.command = reindex.Command()
        self.command.stdout = StringIO()

    def test_load_pid_cmodels(self):
        pids = ['pid:1', 'pid:2', 'pid:3']
        repo = Repository()
        # use a mock repo, but replace get_object with the real thing (for obj uris)
        self.command.repo = Mock()
        self.command.repo.get_object = repo.get_object
        self.command.repo.risearch.find_statements.return_value = 'pid-cmodel-graph'

        # load pid cmodels with a list of pids
        self.command.load_pid_cmodels(pids=pids)
        self.command.repo.risearch.find_statements.assert_called()
        # get the query arg to do a little inspection
        args, kwargs = self.command.repo.risearch.find_statements.call_args
        query = args[0]
        # sparql query should filter on all of the pids specified
        for pid in pids:
            self.assert_(pid in query,
                         'pid %s should be included in risearch cmodel query' % pid)
        self.assertEqual(self.command.repo.risearch.find_statements.return_value,
                         self.command.cmodels_graph,
                         'risearch find_statements result should be stored on manage command as cmodels_graph')

        # load pid cmodels with a list of cmodels
        content_models = ['foo:cm1', 'bar:cm2', 'baz:cm3']
        self.command.load_pid_cmodels(content_models=content_models)
        self.command.repo.risearch.find_statements.assert_called()
        # get the query arg to do a little inspection
        args, kwargs = self.command.repo.risearch.find_statements.call_args
        query = args[0]
        # sparql query should filter on all of the content models specified
        for cm in content_models:
            self.assert_(cm in query,
                         'content model %s should be included in risearch cmodel query' % cm)
        self.assertEqual(self.command.repo.risearch.find_statements.return_value,
                         self.command.cmodels_graph,
                         'risearch find_statements result should be stored on manage command as cmodels_graph')

    def test_index_noargs(self):
        # reindex script will error if nothing is specified for indexing (no pids or site)
        self.assertRaises(CommandError, self.command.handle)

    @patch('eulindexer.indexer.management.commands.reindex.Repository')
    def test_index_by_pid(self, mockrepo):

        pids = ['pid:a', 'pid:b', 'pid:c']
        # cmodel graph is initialized by load_pid_cmodels and needs to
        # return an iterable when queried
        def set_cmodel_graph(*args, **kwargs):
            self.command.cmodels_graph = Mock()
            # set to a non-empty list so items will be indexed
            self.command.cmodels_graph.objects.return_value = ['foo']
        self.command.load_pid_cmodels = Mock(side_effect=set_cmodel_graph)

        indexconfig1 = Mock()
        indexconfig2 = Mock()
        indexes = {
            's1': indexconfig1,
            's2': indexconfig2
        }

        # patch init_configured_indexes to return our mock site indexes
        with patch('eulindexer.indexer.management.commands.reindex.init_configured_indexes',
                   new=Mock(return_value=(indexes, {}))):
            # set mock indexes not to index any items
            indexes['s1'].indexes_item.return_value = False
            indexes['s2'].indexes_item.return_value = False
            self.command.handle(*pids)
            # nothing indexed, but no errors
            self.assertEqual(0, self.command.stats['indexed'])
            self.assertEqual(0, self.command.stats['error'])

            # set mock index to index all items successfully
            indexes['s1'].indexes_item.return_value = True
            indexes['s1'].index_item.return_value = True

            self.command.handle(*pids)
            # index count = all items, no errors
            self.assertEqual(len(pids), self.command.stats['indexed'])
            self.assertEqual(0, self.command.stats['error'])

            # index all items but fail
            indexes['s1'].index_item.return_value = False
            self.command.handle(*pids)
            # nothing indexed, no items
            self.assertEqual(0, self.command.stats['indexed'])
            self.assertEqual(len(pids), self.command.stats['error'])

            # error on attempt to index
            indexes['s1'].index_item.side_effect = Exception
            self.command.handle(*pids)
            # nothing indexed, all errored
            self.assertEqual(0, self.command.stats['indexed'])
            self.assertEqual(len(pids), self.command.stats['error'])

    @patch('eulindexer.indexer.management.commands.reindex.Repository')
    def test_index_by_site(self, mockrepo):
        # test the basic indexing logic of the script - index a configured site

        # cmodel graph is initialized by load_pid_cmodels and needs to
        # return an iterable when queried
        def set_cmodel_graph(*args, **kwargs):
            self.command.cmodels_graph = Mock()
            # set to a non-empty list so items will be indexed
            self.command.cmodels_graph.objects.return_value = ['foo']
        self.command.load_pid_cmodels = Mock(side_effect=set_cmodel_graph)
        self.command.total_from_graph = Mock(return_value=3)
        # set test pids to be indexed
        testpids = ['pid:1', 'pid:2', 'pid:3']
        self.command.pids_from_graph = Mock(return_value=testpids)

        # create a mock site index object
        mocksiteindex = Mock(SiteIndex)
        mocksiteindex.distinct_content_models.return_value = ['cmodel:1', 'cmodel:2']
        # indexes any item it is asked about
        mocksiteindex.indexes_item.return_value = True
        # indexes everything successfully
        mocksiteindex.index_item.return_value = True

        with patch('eulindexer.indexer.management.commands.reindex.SiteIndex',
                   Mock(return_value=mocksiteindex)):
            self.command.handle(site='s1')
            # all pids indexed, no errors
            self.assertEqual(len(testpids), self.command.stats['indexed'])
            self.assertEqual(0, self.command.stats['error'])
            self.assertEqual(1, len(self.command.indexes.keys()),
                             'only the required site configuration is loaded when indexing a single site')
            self.assert_('s1' in self.command.indexes)


    def test_index_by_cmodel(self):

        pids = ['pid:a', 'pid:b', 'pid:c']
        # cmodel graph is initialized by load_pid_cmodels and needs to
        # return an iterable when queried
        def set_cmodel_graph(*args, **kwargs):
            self.command.cmodels_graph = Mock()
            # set to a non-empty list so items will be indexed
            self.command.cmodels_graph.objects.return_value = ['foo']
        self.command.load_pid_cmodels = Mock(side_effect=set_cmodel_graph)
        self.command.pids_from_graph = Mock(return_value=pids)
        self.command.total_from_graph = Mock(return_value=1)
        indexconfig1 = Mock()
        indexconfig2 = Mock()
        indexes = {
            's1': indexconfig1,
            's2': indexconfig2
        }

        # patch init_configured_indexes to return our mock site indexes
        with patch('eulindexer.indexer.management.commands.reindex.init_configured_indexes',
                   new=Mock(return_value=(indexes, {}))):
            # set mock index to index all items successfully
            indexes['s1'].indexes_item.return_value = True
            indexes['s1'].index_item.return_value = True

            # specify cmodel as pid
            self.command.handle(cmodel='my:stuff-1.0')
            mock_load_pids = self.command.load_pid_cmodels
            mock_load_pids.assert_called_with(content_models=['info:fedora/my:stuff-1.0'])

            # specify cmodel as uri
            self.command.handle(cmodel='info:fedora/my:stuff-1.0')
            mock_load_pids = self.command.load_pid_cmodels
            mock_load_pids.assert_called_with(content_models=['info:fedora/my:stuff-1.0'])
