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
from optparse import make_option
from rdflib import URIRef
from urlparse import urlparse

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from eulfedora.rdfns import model as modelns
from eulfedora.server import Repository

from eulindexer.indexer.models import init_configured_indexes

class Command(BaseCommand):
    """Index Fedora objects, specified by pid, against the configured site indexes."""
    help = __doc__
    
    args = '<pid pid ...>'
    
    def handle(self, *pids, **options):
        # verbosity should be set by django BaseCommand standard options
        v_normal = 1	    # 1 = normal, 0 = minimal, 2 = all
        if 'verbosity' in options:
            verbosity = int(options['verbosity'])
        else:
            verbosity = v_normal

        # complain if no pids are specified?

        # load configured site indexes
        # so we can figure out which pids to index where
        self.indexes = init_configured_indexes()
        
        self.repo = Repository()
        self.objs = [self.repo.get_object(pid) for pid in pids]
        self.load_pid_cmodels()

        # loop through the objects and index them
        self.index_count = 0
        self.err_count = 0
        for o in self.objs:
            # query the local rdf graph of pids and cmodels to get a list for this object
            content_models = [str(cm) for cm in self.cmodels_graph.objects(subject=URIRef(o.uri),
                                                                    predicate=modelns.hasModel)]
            
            # if no content models are found, we can't do anything - report & skip to next item
            if not content_models:
                self.stdout.write('Error: no content models found for %s - cannot index\n' % o.pid)
                continue
                
            indexed = False
            # loop through the configured sites to see which (if any)
            # the current object should be indexed by
            for site, index in self.indexes.iteritems():
                if index.indexes_item(content_models):
                    try:
                        indexed = index.index_item(o.pid)
                        if verbosity > v_normal:
                            self.stdout.write('Indexed %s (site: %s)\n' % (o.pid, site))
                    except Exception as e:
                        # if an error occurs on a single item, report it but keep going
                        self.stdout.write('Error indexing %s in site %s: %s\n' % \
                                          (o.pid, site, e))
                        self.err_count += 1

            if indexed:
                self.index_count += 1
            else:
                self.stdout.write('Failed to index %s - none of the configured sites index this item\n' % o.pid)

        if verbosity >= v_normal:
            # report # of items indexed, even if it is zero
            self.stdout.write('Indexed %d item%s\n' % (self.index_count,
                                                       '' if self.index_count == 1 else 's'))
            # if err count is not zero, report it also
            if self.err_count:
                self.stdout.write('%d errors on attempts to index\n' % self.err_count)

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



        
