Readme
======

EULindexer is currently experimental code going through development
and preliminary production deployment.  It is not recommended to use
this code base until our internal testing on this code has been
completed and this message has been removed.

EULindexer manages and coordinates index updates content that is
indexed by multiple sites and in multiple Solr instances, normally
triggered by an object update; this is done by way of a very simple
JSON service (format documented below) for passing configuration and
indexing data. In the current implementation, `EULfedora
<https://github.com/emory-libraries/eulfedora>`_ provides a webservice
that can be used for indexing, and Solr is used for
indexing, but EULindexer can be used with any site that provides JSON
data in the required format.

Components
----------

:mod:`eulindexer` currently consists of one primary script,
:mod:`~eulindexer.indexer.management.commands.indexer`, a helper
script :mod:`~eulindexer.indexer.management.commands.reindex`, and a
minimal web application that exposes Django's
:mod:`django.contrib.admin` interface for reviewing errors logged in
the database by either of the indexing scripts.



Index data service format
-------------------------

Any site configured in **INDEXER_SITE_URLS** in ``localsettings.py``
will be expected to respond to two types of requests, as documented
below.

Index Configuration
^^^^^^^^^^^^^^^^^^^

When the :mod:`~eulindexer.indexer.management.commands.indexer` or
:mod:`~eulindexer.indexer.management.commands.reindex` scripts start
up, they will query the sites configured as **INDEXER_SITE_URLS** at
the exact url configured in ``localsettings.py``.  That url is
expected to respond with a JSON object that consists of the
**SOLR_URL** where this site wants content indexed and a list of
**CONTENT_MODELS** that will be used to identify the types of objects
this site indexes.  

The **CONTENT_MODELS** portion of the response should be a list of
lists, where each list is the combination of content models required
to identify an object that the site indexes.  For example, if a site
indexes text content and audio-visual content (but not audio-only or
visual-only), it might return something like this::

  {
    "SOLR_URL": "http://localhost:8983/solr/myapp",
    "CONTENT_MODELS": [
                         ["info:fedora/cmodel:text"],      
                         ["info:fedora/cmodel:visual", "info:fedora/cmodel:audio"]
                      ]  
  }

When :mod:`~eulindexer.indexer.management.commands.indexer` identifies
objects that have the text content model or *both* the visual and
audio content models (and possibly others), it will attempt to index
them in this site.  Note that the order of the content models is not
significant; they simply act as a composite key to identify an object
from Fedora.

Index data
^^^^^^^^^^

When either of the indexing scripts identify an object to be indexed
by a particular configured site, they will query the site for the data
that should be sent to the Solr index.  Based on the url set for a
particular site in **INDEXER_SITE_URLS**, the indexer will query for
``/pid/``; e.g., if the url configured in ``localsettings.py`` is::

    http://localhost/myapp/indexdata/ 

For an object with pid ``test:123``, the :mod:`eulindexer` will
request index data at::

    http://localhost/myapp/indexdata/test:123/

This url is expected to return a JSON object with index data as field:
value, e.g. ::

  {
    "pid":"test:123",
    "title":"Emory University",
    "description": "A University located in the Southeast."
  }  

Any JSON content in this format (including, e.g., lists for values)
can be used, as long as it matches the field names in the configured
Solr schema for this site.  The JSON content is converted to an
equivalent python object and passed to the :mod:`sunburnt`
:meth:`sunburnt.sunburnt.SolrInterface.add` method.

.. Note::

  :mod:`eulindexer` does not send Solr a ``commit`` message, as that
  can be handled much more efficiently and directly by Solr.  

If the indexer encounters an error on indexing an individual item,
either when requesting the index data or sending that data to Solr, it
will do as follows: if the error is potentially recoverable, it will
attempt to reindex it (using the configured retry); if retries fail,
or the error is not recoverable, it will remove the item from the
index queue and log an :class:`~eulindexer.indexer.models.IndexError`
in the database for review.


Using with EULFedora
--------------------

Current versions of `EULfedora
<https://github.com/emory-libraries/eulfedora>`_ have support for the
:mod:`eulindexer` index-data service, which can be enabled and
extended in any project using :mod:`eulfedora` with :mod:`django`.
The code and documentation for this functionality can be found in
:mod:`eulfedora.indexdata`.

Dependencies
------------

**EULindexer** currently depends on 
`django <http://pypi.python.org/pypi/Django/>`_,
`sunburnt <https://github.com/tow/sunburnt/>`_,
`httplib2 <http://code.google.com/p/httplib2/>`_,
`stompest <http://pypi.python.org/pypi/stompest/1.0.0>`_,
`pyPdf <http://pypi.python.org/pypi/pyPdf>`_

**EULindexer** could be used without 
`EULfedora <https://github.com/emory-libraries/eulfedora>`_, but a
compatible web interface would need to be built for any replacement.


Contact Information
-------------------

**eulindexer** was created by the Digital Programs and Systems Software
Team of `Emory University Libraries <http://web.library.emory.edu/>`_.

libsysdev-l@listserv.cc.emory.edu


License
-------
**eulindexer** is distributed under the Apache 2.0 License.
