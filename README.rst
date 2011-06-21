EULindexer
==========

EULindexer is currently highly experimental code going through rapid development.
It is not recommended to use this code base until the first release branch is
created.

EULindexer is a module that takes a JSON response and deposits the data
in that response in an index. For this initial implementation, `EULfedora <https://github.com/emory-libraries/eulfedora>`_
provides the webservice that will return the fedora object data it wants
indexed. Meanwhile, Solr is the index that will be used. Theoretically,
EULindexer can be used with other compatible services than just the above.


Dependencies
------------

**EULindexer** currently depends on 
`sunburnt <https://github.com/tow/sunburnt/>`_,
`httplib2 <http://code.google.com/p/httplib2/>`_,
`stompest <http://pypi.python.org/pypi/stompest/1.0.0>`_,

**EULindexer** can be used without 
`EULfedora <https://github.com/emory-libraries/eulfedora>`_, but a
compatible web interface would need to be built for any replacement.


Contact Information
-------------------

**eulfedora** was created by the Digital Programs and Systems Software
Team of `Emory University Libraries <http://web.library.emory.edu/>`_.

libsysdev-l@listserv.cc.emory.edu


License
-------
**eulfedora** is distributed under the Apache 2.0 License.
