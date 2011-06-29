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


from mock import Mock, patch, DEFAULT
from os import path
from socket import error as socket_error
from stompest.simple import Stomp
from stompest.error import StompFrameError
import urllib2

from django.conf import settings
from django.core.management.base import CommandError
from django.test import Client, TestCase

from eulfedora.models import DigitalObject, FileDatastream
from eulfedora.server import Repository

from eulindexer.indexer.management.commands import indexer
from eulindexer.indexer.pdf import pdf_to_text
from eulindexer.indexer.models import IndexerSettings

from django.utils import simplejson
from datetime import datetime, timedelta
from sunburnt import sunburnt


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
        self.command.max_retries = 3
        self.command.retry_wait = 1
        
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
            self.assertEqual(self.command.max_retries, mocklistener.connect.call_count)


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

        # Verify index settings are loaded
        with patch('eulindexer.indexer.models.urllib2',
                   new=mockurllib):
            self.command.init_cmodel_settings()
            self.assertEqual(len(settings.INDEXER_SITE_URLS.keys()),
                             len(self.command.index_settings.keys()),
                             'indexer should initialize one index setting per configured indexer site')

            # check that site urls match - actual index configuration
            # loading is handled in index settings object
            self.assertEqual(self.command.index_settings['site1'].site_url, settings.INDEXER_SITE_URLS['site1'])
            self.assertEqual(self.command.index_settings['site2'].site_url, settings.INDEXER_SITE_URLS['site2'])
            self.assertEqual(self.command.index_settings['site3'].site_url, settings.INDEXER_SITE_URLS['site3'])

    def test_process_index_queue(self):
        pid1 = 'indexer-test:test1'
        pid2 = 'indexer-test:test2'
        self.command.to_index[pid1] = {'time': datetime.now(), 'site': 'site1'}
        self.command.to_index[pid2] = {'time': datetime.now(), 'site': 'site1'}

        #Mock out the process index item
        mock_process_index_item = Mock()
        self.command.process_index_item = mock_process_index_item

        #Test process with returned True value
        mock_process_index_item.return_value = True
        self.command.process_index_queue()
        self.assertFalse(self.command.to_index.has_key(pid1))
        self.assertFalse(self.command.to_index.has_key(pid2))

        #Test process with returned False values
        self.command.to_index[pid1] = {'time': datetime.now(), 'site': 'site1'}
        self.command.to_index[pid2] = {'time': datetime.now(), 'site': 'site1'}
        mock_process_index_item.return_value = False

        self.command.process_index_queue()
        self.assertTrue(self.command.to_index.has_key(pid1))
        self.assertTrue(self.command.to_index.has_key(pid2))

    def test_process_index_item(self):
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

        mockurllib = Mock(urllib2)
        mockurllib.urlopen.return_value.read.return_value = simplejson.dumps(webservice_data)
        with patch('eulindexer.indexer.models.urllib2', new=mockurllib):
            self.command.init_cmodel_settings()

        #Should be false as has not been adequate time.
        result = self.command.process_index_item(pid1)
        self.assertFalse(result)

        #Configure a response
        webservice_data = {}
        webservice_data['pid'] = pid2
        webservice_data['some_other_value'] = 'sample value'


        mockurllib.urlopen.return_value.read.return_value = simplejson.dumps(webservice_data)
        mockSolrInterface = Mock(sunburnt)

        with patch('eulindexer.indexer.management.commands.indexer.urllib2', new=mockurllib):
            with patch('eulindexer.indexer.management.commands.indexer.sunburnt', new=mockSolrInterface):
                result = self.command.process_index_item(pid2)
                self.assertTrue(result)


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

        # mock urrlib to return json index config data
        mockurllib = Mock(urllib2)
        # empty response
        mockurllib.urlopen.return_value.read.return_value = '{}'
        with patch('eulindexer.indexer.models.urllib2', new=mockurllib):
            indexer_setting = IndexerSettings(site_url)
            self.assertEqual(site_url, indexer_setting.site_url)
            self.assertEqual('', indexer_setting.solr_url)
            self.assertEqual([], indexer_setting.CMODEL_list)

        # fields but no values
        webservice_data = {}
        webservice_data['SOLR_URL'] = ""
        webservice_data['CONTENT_MODELS'] = ""

        mockurllib.urlopen.return_value.read.return_value = simplejson.dumps(webservice_data)
        with patch('eulindexer.indexer.models.urllib2', new=mockurllib):
            indexer_setting = IndexerSettings(site_url)
            self.assertEqual(site_url, indexer_setting.site_url)
            self.assertEqual('', indexer_setting.solr_url)
            self.assertEqual('', indexer_setting.CMODEL_list)

        # fields and values
        webservice_data['SOLR_URL'] = "http://localhost:8983/"
        content_models = []
        content_models.append(['info:fedora/emory-control:Collection-1.1'])
        content_models.append(['info:fedora/emory-control:EuterpeAudio-1.0'])
        webservice_data['CONTENT_MODELS'] = content_models

        mockurllib.urlopen.return_value.read.return_value = simplejson.dumps(webservice_data)
        with patch('eulindexer.indexer.models.urllib2', new=mockurllib):
            indexer_setting = IndexerSettings(site_url)
            self.assertEqual(site_url, indexer_setting.site_url)
            self.assertEqual('http://localhost:8983/', indexer_setting.solr_url)
            self.assertEqual([["info:fedora/emory-control:Collection-1.1"], ["info:fedora/emory-control:EuterpeAudio-1.0"]], indexer_setting.CMODEL_list)


    def test_cmodel_comparison(self):
        # Test init & load configuration
        site_url = 'http://localhost:0001'
        # Setup an indexer setting
        mockurllib = Mock(urllib2)

        
        # fields and values
        webservice_data = {}
        webservice_data['SOLR_URL'] = "http://localhost:8983/"
        content_models = []
        content_models.append(['info:fedora/emory-control:Collection-1.1'])
        content_models.append(['info:fedora/emory-control:EuterpeAudio-1.0'])
        content_models.append(['info:fedora/emory-control:SomeOtherValue-1.1'])
        webservice_data['CONTENT_MODELS'] = content_models

        mockurllib.urlopen.return_value.read.return_value = simplejson.dumps(webservice_data)
        with patch('eulindexer.indexer.models.urllib2', new=mockurllib):
            indexer_setting = IndexerSettings(site_url)

            #Check for only 1 matching
            self.assertFalse(indexer_setting.CMODEL_match_check(["info:fedora/emory-control:Collection-1.1"]))
            self.assertFalse(indexer_setting.CMODEL_match_check(["DOESNOTEXIST-1.1"]))
        
            #Check for only 2 matching
            #self.assertFalse(indexer_setting.CMODEL_match_check(["info:fedora/emory-control:Collection-1.1", "info:fedora/emory-control:SomeOtherValue-1.1"]))

            #Check for all 3 matching
            #self.assertTrue(indexer_setting.CMODEL_match_check(["info:fedora/emory-control:Collection-1.1", "info:fedora/emory-control:SomeOtherValue-1.1", "info:fedora/emory-control:EuterpeAudio-1.0"]))

            #Check for superset (3 matching of the 4)
            #self.assertTrue(indexer_setting.CMODEL_match_check(["DOESNOTEXIST", "info:fedora/emory-control:Collection-1.1", "info:fedora/emory-control:SomeOtherValue-1.1", "info:fedora/emory-control:EuterpeAudio-1.0"]))
