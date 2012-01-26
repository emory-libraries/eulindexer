Deploy Notes
============

Instructions for installation & upgrade notes.

Software Dependencies
---------------------

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

Install Python dependencies
^^^^^^^^^^^^^^^^^^^^^^^^^^^

EULIndexer depends on several python libraries. The installation is mostly
automated, and will print status messages as packages are installed. If there
are any errors, pip should announce them very loudly.

To install python dependencies, cd into the repository checkout and::

  $ pip install -r pip-install-req.txt

If you are a developer or are installing to a continuous ingration server
where you plan to run unit tests, code coverage reports, or build sphinx
documentation, you probably will also want to::

  $ pip install -r pip-dev-req.txt

After this step, your virtual environment should contain all of the
dependencies for EULIndexer.


Install/Configure System Dependencies
-------------------------------------

Configuring Fedora for indexing
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Currently, EULIndexer only supports Fedora "out of the box". Fedora is configured 
by default to send all data ingests, modifications, and deletions to a message 
queueing service. This enables indexers to listen on that service's queues for 
updates and respond to them in custom-defined ways. This section describes the 
Fedora configuration necessary for this indexer project to communicate with it.

Install Spring
""""""""""""""

For our Production installation, we have installed Spring as part of
enabling this service. We are using Spring Framework 3.1.0.M1 which
can be downloaded from: http://www.springsource.org/download

Once downloaded and extracted, run the following copy command: ::

  cp <extracted_directory>/spring-framework-3.1.0.M1/dist/org.springframework* <fedora_home>/tomcat/webapps/fedora/WEB-INF/lib/

Configure STOMP
"""""""""""""""

By default, Fedora is configured to notify applications about data ingests,
modifications, and deletions via the `JMS`_ protocol. It's also
easy to configure it to use the `STOMP`_ protocol.

.. _JMS: http://en.wikipedia.org/wiki/Java_Message_Service
.. _STOMP: http://stomp.codehaus.org/

In the ``fedora.fcfg`` file, find the section that begins with the following
tag::

   <module role="org.fcrepo.server.messaging.Messaging"
           class="org.fcrepo.server.messaging.MessagingModule">

Within that module configuration, find the following parameter::

   <param name="java.naming.provider.url" value="vm:(broker:(tcp://localhost:61616))"/>

Change that line to read::

   <param name="java.naming.provider.url" value="vm:(broker:(tcp://localhost:61616,stomp://localhost:61613))"/>

This tells Fedora to expose its update messages via STOMP in addition to
JMS. You can use another port besides 61613 if you prefer. Restart Fedora
when you're ready for this change to take effect.

Add a message queue
"""""""""""""""""""

JMS and STOMP have two ways of distributing messages: `topics` and `queues`.
By default, Fedora is configured to use a topic named ``fedora.apim.update``
for publishing update messages. When a message is published to a topic, all
external applications listening to that topic receive the update, but
there's no way of guaranteeing delivery to any particular application. This
is sufficient for testing the indexer, but we do not recommend it for
production use.

For production installations, we recommend sending update messages to a
queue. When a message is published to a topic, only one external application
receives it, but Fedora guarantees that it will be received. If no services
are listening to that queue when the message is published (for example, if
the indexer is temporarily down), Fedora will hold the message until it can
be delivered.

Fedora supports configuration of several message destinations. By default it
is configured with two: One that sends update messages to the
``fedora.apim.update`` topic, and one that sends access messages to the
``fedora.apim.access`` topic. These are configured as ``datastore``
parameters in the ``Messaging`` module and as separate ``<datastore>``
elements later in the ``fedora.fcfg``.

Configure Fedora to send update messages to a third message target. Inside
the same ``Messaging`` module as above, add the following parameter::

   <param name="datastore3" value="notifyIndexer">

Here we use the name ``notifyIndexer``. Any name is acceptable, so long as
the name here matches the one used below. We chose this name to represent
the purpose of this message target. Find the following element near the end
of the file::

   <datastore id="apimUpdateMessages">
     <param name="messageTypes" value="apimUpdate"/>
     <param name="name" value="fedora.apim.update"/>
     <param name="type" value="topic"/>
   </datastore>

Add a new element near this one for our newly-added parameter::

   <datastore id="notifyIndexer">
     <param name="messageTypes" value="apimUpdate"/>
     <param name="name" value="fedora.indexer.updates"/>
     <param name="type" value="queue"/>
   </datastore>

Note that the ``id`` matches the ``value`` set in the param above. The
``name`` parameter refers to the message target name. We use
``fedora.indexer.updates``, but other names are acceptable. We configured
this target as a ``queue`` to guarantee delivery to a single indexer
application.

Restart Fedora when you're ready for this change to take effect.


SOLR
^^^^

:mod:`eulindexer` currently only supports `Solr`_ indexing.  To learn
more about SOLR, please visit:  . Sample
documentation of our infrastructure install with Fedora can be found
at: `Emory Libraries TechKnowHow
<https://techknowhow.library.emory.edu/fedora-commons/fedora-install-notes>`_

.. _Solr: http://lucene.apache.org/solr/

:mod:`eulindexer` uses :mod:`sunburnt` to access Solr, and will
autoload Solr schemas from the Solr instances referenced by the
configured sites.

Install the Application
-----------------------

Apache
^^^^^^
After installing dependencies, copy and edit the wsgi and apache
configuration files in ``apache`` inside the source code checkout. Both will
probably require some tweaking for paths and such. Currently, this part of
the setup is just used to access the minimal admin of eulindexer.

Configuration
^^^^^^^^^^^^^
Configure application settings by copying localsettings.py.sample to
localsettings.py and editing for local database, applications to index,
and the indexer STOMP connection settings. Additionally, Fedora settings
need to be specified for some unit tests to currently work.

The indexer's ``localsettings.py`` contains configuration values for the
STOMP message target. The settings in ``localsettings.py.dist`` assume the
configuration described above, with the indexer running on the same server
as fedora. If you configured everything as described above, you can use
those settings directly.

If fedora is on a different server, set ``INDEXER_STOMP_SERVER`` to its host
name. If you configured STOMP to listen on a different port above, set that
in ``INDEXER_STOMP_PORT``. If you want the indexer to listen to a topic,
change the ``queue`` in ``INDEXER_STOMP_CHANNEL`` to ``topic``. If you chose
a different message target name above, replace the name in
``INDEXER_STOMP_CHANNEL``.

If any changes to settings are made to a running indexer, then the indexer
must be restarted for those changes to take effect.

Running the indexer
^^^^^^^^^^^^^^^^^^^

For command line options and features, see the documentation on the
:mod:`~eulindexer.indexer.management.commands.indexer` script.

To manage the ``indexer`` script as a system service, you can use the
shell script included with the source code (``scripts/eulindexer``) as
an init.d script.  To do that, simply copy the script to the
appropiate location, e.g.::

  $ cp scripts/eulindexer /etc/init.d/

And edit all the configuration variables and paths at the top of the
script to match your environment.  This init script supports running
:mod:`eulindexer` in a Python virtualenv.  Logging for the indexer is
expected to be configured in the :mod:`eulindexer` application and is
not handled directly by the init script.

.. Warning::

  Because this init script uses ``start-stop-daemon`` to start
  ``indexer`` in background mode, if there are any errors running the
  script, it will fail silently.  It is recommended to check that
  everything is configured properly in your site and that all
  permissions are correct (including permission to write to the
  configured logfiles, etc) by starting the indexer script manually
  before attempting to start it via the init script.



