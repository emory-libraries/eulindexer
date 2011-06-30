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


from datetime import timedelta
from mock import Mock, patch, DEFAULT
from os import path
from socket import error as socket_error
from stompest.simple import Stomp
from stompest.error import StompFrameError
from sunburnt import SolrError, sunburnt
import urllib2

from django.conf import settings
from django.core.management.base import CommandError
from django.test import Client, TestCase

from eulfedora.models import DigitalObject, FileDatastream
from eulfedora.server import Repository

from eulindexer.indexer.management.commands import indexer
from eulindexer.indexer.pdf import pdf_to_text
from eulindexer.indexer.models import IndexerSettings, IndexError

from django.utils import simplejson
from datetime import datetime, timedelta


class IndexerTest(TestCase):
    '''Unit tests for the indexer manage command.'''
    # test the indexer command and its methods here

    def setUp(self):
        self.command = indexer.Command()
        # store real configuration for sites to be indexed
        self._INDEXER_SITE_URLS = getattr(settings, 'INDEXER_SITE_URLS', None)

    def tearDown(self):
        # restore index site configuration
        if self._INDEXER_SITE_URLS is None:
            delattr(settings, 'INDEXER_SITE_URLS')
        else:
            settings.INDEXER_SITE_URLS = self._INDEXER_SITE_URLS

    def test_startup_error(self):
        # simulate a socket error (fedora not running/configured properly)
        # on first startup - should raise a command error
        mockstomp = Mock(Stomp)
        mockstomp.side_effect = socket_error
        with patch('eulindexer.indexer.management.commands.indexer.Stomp',
                   new=mockstomp):
            self.assertRaises(CommandError, self.command.handle, verbosity=0)

    def test_reconnect_listener(self):
        # configure fewer retries/wait period to make tests faster
        self.command.max_reconnect_retries = 3
        self.command.retry_reconnect_wait = 1
        
        mocklistener = Mock(Stomp)
        # raise an error every time - no reconnection
        mocklistener.connect.side_effect = socket_error
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
                raise socket_error
            else:
                return DEFAULT
        mocklistener.connect.side_effect = err_then_connect

        with patch('eulindexer.indexer.management.commands.indexer.Stomp',
                   new=Mock(return_value=mocklistener)):
            # should return without raising an exception
            self.command.reconnect_listener()
            # listener.connect should be called twice - failure, then success
            self.assertEqual(2, mocklistener.connect.call_count)

    def test_init_cmodel_settings(self):
        #Setup some known settings values
        settings.INDEXER_SITE_URLS = {
            'site1': 'http://localhost:0001', 
            'site2': 'http://localhost:0002', 
            'site3': 'http://localhost:0003'
        }

        # Try to connect to an unavailable server. Not ideal handling
        # currently. Just verifying app will throw an error and not
        # start until the unreachable host is up. Should likely be
        # handled some other way eventually.
        self.assertRaises(urllib2.HTTPError, self.command.init_cmodel_settings)

        # Mock urllib calls - no data for now
        mockurllib = Mock(urllib2)
        mockurllib.urlopen.return_value.read.return_value = '{}'

        # Mock sunburnt.
        mocksunburnt = Mock(sunburnt)

        # Verify index settings are loaded
        with patch('eulindexer.indexer.models.urllib2',
                   new=mockurllib):
            with patch('eulindexer.indexer.models.sunburnt',
                   new=mocksunburnt):
                self.command.init_cmodel_settings()
                self.assertEqual(len(settings.INDEXER_SITE_URLS.keys()),
                                 len(self.command.index_settings.keys()),
                                 'indexer should initialize one index setting per configured indexer site')

                # check that site urls match - actual index configuration
                # loading is handled in index settings object
                self.assertEqual(self.command.index_settings['site1'].site_url,
                                 settings.INDEXER_SITE_URLS['site1'])
                self.assertEqual(self.command.index_settings['site2'].site_url,
                                 settings.INDEXER_SITE_URLS['site2'])
                self.assertEqual(self.command.index_settings['site3'].site_url,
                             settings.INDEXER_SITE_URLS['site3'])

    #def test_process_message_purgeobject(self):
        # test processing a purge-object message

        # mockurllib = Mock(urllib2)
        # mockurllib.urlopen.return_value.read.return_value = simplejson.dumps({})
        # with patch('eulindexer.indexer.models.urllib2', new=mockurllib):

        '''indexconfig1 = Mock(IndexerSettings)
        indexconfig1.solr_url = "http://solr:port/core"
        indexconfig2 = Mock(IndexerSettings)
        indexconfig2.solr_url = "http://different.solr:port/core2"
        self.command.index_settings = {
            'site1': indexconfig1,
            'site2': indexconfig2,
            }

        mocksunburnt = Mock()
        testpid = 'testpid:1'
        with patch('eulindexer.indexer.management.commands.indexer.sunburnt', new=mocksunburnt):
            self.command.process_message(testpid, 'purgeObject')
            print mocksunburnt.SolrInterface.call_args_list
            index_count = len(self.command.index_settings)
            self.assertEqual(index_count, mocksunburnt.SolrInterface.call_count,
                             'one solr connection should be initialized for each connection')
            # check that both solr configurations were used
            # multiple calls- checking list of call args (tuple of args, kwargs - most recent call is first)
            self.assertEqual(((indexconfig1.solr_url,), {}), mocksunburnt.SolrInterface.call_args_list[1])
            self.assertEqual(((indexconfig2.solr_url,), {}), mocksunburnt.SolrInterface.call_args_list[0])
            self.assertEqual(index_count, mocksunburnt.SolrInterface.return_value.delete.call_count,
                             'solr delete should be called for each configured index')

            # mock's assert_called_with seems to have trouble comparing a dictionary arg
            args, kwargs = mocksunburnt.SolrInterface.return_value.delete.call_args
            self.assertEqual({'pid': testpid}, args[0],
                             'solr delete should be called with pid passed in for processing') '''


    def test_process_queue(self):
        # test basic index queue processing
        # mocking the index_item method to isolate just the process_queue logic
        pid1 = 'indexer-test:test1'
        pid2 = 'indexer-test:test2'
        index_queue = {        # sample test index queue
            pid1: {'time': datetime.now(), 'site': 'site1'},
            pid2: {'time': datetime.now(), 'site': 'site1'}
        }
        self.command.to_index = index_queue.copy()

        # no items indexed
        with patch.object(self.command, 'index_item', new=Mock(return_value=False)):
            self.command.process_queue()
            self.assertEqual(index_queue, self.command.to_index,
                             'to_index queue should remain unchanged when items are not indexed')

        # all items successfully indexed
        with patch.object(self.command, 'index_item', new=Mock(return_value=True)):
            self.command.process_queue()
            print self.command.to_index
            self.assertEqual({}, self.command.to_index,
                             'to_index queue should be empty when all items are indexed')

    def test_index_item(self):
        #Setup some objects
        pid1 = 'indexer-test:test1'
        pid2 = 'indexer-test:test2'
        self.command.to_index[pid1] = {'time': datetime.now(), 'site': self._INDEXER_SITE_URLS.iterkeys().next() }
        self.command.to_index[pid2] = {'time': datetime.now()-timedelta(seconds=self.command.index_delay), 'site': self._INDEXER_SITE_URLS.iterkeys().next()}

        #Configure settings
        webservice_data = {}
        webservice_data['SOLR_URL'] = "http://localhost:8983/"
        content_models = []
        content_models.append(['info:fedora/emory-control:Collection-1.1'])
        content_models.append(['info:fedora/emory-control:EuterpeAudio-1.0'])
        webservice_data['CONTENT_MODELS'] = content_models

        #Mock out urllib2
        mockurllib = Mock(urllib2)

        #mock out sunburnt
        mockSolrInterface = Mock(sunburnt)

        mockurllib.urlopen.return_value.read.return_value = simplejson.dumps(webservice_data)
        with patch('eulindexer.indexer.models.urllib2', new=mockurllib):
            with patch('eulindexer.indexer.models.sunburnt', new=mockSolrInterface):
                self.command.init_cmodel_settings()

        #Should be false as has not been adequate time.
        result = self.command.index_item(pid1)
        self.assertFalse(result)

        #Configure a response
        webservice_data = {}
        webservice_data['pid'] = pid2
        webservice_data['some_other_value'] = 'sample value'


        mockurllib.urlopen.return_value.read.return_value = simplejson.dumps(webservice_data)

        with patch('eulindexer.indexer.management.commands.indexer.urllib2', new=mockurllib):
            with patch('eulindexer.indexer.management.commands.indexer.sunburnt', new=mockSolrInterface):
                result = self.command.index_item(pid2)
                self.assertTrue(result)

    def test_process_queue_error(self):
        # test error logging - generic error (e.g., connection errror or JSON load failure)
        testpid = 'pid:1'
        testsite = 'testproj'
        err_msg = 'Failed to load index data'
        self.command.to_index = {testpid: {'site': testsite}}
        
        # simulate error on index attempt
        with patch.object(self.command, 'index_item', new=Mock(side_effect=Exception(err_msg))):
            self.command.process_queue()

        # an IndexError object should have been created for this pid
        indexerr = IndexError.objects.get(object_id=testpid)
        self.assertEqual(testsite, indexerr.site)
        self.assertEqual(err_msg, indexerr.detail,
                         'index error detail should include full exception message')

    def test_process_queue_solrerror(self):
        # test error logging - solr error when indexing is attempted
        testpid = 'pid:2'
        testsite = 'testproj2'
        err_msg = 'Required fields are unspecified: "id"'
        index_queue = {testpid: {'site': testsite}}
        self.command.to_index = index_queue.copy()
        
        # simulate Solr error on index attempt
        with patch.object(self.command, 'index_item', new=Mock(side_effect=SolrError(err_msg))):
            self.command.process_queue()

        # an IndexError object should have been created for this pid
        indexerr = IndexError.objects.get(object_id=testpid)
        self.assertEqual(testsite, indexerr.site)
        self.assert_(indexerr.detail.startswith('Solr Error:'),
                     'index error detail should be labeled as a solr error when SolrError is raised')
        self.assert_(indexerr.detail.endswith(err_msg),
                     'index error detail should include exception error message')

    def test_process_queue_recoverableerror(self):
        # test index retries & error logging for a potentially recoverable error
        testpid = 'pid:1'
        testsite = 'testproj'
        err_msg = 'Failed to load index data'
        self.command.to_index = {testpid: {'site': testsite, 'tries': 0}}
        # configure to only try twice
        self.command.index_max_tries = 2

        # simulate recoverable error 
        with patch.object(self.command, 'index_item',
                          new=Mock(side_effect=indexer.RecoverableIndexError(err_msg))):
            # first index attempt
            self.command.process_queue()
            self.assert_(testpid in self.command.to_index,
                         'on a recoverable error, pid should still be index queue')
            self.assertEqual(1, self.command.to_index[testpid]['tries'],
                             'index attempt count should be tracked in index queue')
            self.assertEqual(0, IndexError.objects.filter(object_id=testpid).count(),
                             'recoverable error should not be logged to db on first attempt')

            # second index attempt  (2 tries configured)
            self.command.process_queue()
            self.assert_(testpid not in self.command.to_index,
                         'on a recoverable error after max tries, pid should not be index queue')
            # when we hit the configured max number of attempts to index, error should be logged in db
            indexerr = IndexError.objects.get(object_id=testpid)
            self.assertEqual(testsite, indexerr.site)
            self.assert_('Failed to index' in indexerr.detail)
            self.assert_('2 attempts'  in indexerr.detail)


