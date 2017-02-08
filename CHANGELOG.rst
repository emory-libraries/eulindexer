.. _CHANGELOG:

Change Log
==========

Release 0.8
-----------

* Update indexer to work with celery
* Update indexer manage command to work with celery
* Update reindex manage command to  work with celery

Release 0.7
-----------

* Update Django to 1.8
* Update to require eulfedora 1.6 or greater for Fedora 3.8 support.
* Adding fab commands for test, build

Release 0.6
-----------

* New convenience script **clear_index*to clear the Solr index for a
  configured site.
* Update to require eulfedora 1.1 or greater for Fedora 3.8 support.
* Update to require a recent version of python-requests.

Release 0.5.1
-------------

* Fix Fedora connection error handling and reconnects.

Release 0.5.0
-------------

* Updated to Django 1.6.x
* Enhancements to the **reindex**  script:

  * ``-i index_url``: allow indexing site data into an alternate Solr instance.
  * ``-m YYYY-MM-DD`` : reindex objects modified in Fedora since the specified
    date
  * ``-c content-model`` option now supports objects with more content models
    than the one specified on the command-line
  * Script is now threaded; use the ``--concurrency`` option to specify the
    number of threads to be used when reindexing (current default is 4)

* Unit tests now use django-nose
* Logging has been overhauled to be more useful and filterable by level
* Now uses :mod:`requests` for HTTP requests to configured sites
* Now using a newer version of :mod:`sunburnt`; configured to use
  :mod:`requests` for HTTP connections to Solr

Release 0.4.0
-------------

* Added ``idle-reconnect` option to ``indexer`` script to optionally
  renew stomp listen connection after a specified time of no activity.
* Sample init.d script in ``scripts/eulindexer`` for use starting,
  stopping, reloading, and otherwise managing the ``indexer`` script
  like a system service.

Release 0.3.0
-------------

* Minor updates to ``reindex`` script: optional support for progress
  reporting with :mod:`progressbar`; report on the time reindexing
  took.
* New ``pip-install-opt.txt`` pip requirement file for modules that
  are not strictly required, but probably useful for a standard
  deploy; will be installed by a fab deploy.
* ``indexer`` and ``reindex`` will now pass any Fedora credentials
  configured in ``localsettings.py`` to sites that are running under
  SSL when making index data requests, in order to provide a method
  for centralizing fedora indexing permissions.


Release 0.2.1
-------------

* Handle generic :class:`Exception` in addition to
  :class:`~stompest.error.StompFrameError` when the Stomp listener
  :meth:`~stompest.simple.Stomp.canRead` generates an error (supports
  reconnect when attaching to a topic or a queue)

Release 0.2
-----------

* Better error handling when deleting an object from the Solr index
  (after a Fedora purgeObject).
* Use the Solr unique field (as configured in the Solr schema) for
  constructing the Solr delete request.
* Added an optional Django setting, **SOLR_CA_CERT_PATH** to allow
  configuring :mod:`httplib2` with a specific SSL Cert file in order
  to support connecting to SSL Solr instances with certificates that
  :mod:`httplib2` does not recognize.
* Signal handlers for SIGINT and SIGHUP in the ``indexer`` script:

  * on SIGINT, ``indexer`` will attempt to stop gracefully (index any
    currently items queued for indexing, but not listen for any new
    items).
  * on SIGHUP, ``indexer`` will reload the configured site index
    configurations and re-initialize Solr connections.

* Support indexing a single item by multiple sites.
* Improved sample apache configuration and fabric deploy file.


Release 0.1 - Initial Release
-----------------------------

This is the first release of eulindexer. It includes three components:
 * ``indexer`` manage.py command -- Listen for fedora object updates and
   use these to drive webapp requests for updated index data
 * ``reindex`` manage.py command -- Reindex specific items or all of the
   items associated with a particular webapp
 * simple ``indexer`` webapp for displaying index errors
