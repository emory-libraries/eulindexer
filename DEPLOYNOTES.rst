Deploy Notes
============

Instructions for installation & upgrade notes.

Installation
------------

Software Dependencies
~~~~~~~~~~~~~~~~~~~~~

We recommend the use of `pip <http://pip.openplans.org/>`_ and `virtualenv
<http://virtualenv.openplans.org/>`_ for environment and dependency
management in this and other Python projects. If you don't have them
installed we recommend ``sudo easy_install pip`` and then ``sudo pip install
virtualenv``.

Configure the environment
^^^^^^^^^^^^^^^^^^^^^^^^^

When first installing this project, you'll need to create a virtual environment
for it. The environment is just a directory. You can store it anywhere you like;
in this documentation it’ll live right next to the source. For instance, if the
source is in /home/eulindexer/, consider creating an environment in
/home/eulindexer/env. To create such an environment, su into apache's user
and::

  $ virtualenv --no-site-packages /home/eulindexer/env

This creates a new virtual environment in that directory. Source the activation
file to invoke the virtual environment (requires that you use the bash shell)::

  $ . /home/eulindexer/env/bin/activate

Once the environment has been activated inside a shell, Python programs
spawned from that shell will read their environment only from this
directory, not from the system-wide site packages. Installations will
correspondingly be installed into this environment.

.. Note::
  Installation instructions and upgrade notes below assume that
  you are already in an activated shell.

Install python dependencies
^^^^^^^^^^^^^^^^^^^^^^^^^^^

EULIndexer depends on several python libraries. The installation is mostly
automated, and will print status messages as packages are installed. If there
are any errors, pip should announce them very loudly.

To install python dependencies, cd into the repository checkout and::

  $ pip install -r pip-dependencies

If you are a developer or are installing to a continuous ingration server
where you plan to run unit tests, code coverage reports, or build sphinx
documentation, you probably will also want to::

  $ pip install -r build-dependencies

After this step, your virtual environment should contain all of the
dependencies for EULIndexer.


Install/Configure System Dependencies
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Fedora
""""""

Currently, EULIndexer only supports Fedora "out of the box". Fedora needs to be
configured as mentioned in the FEDORA-MQ-CONFIG.rst document that exists
in the same directory as this document. That document basically enables STOMP
messages that tells EULIndexer when a Fedora object has been added or updated.

SOLR
""""

EULIndexer also only supports SOLR for an index "out of the box" at this time. 
To learn more about SOLR, please visit: http://lucene.apache.org/solr/ . Sample
documentation of our infrastructure install with Fedora can be found at:
`Emory Libraries TechKnowHow <https://techknowhow.library.emory.edu/fedora-commons/fedora-install-notes>`_

Please note that a SOLR schema is required for data to be processed and EULIndexer 
assumes that schema is named "schema.xml" within the SOLR instance. A sample simple
SOLR Schema is planned to be added to this project in the future, but please
refer to the SOLR Documentation in the meantime on creating / modifying one.

Install the Application
~~~~~~~~~~~~~~~~~~~~~~~

Configuration
^^^^^^^^^^^^^
Configure application settings by copying localsettings.py.sample to
localsettings.py and editing for local database, applications to index,
and the indexer STOMP connection settings. Additionally, Fedora settings
need to be specified for some unit tests to currently work.

Running The Application
^^^^^^^^^^^^^^^^^^^^^^^

Please see the documentation under the README.rst.

Reindexing individual PIDs or an entire Site
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Please see the documentation under the README.rst.


Future Release Documentation
----------------------------

The following directions are things that are not ready to be done yet. As such,
the following section should be ignored for the time being.

Remove Old Rushdie Gsearch Configuration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

1. Under <fedora_home>/tomcat/webapps/fedoragsearch/WEB-INF/classes/config, edit fedoragsearch.properties
    a. Find the text: fedoragsearch.indexNames
    b. Remove the "RushdieSolr" entry.

2. Under <fedora_home>/tomcat/webapps/fedoragsearch/WEB-INF/classes/config/index
    a. Remove the RushdieSolr directory.

3. Shutdown fedora.

4. Shutdown Solr.

5. Under <fedora_home>/gsearch/solr/ssl-multicore/rushdie/
    a. Remove the data directory.

6. Restart Solr and Fedora.
