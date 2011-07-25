.. _CHANGELOG:

Release 0.1 - Initial Release
-----------------------------

This is the first release of eulindexer. It includes three components:
 * ``indexer`` manage.py command -- Listen for fedora object updates and
   use these to drive webapp requests for updated index data
 * ``reindex`` manage.py command -- Reindex specific items or all of the
   items associated with a particular webapp
 * simple ``indexer`` webapp for displaying index errors
