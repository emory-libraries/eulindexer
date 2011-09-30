.. _CHANGELOG:


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
* Signal handlers for SIGINT and SIGHUP in the ``indexer`` script.
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
