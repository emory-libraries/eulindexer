.. _CHANGELOG:
Change Log
==========


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
