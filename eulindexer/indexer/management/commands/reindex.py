# file eulindexer/indexer/management/commands/reindex.py
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
from optparse import make_option
from rdflib import URIRef
from urlparse import urlparse

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from eulfedora.rdfns import model as modelns
from eulfedora.models import DigitalObject
from eulfedora.server import Repository

from django.utils import simplejson
from eulindexer.indexer.models import init_configured_indexes


logger = logging.getLogger(__name__)

class Command(BaseCommand):
    args = '<pid pid ...>'
    
    def handle(self, *pids, **options):
        # verbosity should be set by django BaseCommand standard options
        v_normal = 1	    # 1 = normal, 0 = minimal, 2 = all
        if 'verbosity' in options:
            verbosity = int(options['verbosity'])
        else:
            verbosity = v_normal

        # load configured site indexes
        # so we can figure out which pids to index where
        self.indexes = init_configured_indexes()
        
        self.repo = Repository()
        self.objs = [self.repo.get_object(pid) for pid in pids]
        self.load_pid_cmodels()

        for o in self.objs:
            # query the local rdf graph of pids and cmodels to get a list for this object
            cmodels = [str(cm) for cm in self.cmodels_graph.objects(subject=URIRef(o.uri),
                                                                    predicate=modelns.hasModel)]
            logger.debug("%s has content models: %s" % (o.pid, ', '.join(cmodels)))

            for site, index_setting in self.indexes.iteritems():
                if index_setting.CMODEL_match_check(cmodels):
                    pass
                # TODO: move indexer.index_item logic into SiteIndex class for re-use here



    def load_pid_cmodels(self):
        '''Query the Fedora RIsearch for the content models of all
        pids that are being reindexed.  Stores the result as an RDF
        graph so it can be queried by object.
        '''
        query = '''CONSTRUCT   { ?pid <%(has_model)s> ?cmodel }
        WHERE {
           ?pid <%(has_model)s> ?cmodel
           FILTER ( %(pidlist)s )
        }
        ''' % {
           'has_model': modelns.hasModel,
           'pidlist': ' || '.join('?pid = <%s>' % o.uri for o in self.objs)
        }
        self.cmodels_graph = self.repo.risearch.find_statements(query, language='sparql',
                                                         type='triples', flush=True)



        
