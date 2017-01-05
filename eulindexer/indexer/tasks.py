from __future__ import absolute_import

import logging
import os
import subprocess
import tempfile
import traceback
from datetime import datetime
from celery import shared_task
from sunburnt import SolrError

from django.conf import settings
from eulcommon.djangoextras.taskresult.models import TaskResult
from eulindexer.indexer.models import IndexError, \
     init_configured_indexes, RecoverableIndexError


logger = logging.getLogger(__name__)


@shared_task(bind=True)
def reindex_object(site, pid):
    indexes = load_indexes()
    site_index = indexes[site]
    try:
        indexed = site_index.index_item(pid)
        err = None
    except Exception as e:
        logging.error("Failed to index %s (%s): %s",
                      pid, site, e)

        # Add a prefix to the detail error message if we
        # can identify what type of error this is.
        detail_type = ''
        if isinstance(e, SolrError):
            detail_type = 'Solr Error: '
        msg = '%s%s' % (detail_type, e)
        err = IndexError(object_id=pid, site=site,
                         detail=msg)
        err.save()
    return 'Indexed pid %s' % pid

    


@shared_task(bind=True)
def index_object(pid, queueitem, site):
	# initialize all indexes configured in django settings
    indexes, init_errors = init_configured_indexes()
    index_max_tries = 3 

    try:
        # tell the site index to index the item - returns True on success
        if indexes[site].index_item(pid):
            # mark the site index as complete on the queued item
            queueitem.site_complete(site)

    except RecoverableIndexError as rie:
        # If the index attempt resulted in error that we
        # can potentially recover from, keep the item in
        # the queue and attempt to index it again.

        # Increase the count of index attempts, so we know when to stop.
        queueitem.tries += 1

        # quit when we reached the configured number of index attempts
        if queueitem.tries >= index_max_tries:
            logger.error("Failed to index %s (%s) after %d tries: %s",
                          pid, site, queueitem.tries, rie)

            err = IndexError(object_id=pid, site=site,
                             detail='Failed to index after %d attempts: %s' % \
                             (queueitem.tries, rie))
            err.save()
            # we've hit the index retry limit, so set site as complete on the queue item
            queueitem.site_complete(site)

        else:
            logging.warn("Recoverable error attempting to index %s (%s), %d tries: %s",
                         pid, site, queueitem.tries, rie)

            # update the index time - wait the configured index delay before
            # attempting to reindex again
            queueitem.time = datetime.now()

    except Exception as e:
        logging.error("Failed to index %s (%s): %s",
                      pid, site, e)

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
        queueitem.site_complete(site)

    return 'Indexed pid %s' % pid

def load_indexes(self):
        # load configured site indexes so we can figure out which pids to index where
        # report on any sites that failed to load
        indexes, init_errors = init_configured_indexes()
        if init_errors:
            msg = 'Error loading index configuration for the following site(s):\n'
            for site, err in init_errors.iteritems():
                msg += '\t%s:\t%s\n' % (site, err)
                self.stdout.write(msg + '\n')
        return indexes

