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

'''

To index or reindex a specific set of objects, use the **reindex**
command::

  $ python manage.py reindex  

The objects to be reindexed can be specified in one of the following ways:

* A list of specific pids to be indexed::

  $ python manage.py reindex  pid:1 pid:2 pid:3 ...

  Those objects (and only those) will be indexed in whichever of the
  configured sites index them.

* A single configured site::

  $ python manage.py reindex  -s/--site sitename

  All objects from the configured site (currently identified by
  finding objects with any of the content models that site indexes)
  will be indexed, in that site only.

* A single fedora content model::

  $ python manage.py reindex  -c/--content-model info:fedora/cmodel:My-Object

  All objects with the requested content model will be indexed in any
  of the configured sites that claim them.

Use ``python manage.py reindex -h`` for more details.

----
'''


from datetime import datetime, timedelta
from optparse import make_option
from rdflib import URIRef
from urlparse import urlparse

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from eulfedora.rdfns import model as modelns
from eulfedora.server import Repository

from eulindexer.indexer.models import init_configured_indexes, \
     SiteIndex, SiteUnavailable

class Command(BaseCommand):
    """Index Fedora objects, specified by pid, against the configured site indexes."""
    help = __doc__
    
    args = '<pid pid ...>'

    option_list = BaseCommand.option_list + (
        make_option('-s', '--site', type='choice', dest='site',
                    choices=settings.INDEXER_SITE_URLS.keys(),
                    help='Index all objects that belong to a configured site [choices: ' +
                         ','.join(settings.INDEXER_SITE_URLS.keys()) + ']'),
        make_option('-c', '--content-model', dest='cmodel',
                    help='Index all objects with the specified content model'),
    )

    def handle(self, *pids, **options):
        # verbosity should be set by django BaseCommand standard options
        v_normal = 1	    # 1 = normal, 0 = minimal, 2 = all
        if 'verbosity' in options:
            verbosity = int(options['verbosity'])
        else:
            verbosity = v_normal


        # initialize repository connection - used in either mode
        self.repo = Repository()

        # check if site is set in options - indexing all objects for a single site
        if 'site' in options and options['site']:
            site = options['site']
            # only load the configuration for the one site we are interested in
            if verbosity > v_normal:
                self.stdout.write('Loading index configuration for %s' % site)
            try:
                self.indexes = {
                    site: SiteIndex(settings.INDEXER_SITE_URLS[site])
                }
            except SiteUnavailable as err:
                raise CommandError("Site '%s' is not available - %s" %
                                   (site, err))
            
            # Query fedora risearch for all objects with any of the
            # content models this site cares about.  If a site
            # requires a combination of content models, this may
            # return extra objects, but they will be ignored at index time.
            self.content_models = self.indexes[site].distinct_content_models()
            self.stdout.write('Querying Fedora for objects with content models:\n %s\n' % \
                              ', '.join(self.content_models))
            self.load_pid_cmodels(content_models=self.content_models)
            # set pids to be indexed based on the risearch query result
            self.pids = self.pids_from_graph()

        elif 'cmodel' in options and options['cmodel']:
            cmodel_pid = options['cmodel']
            if verbosity > v_normal:
                self.stdout.write("Indexing objects with content model '%s'\n" % \
                                  cmodel_pid)
            # get the content model object from fedora in order to 
            # support both uri and pid notation
            cmodel = self.repo.get_object(cmodel_pid)
            # load pids for the specified cmodel
            self.load_pid_cmodels(content_models=[cmodel.uri])
            # set pids to be indexed based on the risearch query result
            self.pids = self.pids_from_graph()

            # load configured site indexes 
            self.load_indexes()

        # a list of pids to index, from an unknown site 
        elif pids:
            # load configured site indexes so we can figure out which pids to index where
            self.load_indexes()
            self.pids = pids
            self.load_pid_cmodels(pids=pids)

        # no site, no pids - nothing to index
        else:	
            raise CommandError('Neither site nor pids were specified.  Nothing to index.')


        # loop through the objects and index them
        self.index_count = 0
        self.err_count = 0
        for pid in self.pids:
            obj = self.repo.get_object(pid)
            # query the local rdf graph of pids and cmodels to get a list for this object
            content_models = [str(cm) for cm in self.cmodels_graph.objects(subject=URIRef(obj.uri),
                                                                    predicate=modelns.hasModel)]
            
            # if no content models are found, we can't do anything - report & skip to next item
            if not content_models:
                self.stdout.write('Error: no content models found for %s - cannot index\n' % obj.pid)
                continue
                
            indexed = False
            # loop through the configured sites to see which (if any)
            # the current object should be indexed by
            for site, index in self.indexes.iteritems():
                if index.indexes_item(content_models):
                    try:
                        indexed = index.index_item(obj.pid)
                        if verbosity > v_normal:
                            # if site was specified as an argument, don't report it for each item
                            if options['site']:
                                site_detail = ''
                            else:
                                site_detail = '(site: %s)' % site
                            self.stdout.write('Indexed %s %s\n' % (obj.pid, site_detail))
                    except Exception as e:
                        # if an error occurs on a single item, report it but keep going
                        self.stdout.write('Error indexing %s in site %s: %s\n' % \
                                          (obj.pid, site, e))
                        self.err_count += 1

            if indexed:
                self.index_count += 1
            else:
                self.stdout.write('Failed to index %s - none of the configured sites index this item\n'
                                  % obj.pid)

        if verbosity >= v_normal:
            # report # of items indexed, even if it is zero
            self.stdout.write('Indexed %d item%s\n' % (self.index_count,
                                                       '' if self.index_count == 1 else 's'))
            # if err count is not zero, report it also
            if self.err_count:
                self.stdout.write('%d errors on attempts to index\n' % self.err_count)

    def load_indexes(self):
        # load configured site indexes so we can figure out which pids to index where
        # report on any sites that failed to load
        self.indexes, init_errors = init_configured_indexes()
        if init_errors:
            msg = 'Error loading index configuration for the following site(s):\n'
            for site, err in init_errors.iteritems():
                msg += '\t%s:\t%s\n' % (site, err)
                self.stdout.write(msg + '\n')


    def load_pid_cmodels(self, pids=None, content_models=None):
        '''Query the Fedora RIsearch for the pids and content models
        to be indexed.  Stores the result as an RDF graph (instance of
        :class:`rdflib.graph.Graph`) so it can be queried by object.

        This method has two basic modes of operation: if a list of
        pids are specified, it queries the RIsearch for the content
        models for only the objects corresponding to those pids.  When
        given a list of content models, it will query for all objects
        with any of the content models.

        :param pids: list of pids - query will be filtered to include
            only the specified pids.
        :param content_models: list of content models - query will
            find all pids with any of the specified content models
        '''
        if pids is not None:
            objs = [self.repo.get_object(pid) for pid in pids]
            query_filter =  ' || '.join('?pid = <%s>' % o.uri for o in objs)
            
        elif content_models is not None:
            query_filter =  ' || '.join('?cmodel = <%s>' % cm for cm in content_models)
        
        query = '''CONSTRUCT   { ?pid <%(has_model)s> ?cmodel }
        WHERE {
           ?pid <%(has_model)s> ?cmodel
           FILTER ( %(filter)s )
        }
        ''' % {
           'has_model': modelns.hasModel,
     	   'filter': query_filter
        }
        self.cmodels_graph = self.repo.risearch.find_statements(query, language='sparql',
                                                         type='triples', flush=True)

    def pids_from_graph(self):
        '''Generator of pids based on the Content Model RDF graph
        (class:`rdflib.graph.Graph` instance).  Intended for use in
        Site indexing mode, and expects content model information to
        already be populated :meth:`load_pid_cmodels` with pid and
        content model information for objects with any of the content
        models that a particular site indexes.'''
        for subj in self.cmodels_graph.subjects(predicate=modelns.hasModel):
            # convert from URIRef to string 
            yield str(subj)



        
