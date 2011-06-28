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
from socket import error as socket_error
from stompest.simple import Stomp
from stompest.error import StompFrameError
from os import path

from django.conf import settings
from django.core.management.base import CommandError
from django.test import Client, TestCase

from eulfedora.models import DigitalObject, FileDatastream
from eulfedora.server import Repository

from eulindexer.indexer.management.commands import indexer
from eulindexer.indexer.pdf import pdf_to_text

import urllib2

class IndexerTest(TestCase):
    def setUp(self):
        self.command = indexer.Command()
        # settings? options? 
        
    def tearDown(self):
        pass

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

class test_indexer_settings(TestCase):
    def setUp(self):
        self.command = indexer.Command()
        self.old_settings_APPLICATION_URLS = settings.APPLICATION_URLS

    def tearDown(self):
        settings.APPLICATION_URLS = self.old_settings_APPLICATION_URLS

    def test_init_cmodel_settings(self):
        #Setup some known settings values
        settings.APPLICATION_URLS = ['http://localhost:0001', 'http://localhost:0002', 'http://localhost:0003']

        #Try to connect to an unavailable server. Currently still trying to get this to catch the error.
        #self.assertRaises(urllib2.HTTPError, self.command.init_cmodel_settings())


        #Mock out the calls for data from the application.
        application_returned_values = []
        application_returned_values.append('{"SOLR_URL": "", "CONTENT_MODELS": []}')
        application_returned_values.append('{"SOLR_URL": "http://localhost:9999/somevalue/", "CONTENT_MODELS": [["info:fedora/DOESNOTEXIST:Collection-1.1"]]}')
        application_returned_values.append('{"SOLR_URL": "http://localhost:8983/", "CONTENT_MODELS": [["info:fedora/emory-control:Collection-1.1"], ["info:fedora/emory-control:EuterpeAudio-1.0"]]}')


        def mock_side_effect():
            return application_returned_values.pop()

        mockreader = Mock()
        mockreader.read.side_effect = mock_side_effect
        mockurllib = Mock(urllib2)
        mockurllib.urlopen.return_value = mockreader

        #Verify settings are set correctly.
        with patch('eulindexer.indexer.management.commands.indexer.urllib2',
                   new=mockurllib):
            self.command.init_cmodel_settings()
            #Check the first responses settings
            self.assertEqual(self.command.index_settings[0].solr_url, 'http://localhost:8983/')
            self.assertEqual(str(self.command.index_settings[0].CMODEL_list), "[['info:fedora/emory-control:Collection-1.1'], ['info:fedora/emory-control:EuterpeAudio-1.0']]")
            self.assertEqual(self.command.index_settings[0].app_url, settings.APPLICATION_URLS[0])

            #Check the second respose settings
            self.assertEqual(self.command.index_settings[1].solr_url, 'http://localhost:9999/somevalue/')
            self.assertEqual(str(self.command.index_settings[1].CMODEL_list), "[['info:fedora/DOESNOTEXIST:Collection-1.1']]")
            self.assertEqual(self.command.index_settings[1].app_url, settings.APPLICATION_URLS[1])

            #Check the third (empty) response settings
            self.assertEqual(self.command.index_settings[2].solr_url, '')
            self.assertEqual(str(self.command.index_settings[2].CMODEL_list), "[]")
            self.assertEqual(self.command.index_settings[2].app_url, settings.APPLICATION_URLS[2])


        def test_IndexerSettings(TestCase):

            #Setup some known settings values
            settings.APPLICATION_URLS = ['http://localhost:0001']

            #Test setting Application URL
            indexer_setting = IndexerSettings(settings.APPLICATION_URLS[0])
            self.assertEqual(indexer_setting.app_url, settings.APPLICATION_URLS[0])

            #Test setting some CMODELS
            indexer_setting.CMODEL_list = ["info:fedora/emory-control:Collection-1.1"]
            indexer_setting.CMODEL_list = ["info:fedora/emory-control:EuterpeAudio-1.0"]
            self.assertEqual(indexer_setting.CMODEL_list, "[['info:fedora/emory-control:Collection-1.1'], ['info:fedora/emory-control:EuterpeAudio-1.0']]")

            #Test setting Solr URL
            indexer_setting.solr_url = 'localhost'
            self.assertEqual(indexer_setting.solr_url, 'localhost')






        