class TestPdfObject(DigitalObject):
    pdf = FileDatastream("PDF", "PDF document", defaults={
        	'versionable': False, 'mimetype': 'application/pdf'
        })


class PdfToTextTest(TestCase):
    fixture_dir = path.join(path.dirname(path.abspath(__file__)), 'fixtures')
    pdf_filepath = path.join(fixture_dir, 'test.pdf')
    pdf_text = 'This is a short PDF document to use for testing.'

    def setUp(self):
        self.repo = Repository(settings.FEDORA_TEST_ROOT, settings.FEDORA_TEST_USER,
                               settings.FEDORA_TEST_PASSWORD)
        with open(self.pdf_filepath) as pdf:
            self.pdfobj = self.repo.get_object(type=TestPdfObject)
            self.pdfobj.label = 'eulindexer test pdf object'
            self.pdfobj.pdf.content = pdf
            self.pdfobj.save()

    def tearDown(self):
        self.repo.purge_object(self.pdfobj.pid)
        
    def test_file(self):
        # extract text from a pdf from a file on the local filesystem
        text = pdf_to_text(open(self.pdf_filepath, 'rb'))
        self.assertEqual(self.pdf_text, text)

    def test_object_datastream(self):
        # extract text from a pdf datastream in fedora
        pdfobj = self.repo.get_object(self.pdfobj.pid, type=TestPdfObject)
        text = pdf_to_text(pdfobj.pdf.content)
        self.assertEqual(self.pdf_text, text)

