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

* A single configured site, but at an alternate index URL:

  $ python manage.py reindex -s sitename -i index_url

  All objects from the configured site will be indexed, with index data
  going into the specified index URL instead of the site-specified index.

* A single fedora content model::

  $ python manage.py reindex  -c/--content-model info:fedora/cmodel:My-Object

  All objects with the requested content model will be indexed in any
  of the configured sites that claim them.

Use ``python manage.py reindex -h`` for more details.

----
'''


import os, sys
from collections import defaultdict
from datetime import datetime
from optparse import make_option
from Queue import Queue, Empty as EmptyQueue
from rdflib import URIRef
import threading
from time import sleep

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

# progressbar for optional progress output
try:
    from progressbar import ProgressBar, Bar, Percentage, \
         ETA, Counter
except ImportError:
    ProgressBar = None


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
        make_option('-i', '--index-url',
                    help='Override the site default solr index URL. Requires -s.'),
        make_option('-c', '--content-model', dest='cmodel',
                    help='Index all objects with the specified content model'),
        make_option('-m', '--modified-since', dest='since',
                    help='Index all objects modified since the specified date in YYYY-MM-DD format'),
        make_option('--concurrency', type=int, metavar='N', default=1,
                    help='Number of concurrent validation/repair threads to run (default: %(default)d)')
    )

    # class variables defined in setup
    indexes = []
    repo = None
    content_models = []
    pids = []
    cmodels_graph = None

    stats = defaultdict(int)

    todo_queue = Queue()
    done_queue = Queue()

    v_normal = 1	    # 1 = normal, 0 = minimal, 2 = all

    def handle(self, *pids, **options):
        # verbosity should be set by django BaseCommand standard options

        if 'verbosity' in options:
            verbosity = int(options['verbosity'])
        else:
            verbosity = self.v_normal

        if options.get('index_url', None) and not options.get('site', None):
            raise CommandError('--index_url requires --site')

        modified_since = None
        if options.get('since', None):
            try:
                modified_since = datetime.strptime(options.get('since'), '%Y-%m-%d')
            except:
                raise CommandError('--modified-since %s could not be interpreted as YYYY-MM-DD date' \
                                   % options.get('since'))

        # initialize repository connection - used in either mode
        self.repo = Repository()
        # get a timestamp in order to report how long indexing took
        start_time = datetime.now()

        # check if site is set in options - indexing all objects for a single site
        if 'site' in options and options['site']:
            site = options['site']

            index_url = None
            if 'index_url' in options:
                index_url = options['index_url']

            # only load the configuration for the one site we are interested in
            if verbosity > self.v_normal:
                self.stdout.write('Loading index configuration for %s' % site)
            try:
                self.indexes = {
                    site: SiteIndex(settings.INDEXER_SITE_URLS[site], name=site,
                                    solr_url=index_url)
                }
            except SiteUnavailable as err:
                raise CommandError("Site '%s' is not available - %s" %
                                   (site, err))

            # Query fedora risearch for all objects with any of the
            # content models this site cares about.  If a site
            # requires a combination of content models, this may
            # return extra objects, but they will be ignored at index time.
            self.content_models = self.indexes[site].distinct_content_models()
            if verbosity >= self.v_normal:
                self.stdout.write('Querying Fedora for objects with content models:\n %s\n' % \
                                  ', '.join(self.content_models))
            self.load_pid_cmodels(content_models=self.content_models)
            # set pids to be indexed based on the risearch query result
            self.pids = self.pids_from_graph()

        elif 'cmodel' in options and options['cmodel']:
            cmodel_pid = options['cmodel']
            if verbosity > self.v_normal:
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

        # find and reindex pids modified since a specified date
        elif modified_since:

            # sparql query to find objects by modification date
            # - includes query for content models so cmodels_graph can
            # be populated at the same time
            find_modified = '''SELECT ?pid ?hasmodel ?cmodel
            WHERE {
               ?pid <fedora-model:hasModel> <info:fedora/fedora-system:FedoraObject-3.0> .
               ?pid <fedora-model:hasModel> ?cmodel .
               ?pid ?hasmodel ?cmodel .
               ?pid <fedora-view:lastModifiedDate> ?modified .
               FILTER (?modified >= xsd:dateTime('%s'))
               }''' % modified_since.strftime('%Y-%m-%dT%H:%M:%S')
            graph = self.repo.risearch.find_statements(find_modified, language='sparql',
                type='triples')

            self.pids = set([str(p) for p in graph.subjects()])
            self.cmodels_graph = graph
            if verbosity >= self.v_normal:
                self.stdout.write('Found %d objects modified since %s' % \
                                  (len(self.pids), options.get('since')))

            # if there is anything to index, load configured site indexes
            if self.pids:
                self.load_indexes()

        # a list of pids to index, from an unknown site
        elif pids:
            # load configured site indexes so we can figure out which pids to index where
            self.load_indexes()
            self.pids = pids
            if verbosity >= self.v_normal:
                self.stdout.write('Querying Fedora for object content models\n')
            self.load_pid_cmodels(pids=pids)

        # no site, no pids - nothing to index
        else:
            raise CommandError('Neither site nor pids were specified.  Nothing to index.')


        # loop through the objects and index them
        pbar = None
        # check if progressbar is available and output is not redirected
        if ProgressBar and os.isatty(sys.stderr.fileno()):
            try:
                # get the length of pids is a list
                total = len(self.pids)
            except:
                # otherwise, pids is a generator - get the total from rdf graph
                total = self.total_from_graph()
            # init progress bar if we're indexing enough items to warrant it
            if total >= 5:
                pbar = ProgressBar(widgets=[Percentage(), ' (', Counter(), ')', Bar(),
                                            ETA()], maxval=total).start()

        self.stats['total'] = 0
        self.stats['indexed'] = 0
        self.stats['error'] = 0

        # start the requested number of worker threads
        # NOTE: might not want multiple threads for just a few pids...
        for i in range(options.get('concurrency', 1)):
            v = Indexer(self.todo_queue, self.done_queue, self.stats)
            v.start()

        # start a single reporter thread to pick up completed items
        vr = Reporter(self.done_queue, options, self.stats, pbar, self.stdout)
        vr.start()

        for pid in self.pids:
            obj = self.repo.get_object(pid)
            # query the local rdf graph of pids and cmodels to get a list for this object
            content_models = [str(cm) for cm in self.cmodels_graph.objects(subject=URIRef(obj.uri),
                                                                    predicate=modelns.hasModel)]

            # if no content models are found, we can't do anything - report & skip to next item
            if not content_models:
                self.stdout.write('Error: no content models found for %s - cannot index\n' % obj.pid)
                continue

            # loop through the configured sites to see which (if any)
            # the current object should be indexed by
            for site, index in self.indexes.iteritems():
                if index.indexes_item(content_models):
                    self.todo_queue.put((index, obj.pid))

            # if indexed:
            #     self.stats['indexed'] += 1
            # else:
            #     self.stdout.write('Failed to index %s - none the configured sites index this item\n'
            #                       % obj.pid)

        # queue.join blocks; check periodically if the need to check/sleep/interrupt
        while not self.todo_queue.empty():
            sleep(1)
        self.todo_queue.join()

        while not self.done_queue.empty():
            sleep(1)
        self.done_queue.join()

        end_time = datetime.now()
        if pbar:
            pbar.finish()

        if verbosity >= self.v_normal:
            # report # of items indexed, even if it is zero
            timediff = (end_time - start_time)

            self.stdout.write('Indexed %d item%s in %s\n' % \
                              (self.stats['total'], '' if self.stats['total'] == 1 else 's',
                               timediff))
            # if err count is not zero, report it also
            if self.stats['error']:
                self.stdout.write('%(error)d errors on attempts to index\n' % self.stats)

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
            # NOTE: need to filter on a different cmodel variable than the one
            # being returned because *all* cmodels are needed in order to
            # correctly identify which indexes support which objects
            query_filter =  ' || '.join('?cm1 = <%s>' % cm for cm in content_models)

        query = '''CONSTRUCT   { ?pid <%(has_model)s> ?cmodel }
        WHERE {
           ?pid <%(has_model)s> ?cmodel .
           ?pid <%(has_model)s> ?cm1
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


    def total_from_graph(self):
        '''Determine the total number of pids that will be indexed
        when indexing based on a RIsearch query (i.e., indexing by
        site or by content model).
        '''
        # FIXME: more efficient way to do this?
        return len(list(self.cmodels_graph.subjects(predicate=modelns.hasModel)))


class Indexer(threading.Thread):
    '''Thread class for indexing items in a queue.'''
    daemon = True

    def __init__(self, todo_queue, done_queue, stats):
        threading.Thread.__init__(self)
        self.todo = todo_queue
        self.done = done_queue
        self.stats = stats


    def run(self):
        while True:
            try:
                item = self.todo.get()
                # item should be a tuple of site index and pid
                site_index, pid = item
                try:
                    indexed = site_index.index_item(pid)
                    self.stats['indexed'] += 1
                    err = None
                except Exception as err:
                    indexed = False
                    self.stats['error'] += 1

                # stick in done queue a tuple of site index, pid,
                # index success or failure, and error if any
                self.done.put((site_index, pid, indexed, err))

                self.todo.task_done()
            except EmptyQueue:
                sleep(1)

class Reporter(threading.Thread):
    '''Thread class with common logic for handling items in the
    ``done`` queue and reporting where appropriate.'''

    daemon = True

    def __init__(self, done_queue, options, stats, pbar=None, stdout=None):
        threading.Thread.__init__(self)
        self.done = done_queue
        self.options = options
        self.pbar = pbar
        self.stats = stats
        self.stdout = stdout

        # keep track of total unique pids indexed (even if indexed in multiple sites)
        self.pids = set()

    def run(self):
        while True:
            try:
                site_index, pid, indexed, err = self.done.get()
                self.pids.add(pid)
                # successfully indexed
                if indexed:
                    self.stats['indexed'] += 1
                    if int(self.options.get('verbosity', Command.v_normal)) > Command.v_normal:
                        # if site was specified as an argument, don't report it for each item
                        if self.options['site']:
                            site_detail = ''
                        else:
                            site_detail = '(site: %s)' % site_index.name
                        self.stdout.write('Indexed %s %s\n' % (pid, site_detail))

                # error indexing
                else:
                    # NOTE: pid could be redundant, but better to include in case not
                    self.stdout.write('Index error in site %s for %s: %s\n' % \
                                      (site_index.name, pid, err))
                    self.stats['error'] += 1

                self.stats['total'] = len(self.pids)
                if self.pbar:
                    self.pbar.update(self.stats['total'])

                self.done.task_done()

            except EmptyQueue:
                sleep(1)
