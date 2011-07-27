Readme
======

EULindexer is currently highly experimental code going through rapid development.
It is not recommended to use this code base until our internal testing on this
code has been completed and this message has been removed.

EULindexer is a module that takes a JSON response (documented below) and deposits the data
in that response in an index. For this initial implementation, `EULfedora <https://github.com/emory-libraries/eulfedora>`_
provides the webservice that will return the fedora object data it wants
indexed. Meanwhile, Solr is the index that will be used. Theoretically,
EULindexer can be used with other compatible services than just the above.


Running the Indexer
-------------------

To use the indexer, from the directory with manage.py, do:

  $ python manage.py indexer

Available options that can be specified are as follows: ::
  
  --max-reconnect-retries
      This is a numeric entry that specifies how many times to try to reconnect
      to Fedora if the connection is lost. The current default is: 5. ::

  --retry-reconnect-wait
      This is a numeric entry that specifies the wait time between Fedora connection
      retry attempts. The current default is: 5. ::

  --index-max-tries
      This is the maximum amount of times the indexer will attempt to reindex an item
      before giving up on it and logging an error. Retrying a failed object is useful
      when an application that handles that object's index is restarting. The current 
      default is: 3.


Reindex individual PIDs or an entire Site
-----------------------------------------

To reindex, the following command is made available:

  $ python manage.py reindex

At least one of the following two options is required: ::
  
  <pid pid ...>
      This is a list of pids to reindex. Only those pids specified will be reindexed. ::cd d

  -s (--site)
      This the name of a site currently configured in the localsettings.py. ALL objects
      from that site will be reindexed.


Expected JSON Responses
-----------------------

This application expects two distinct responses to -queries the indexer will make. This allows
an application that does not use eulfedora to simple code to this keyhole. Applications
that don't even support Python can be programmed to return these responses.

Configuration Response
^^^^^^^^^^^^^^^^^^^^^^

The first is querying a site's indexdata url with no arguments. An example might be:
http://localhost/myapp/indexdata/ . That URL will return a dictionary the consists of
SOLR_URL and CONTENT_MODELS. The SOLR_URL is just the absolute url to the SOLR instance
that the data should be placed into. The CONTENT_MODELS is a bit more complicated: it is 
a list of content model groups, or basically a list of a list. 

To be explain the CONTENT_MODELS, let's assume our repository handled two object types,
DOCUMENTS and VIDEOS. The DOCUMENTS object has a content model of "text" and the
VIDEOS object has content models "visual" and "audio". In that case, the following might
be returned: ::

  {
    "SOLR_URL": <url to solr, such as http://localhost/solr/app>,
    "CONTENT_MODELS": [
                         ["text"], 
                         ["visual", "audio"]
                      ]
  }

If we only had the DOCUMENTS object supported in our application and no VIDEOS, then
the JSON Response would be: ::

  {
    "SOLR_URL": <url to solr, such as http://localhost/solr/app>,
    "CONTENT_MODELS": [
                         ["text"]
                      ]
  }

If Documents suddenly started to have a "visual" content model in addition to its
"document" content model, then the JSON Response would be: ::

  {
    "SOLR_URL": <url to solr, such as http://localhost/solr/app>,
    "CONTENT_MODELS": [
                         ["text", "visual"], 
                         ["visual", "audio"]
                      ]
  }

For a completely generic example: ::

  {
    "SOLR_URL": <url to solr, such as http://localhost/solr/app>,
    "CONTENT_MODELS": [
                         ["Content Model #1", "Content Model #2"],
                         ["Content Model #3"], 
                         ["Content Model #4", "Content Model #1"]
                      ]
  }

It is worth noting that the order the content models are returned in do not
matter. They simply act as a "composite key" to identify an object from 
Fedora and require that object from fedora have at least those models
associated with it.

Index Response
^^^^^^^^^^^^^^

The second is querying a site's indexdata url with a <pid> at the end. An 
example might be: http://localhost/myapp/indexdata/<pid>, or using this
organization as an example with a fake pid of emory:1A1A2, 
http://localhost/myapp/indexdata/emory:1A1A2

This will return a JSON dictionary in the form of 
"solr_field_name":"value_to_put_in_field". For an example, we will assume 
our Solr uses the fields "PID", "Title", and "Description". Besides the
fake pid above of emory:1A1A2, our object has a title of "Emory University"
with a description of "A University located in the Southeast.": ::

  {
    "PID":"emory:1A1A2",
    "Title":"Emory University",
    "Description": "A University located in the Southeast."
  }  

For a completely generic version: ::

  {
    "PID":"<pid>",
    "Title":"<title>",
    "Description": "<description>"
  }

Additionally, please note that any valid JSON format for value
should work. For example, we could add a field "ContentModels"
with a list: ::

  {
    "PID":"<pid>",
    "Title":"<title>",
    "Description": "<description>",
    "ContentModels": ["Content Model #1", "Content Model #2"]
  }


Using with EULFedora
--------------------

`EULfedora <https://github.com/emory-libraries/eulfedora>`_ has support for the above two views already built into it.
The code for this functionality can be found under <eulfedora_base>/eulfedora/indexdata.
The documentation is located within the views.py file. Of note, besides following the url mapping
and adding the settings mentioned in those documents, your objects must extend
their own index_data methods. 


PDF Text Stripping Support
--------------------------

There is currently prototype support in EULIndexer for getting the text out
of PDFs. This can be useful to allow for searching on the content of
the PDF within a SOLR index. To do this, simply include the following
in a project that intends to return the content from a PDF:

from eulindexer.indexer.pdf import pdf_to_text

To use on a file, the syntax is:
  text = pdf_to_text(open(pdf_filepath, 'rb'))

To use on a datastream from EULFedora, the syntax is:
  pdfobj = repository.get_object(pid)
  text = pdf_to_text(pdfobj.pdf.content)


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