class IndexerSettingsTest(TestCase):

    def test_init(self):
        # Test init & load configuration
        site_url = 'http://localhost:0001'

        #Create a mock sunburnt instance
        mockSunburntInterface = Mock(sunburnt)
        mockSunburntInterface.SolrInterface.return_value = 'sunburnt_set'

        # mock urrlib to return json index config data
        mockurllib = Mock(urllib2)
        # empty response
        mockurllib.urlopen.return_value.read.return_value = '{}'

        #This will fail as sunburnt won't be reachable.
        #with patch('eulindexer.indexer.models.urllib2', new=mockurllib):
            #indexer_setting = IndexerSettings(site_url)
            #self.assertRaises(RelativeURIError, indexer_setting.load_configuration)

        # fields but no values
        webservice_data = {}
        webservice_data['SOLR_URL'] = ""
        webservice_data['CONTENT_MODELS'] = ""

        #This will fail as sunburnt won't be reachable.
        #mockurllib.urlopen.return_value.read.return_value = simplejson.dumps(webservice_data)
        #with patch('eulindexer.indexer.models.urllib2', new=mockurllib):
            #indexer_setting = IndexerSettings(site_url)
            #self.assertRaises(RelativeURIError, indexer_setting.load_configuration)

        # fields and values
        webservice_data['SOLR_URL'] = "http://localhost:8983/"
        content_models = []
        content_models.append(['info:fedora/emory-control:Collection-1.1'])
        content_models.append(['info:fedora/emory-control:EuterpeAudio-1.0'])
        webservice_data['CONTENT_MODELS'] = content_models

        mockurllib.urlopen.return_value.read.return_value = simplejson.dumps(webservice_data)
        with patch('eulindexer.indexer.models.urllib2', new=mockurllib):
            with patch('eulindexer.indexer.models.sunburnt', new=mockSunburntInterface):
                indexer_setting = IndexerSettings(site_url)
                indexer_setting.load_configuration
                self.assertEqual(site_url, indexer_setting.site_url)
                self.assertEqual('http://localhost:8983/', indexer_setting.solr_url)
                self.assertEqual([["info:fedora/emory-control:Collection-1.1"], ["info:fedora/emory-control:EuterpeAudio-1.0"]], indexer_setting.CMODEL_list)
                self.assertEqual('sunburnt_set', indexer_setting.solr_interface)


    def test_cmodel_comparison(self):
        # Test init & load configuration
        site_url = 'http://localhost:0001'
        # Setup an indexer setting
        mockurllib = Mock(urllib2)

        #Create a mock sunburnt instance
        mockSunburntInterface = Mock(sunburnt)

        
        # fields and values
        webservice_data = {}
        webservice_data['SOLR_URL'] = "http://localhost:8983/"
        content_top_level = []

        #1st set of content models
        content_models = []
        content_models.append('info:fedora/emory-control:Collection-1.1')
        content_models.append('info:fedora/emory-control:EuterpeAudio-1.0')
        content_models.append('info:fedora/emory-control:SomeOtherValue-1.1')
        content_top_level.append(content_models)

        webservice_data['CONTENT_MODELS'] = content_top_level

        mockurllib.urlopen.return_value.read.return_value = simplejson.dumps(webservice_data)
        with patch('eulindexer.indexer.models.urllib2', new=mockurllib):
            with patch('eulindexer.indexer.models.sunburnt', new=mockSunburntInterface):
                indexer_setting = IndexerSettings(site_url)

                #Check for only 1 matching
                self.assertFalse(indexer_setting.CMODEL_match_check(["info:fedora/emory-control:Collection-1.1"]))
                self.assertFalse(indexer_setting.CMODEL_match_check(["DOESNOTEXIST-1.1"]))

                #Check for only 2 matching
                self.assertFalse(indexer_setting.CMODEL_match_check(["info:fedora/emory-control:Collection-1.1", "info:fedora/emory-control:SomeOtherValue-1.1"]))

                #Check for all 3 matching
                self.assertTrue(indexer_setting.CMODEL_match_check(["info:fedora/emory-control:Collection-1.1", "info:fedora/emory-control:SomeOtherValue-1.1", "info:fedora/emory-control:EuterpeAudio-1.0"]))

                #Check for superset (3 matching of the 4)
                self.assertTrue(indexer_setting.CMODEL_match_check(["DOESNOTEXIST", "info:fedora/emory-control:Collection-1.1", "info:fedora/emory-control:SomeOtherValue-1.1", "info:fedora/emory-control:EuterpeAudio-1.0"]))

        #Add a 2nd set of content models that shares one model
        content_models = []
        content_models.append('info:fedora/emory-control:Collection-1.1')
        content_models.append('info:fedora/emory-control:Rushdie-1.0')
        content_top_level.append(content_models)
        webservice_data['CONTENT_MODELS'] = content_top_level

        mockurllib.urlopen.return_value.read.return_value = simplejson.dumps(webservice_data)
        with patch('eulindexer.indexer.models.urllib2', new=mockurllib):
            with patch('eulindexer.indexer.models.sunburnt', new=mockSunburntInterface):
                indexer_setting = IndexerSettings(site_url)

                #Check for superset (3 matching of the 4) of the 1st set of content models
                self.assertTrue(indexer_setting.CMODEL_match_check(["DOESNOTEXIST", "info:fedora/emory-control:Collection-1.1", "info:fedora/emory-control:SomeOtherValue-1.1", "info:fedora/emory-control:EuterpeAudio-1.0"]))

                #Check that we have a match for the new set of content models using a superset
                self.assertTrue(indexer_setting.CMODEL_match_check(["info:fedora/emory-control:Rushdie-1.0", "DOESNOTEXIST", "info:fedora/emory-control:Collection-1.1"]))

                #Check for no match with a mixture that comes from both sets but doesn't match a single set
                self.assertFalse(indexer_setting.CMODEL_match_check(["info:fedora/emory-control:Rushdie-1.0", "info:fedora/emory-control:SomeOtherValue-1.1", "info:fedora/emory-control:EuterpeAudio-1.0"]))
