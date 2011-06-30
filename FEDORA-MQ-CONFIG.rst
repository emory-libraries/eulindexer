Configuring Fedora for indexing
===============================

Fedora is configured by default to send all data ingests, modifications, and
deletions to a message queueing service. This enables indexers to listen on
that service's queues for updates and respond to them in custom-defined
ways. This document describes the Fedora configuration necessary for this
indexer project to communicate with it.

Configure STOMP
---------------

By default, Fedora is configured to notify applications about data ingests,
modifications, and deletions via the `JMS
<http://en.wikipedia.org/wiki/Java_Message_Service>`_ protocol. It's also
easy to configure it to use the `STOMP <http://stomp.codehaus.org/>`
protocol.

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
-------------------

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

Configure the indexer
---------------------

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

Restart the indexer when you're ready for this change to take effect.
