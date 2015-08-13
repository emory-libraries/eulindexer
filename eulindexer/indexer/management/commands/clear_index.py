from optparse import make_option
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from sunburnt import sunburnt

from eulindexer.indexer.models import init_configured_indexes, \
     SiteIndex, SiteUnavailable

class Command(BaseCommand):
    'Remove all content from a solr index'
    help = __doc__

    option_list = BaseCommand.option_list + (
        make_option('-s', '--site', type='choice', dest='site',
                    choices=settings.INDEXER_SITE_URLS.keys(),
                    help='Index all objects that belong to a configured site [choices: ' +
                         ','.join(settings.INDEXER_SITE_URLS.keys()) + ']'),
    )

    def handle(self, *args, **options):
        # verbosity should be set by django BaseCommand standard options

        # check if site is set in options - indexing all objects for a single site
        if 'site' in options and options['site']:
            site_name = options['site']

            # only load the configuration for the one site we are interested in
            self.stdout.write('Loading index configuration for %s' % site_name)
            try:
                site = SiteIndex(settings.INDEXER_SITE_URLS[site_name], name=site_name)
            except SiteUnavailable as err:
                raise CommandError("Site '%s' is not available - %s" %
                                   (site, err))

            print 'Clearing %d records' % site.solr_interface.query('*').count()

            site.solr_interface.delete_all()

