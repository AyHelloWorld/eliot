Using Eliot
===========

A Note On Naming
----------------

Eliot APIs provide both `PEP 8`_ style (e.g. ``write_traceback()``) and `Twisted`_ (e.g. ``writeTraceback()``) method and function names.
The only exceptions are pyunit-style assertions (e.g. ``assertContainsFields()``) and Twisted-specific APIs since both use camel-case by default.
Code examples below may use either style; both will work.

.. _PEP 8: http://legacy.python.org/dev/peps/pep-0008/
.. _Twisted: https://twistedmatrix.com/documents/current/core/development/policy/coding-standard.html



Actions and Tasks
-----------------

A higher-level construct than messages is the concept of an action.
An action can be started, and then finishes either successfully or with some sort of an exception.
Success in this case simply means no exception was thrown; the result of an action may be a successful response saying "this did not work".
Log messages are emitted for action start and finish.

Actions are also nested; one action can be the parent of another.
An action's parent is deduced from the Python call stack and context managers like ``Action.context()``.
Log messages will also note the action they are part of if they can deduce it from the call stack.
The result of all this is that you can trace the operation of your code as it logs various actions, and see a narrative of what happened and what caused it to happen.

A top-level action with no parent is called a task, the root cause of all its child actions.
E.g. a webserver receiving a new HTTP request would create a task for that new request.
Log messages emitted from Eliot are therefore logically structured as a forest: trees of actions with tasks at the root.

While the logical structure of log messages is a forest, the actual output is effectively a list of dictionaries (e.g. a series of JSON messages written to a file).
To bridge the gap between the two structures each output message contains enough information to recreate the logical relationship between it and other messages:

1. The task, identified using a UUID.
2. The specific action within that task's action tree.
3. A per-action counter that is incremented for each new output message directly within that action.

See the :doc:`Fields <fields>` documentation for details.

Here's a basic example of logging an action:

.. code-block:: python

     from eliot import start_action, Logger

     logger = Logger()

     with start_action(logger, u"yourapp:subsystem:frob"):
         x = _beep()
         frobinate(x)

This will log an action start message and if the block finishes successfully an action success message.
If an exception is thrown by the block then an action failure message will be logged along with the exception type and reason as additional fields.
Each action thus results in two messages being logged: at the start and finish of the action.
No traceback will be logged so if you want a traceback you will need to do so explicitly.
Notice that the action has a name, with a subsystem prefix.
Again, this should be a logical name.

Note that all code called within this block is within the context of this action.
While running the block of code within the ``with`` statement new actions created with ``start_action`` will get the top-level ``start_action`` as their parent.
If there is no parent the action will be considered a task.
If you want to ignore the context and create a top-level task you can use the ``eliot.start_task`` API.


Non-Finishing Contexts
^^^^^^^^^^^^^^^^^^^^^^

Sometimes you want to have the action be the context for other messages but not finish automatically when the block finishes.
You can do so with ``Action.context()``.
You can explicitly finish an action by calling ``eliot.Action.finish``.
If called with an exception it indicates the action finished unsuccessfully.
If called with no arguments that the action finished successfully.
Keep in mind that code within the context block that is run after the action is finished will still be in that action's context.

.. code-block:: python

     from eliot import start_action, Logger

     logger = Logger()

     action = start_action(logger, u"yourapp:subsystem:frob"):
     try:
         with action.context():
             x = _beep()
         with action.context():
             frobinate(x)
         # Action still isn't finished, need to so explicitly.
     except FrobError as e:
         action.finish(e)
     else:
         action.finish()

You can also explicitly run a function within the action context:

.. code-block:: python

     from eliot import start_action, Logger

     logger = Logger()

     action = start_action(logger, u"yourapp:subsystem:frob")
     # Call do_something(x=1) in context of action, return its result:
     result = action.run(do_something, x=1)


Action Fields
^^^^^^^^^^^^^

You can add fields to both the start message and the success message of an action.

.. code-block:: python

     from eliot import start_action, Logger

     logger = Logger()

     with start_action(logger, u"yourapp:subsystem:frob",
                      # Fields added to start message only:
                      key=123, foo=u"bar") as action:
         x = _beep(123)
         result = frobinate(x)
         # Fields added to success message only:
         action.add_success_fields(result=result)

If you want to include some extra information in case of failures beyond the exception you can always log a regular message with that information.
Since the message will be recorded inside the context of the action its information will be clearly tied to the result of the action by the person (or code!) reading the logs later on.


Twisted Support
^^^^^^^^^^^^^^^

If you are using the Twisted networking framework an additional set of APIs is available.
To understand why, consider the following example:

.. code-block:: python

     from eliot import startAction, Logger

     logger = Logger()


     def go():
         action = startAction(logger, u"yourapp:subsystem:frob")
         with action:
             d = Deferred()
             d.addCallback(gotResult, x=1)
             return d

This has two problems.
First, ``gotResult`` is not going to run in the context of the action.
Second, the action finishes once the ``with`` block finishes, i.e. before ``gotResult`` runs.
If we want ``gotResult`` to be run in the context of the action and to delay the action finish we need to do some extra work, and manually wrapping all callbacks would be tedious.

To solve this problem you can use the ``eliot.twisted.DeferredContext`` class.
It grabs the action context when it is first created and provides the same API as ``Deferred`` (``addCallbacks`` and friends), with the difference that added callbacks run in the context of the action.
When all callbacks have been added you can indicate that the action should finish after those callbacks have run by calling ``DeferredContext.addActionFinish``.
As you would expect, if the ``Deferred`` fires with a regular result that will result in success message.
If the ``Deferred`` fires with an errback that will result in failure message.
Finally, you can unwrap the ``DeferredContext`` and access the wrapped ``Deferred`` by accessing its ``result`` attribute.

.. code-block:: python

     from eliot import startAction, Logger
     from eliot.twisted import DeferredContext

     logger = Logger()


     def go():
         action = startAction(logger, u"yourapp:subsystem:frob")
         with action.context():
             d = DeferredContext(Deferred())
             # gotResult(result, x=1) will be called in the context of the action:
             d.addCallback(gotResult, x=1)
             # After gotResult finishes, finish the action:
             d.addActionFinish()
             # Return the underlying Deferred:
             return d.result


Type System
-----------

So far we've been creating messages and actions in an unstructured manner.
This means it's harder to support types that aren't built-in and to validate message structure.
There's no documentation of what fields messages and action messages expect.
To improve this we introduce the preferred API for creating actions and standalone messages: ``ActionType`` and ``MessageType``.

A ``Field`` instance is used to validate fields of messages, and to serialize rich types to the built-in supported types.
It is created with the name of the field, a a serialization function that converts the input to an output and a description.
The serialization function must return a result that is JSON-encodable.
You can also pass in an extra validation function.
If you pass this function in it will be called with values that are being validated; if it raises ``eliot.ValidationError`` that value will fail validation.

A couple of utility functions allow creating specific types of ``Field`` instances.
``Field.for_value`` returns a ``Field`` that only can have a single value.
More generally useful, ``Field.for_types`` returns a ``Field`` that can only be one of certain specific types: some subset of ``unicode``, ``bytes``, ``int``, ``float``, ``bool``, ``list`` and ``dict`` as well as ``None`` which technically isn't a class.
As always, ``bytes`` must only contain UTF-8 encoded Unicode.

.. code-block:: python

    from eliot import Field

    def userToUsername(user):
        """
        Extract username from a User object.
        """
        return user.username

    USERNAME = Field(u"username", userToUsername, u"The name of the user.")

    # Validation is useful for unit tests and catching bugs; it's not used in
    # the actual logging code path. We therefore don't bother catching things
    # we'd do in e.g. web form validation.
    def _validateAge(value):
        if value is not None and value < 0:
             raise ValidationError("Field 'age' must be positive:", value)
    AGE = Field.for_types(u"age", [int, None],
                         u"The age of the user, might be None if unknown",
                         _validateAge)


MessageType
^^^^^^^^^^^

Now that you have some fields you can create a custom ``MessageType``.
This takes a message name which will be put in the ``message_type`` field of resulting messages.
It also takes a list of ``Field`` instances and a description.

.. code-block:: python

    from eliot import MessageType, Field
    USERNAME = Field.for_types("username", [str])
    AGE = Field.for_types("age", [int])

    LOG_USER_REGISTRATION = MessageType(u"yourapp:authentication:registration",
                                        [USERNAME, AGE],
                                        u"We've just registered a new user.")

Since this syntax is rather verbose a utility function called ``fields`` is provided which creates a ``list`` of ``Field`` instances for you, with support to specifying the types of the fields.
The equivalent to the code above is:

.. code-block:: python

    from eliot import MessageType, fields

    LOG_USER_REGISTRATION = MessageType(u"yourapp:authentication:registration",
                                        fields(username=str, age=int))

Given a ``MessageType`` you can create a ``Message`` instance with the ``message_type`` field pre-populated.
You can then use it the way you would normally use ``Message``, e.g. ``bind()`` or ``write()``.

.. code-block:: python

    msg = LOG_USER_REGISTRATION(username=user, age=193)
    msg.write(logger)

A ``Message`` created from a ``MessageType`` will automatically use the ``MessageType`` ``Field`` instances to serialize its fields.

Keep in mind that no validation is done when messages are created.
Instead, validation is intended to be done in your unit tests.
If you're not unit testing all your log messages you're doing it wrong.
Luckily, Eliot makes it pretty easy to test logging as we'll see in a bit.


ActionType
^^^^^^^^^^

Similarly to ``MessageType`` you can also create types for actions.
Unlike a ``MessageType`` you need two sets of fields: one for action start, one for success.

.. code-block:: python

    from eliot import ActionType, fields, Logger

    LOG_USER_SIGNIN = ActionType(u"yourapp:authentication:signin",
                                 # Start message fields:
                                 fields(username=str),
                                 # Success message fields:
                                 fields(status=int),
                                 # Description:
                                 u"A user is attempting to sign in.")

Calling the resulting instance is equivalent to ``start_action``.
For ``start_task`` you can call ``LOG_USER_SIGNIN.as_task``.

.. code-block:: python

    logger = Logger()

    def signin(user, password):
         with LOG_USER_SIGNIN(logger, username=user) as action:
             status = user.authenticate(password)
             action.add_success_fields(status=status)
         return status

Again, as with ``MessageType``, field values will be serialized using the ``Field`` definitions in the ``ActionType``.


Unit Testing
------------

Now that you've got some code emitting log messages (or even better, before you've written the code) you can write unit tests to verify it.
Given good test coverage all code branches should already be covered by tests unrelated to logging.
Logging can be considered just another aspect of testing those code branches.
Rather than recreating all those tests as separate functions Eliot provides a decorator the allows adding logging assertions to existing tests.
``unittest.TestCase`` test methods decorated with ``eliot.testing.validate_logging`` will be called with a ``logger`` keyword argument, a ``eliot.MemoryLogger`` instance, which should replace any ``eliot.Logger`` in objects being tested.
The ``validate_logging`` decorator takes an argument: another function that takes the ``TestCase`` instance as its first argument (``self``), and the ``logger`` as its second argument.
This function can make assertions about logging after the main test function has run.
You can also pass additional arguments and keyword arguments to ``@validate_logging``, in which case the assertion function will get called with them as well.

Let's unit test some code that relies on the ``LOG_USER_REGISTRATION`` object we created earlier.


.. code-block:: python

      from eliot import Logger
      from myapp.logtypes import LOG_USER_REGISTRATION

      class UserRegistration(object):
          logger = Logger()

          def __init__(self):
              self.db = {}

          def register(self, username, password, age):
              self.db[username] = (password, age)
              LOG_USER_REGISTRATION(
                   username=username, password=password, age=age).write(self.logger)


Here's how we'd test it:

.. code-block:: python

    from unittest import TestCase
    from eliot import MemoryLogger
    from eliot.testing import assertContainsFields, validate_logging

    from myapp.registration import UserRegistration
    from myapp.logtypes import LOG_USER_REGISTRATION


    class LoggingTests(TestCase):
        def assertRegistrationLogging(self, logger):
            """
            Logging assertions for test_registration.
            """
            self.assertEqual(len(logger.messages), 1)
            msg = logger.messages[0]
            assertContainsFields(self, msg,
                                 {u"username": u"john",
                                  u"password": u"password",
                                  u"age": 12}))

        @validate_logging(assertRegistrationLogging)
        def test_registration(self, logger):
            """
            Registration adds entries to the in-memory database.
            """
            registry = UserRegistration()
            registry.logger = logger
            registry.register(u"john", u"password", 12)
            self.assertEqual(registry.db[u"john"], (u"passsword", 12))


Besides calling an the given validation function the ``@validate_logging`` decorator will also validate the logged messages after the test is done.
E.g. it will make sure they are JSON encodable.
Messages were created using ``ActionType`` and ``MessageType`` will be validated using the applicable ``Field`` definitions.
You can also call ``MemoryLogger.validate`` yourself to validate written messages.
If you don't want any additional logging assertions you can decorate your test function using ``@validate_logging(None)``.


Testing Tracebacks
^^^^^^^^^^^^^^^^^^

Tests decorated with ``@validate_logging`` will fail if there are any tracebacks logged to the given ``MemoryLogger`` (using ``write_traceback`` or ``writeFailure``) on the theory that these are unexpected errors indicating a bug.
If you expected a particular exception to be logged you can call ``MemoryLogger.flush_tracebacks``, after which it will no longer cause a test failure.
The result will be a list of traceback message dictionaries for the particular exception.

.. code-block:: python

    from unittest import TestCase
    from eliot.testing import validate_logging

    class MyTests(TestCase):
        def assertMythingBadPathLogging(self, logger):
            messages = logger.flush_tracebacks(OSError)
            self.assertEqual(len(messages), 1)

        @validate_logging(assertMythingBadPathLogging)
        def test_mythingBadPath(self, logger):
             mything = MyThing()
             mything.logger = logger
             # Trigger an error that will cause a OSError traceback to be logged:
             self.assertFalse(mything.load("/nonexistent/path"))



Testing Message and Action Structure
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Eliot provides utilities for making assertions about the structure of individual messages and actions.
The simplest method is using the ``assertHasMessage`` utility function which asserts that a message of a given ``MessageType`` has the given fields:

.. code-block:: python

    from eliot.testing import assertHasMessage, validate_logging

    class LoggingTests(TestCase):
        @validate_logging(assertHasMessage, LOG_USER_REGISTRATION,
                         {u"username": u"john",
                          u"password": u"password",
                          u"age": 12})
        def test_registration(self, logger):
            """
            Registration adds entries to the in-memory database.
            """
            registry = UserRegistration()
            registry.logger = logger
            registry.register(u"john", u"password", 12)
            self.assertEqual(registry.db[u"john"], (u"passsword", 12))


``assertHasMessage`` returns the found message and can therefore be used within more complex assertions. ``assertHasAction`` provides similar functionality for actions (see example below).

More generally, ``eliot.testing.LoggedAction`` and ``eliot.testing.LoggedMessage`` are utility classes to aid such testing.
``LoggedMessage.of_type`` lets you find all messages of a specific ``MessageType``.
A ``LoggedMessage`` has an attribute ``message`` which contains the logged message dictionary.
For example, we could rewrite the registration logging test above like so:

.. code-block:: python

    from eliot.testing import LoggedMessage, validate_logging

    class LoggingTests(TestCase):
        def assertRegistrationLogging(self, logger):
            """
            Logging assertions for test_registration.
            """
            logged = LoggedMessage.of_type(logger.messages, LOG_USER_REGISTRATION)[0]
            assertContainsFields(self, logged.message,
                                 {u"username": u"john",
                                  u"password": u"password",
                                  u"age": 12}))

        @validate_logging(assertRegistrationLogging)
        def test_registration(self, logger):
            """
            Registration adds entries to the in-memory database.
            """
            registry = UserRegistration()
            registry.logger = logger
            registry.register(u"john", u"password", 12)
            self.assertEqual(registry.db[u"john"], (u"passsword", 12))


Similarly, ``LoggedAction.of_type`` finds all logged actions of a specific ``ActionType``.
A ``LoggedAction`` instance has ``start_message`` and ``end_message`` containing the respective message dictionaries, and a ``children`` attribute containing a list of child ``LoggedAction`` and ``LoggedMessage``.
That is, a ``LoggedAction`` knows about the messages logged within its context.
``LoggedAction`` also has a utility method ``descendants()`` that returns an iterable of all its descendants.
We can thus assert that a particular message (or action) was logged within the context of another action.

For example, let's say we have some code like this:

.. code-block:: python

    LOG_SEARCH = ActionType(...)
    LOG_CHECK = MessageType(...)

    class Search:
        logger = Logger()

        def search(self, servers, database, key):
            with LOG_SEARCH(self.logger, database=database, key=key):
            for server in servers:
                LOG_CHECK(server=server).write(self.logger)
                if server.check(database, key):
                    return True
            return False

We want to assert that the LOG_CHECK message was written in the context of the LOG_SEARCH action.
The test would look like this:

.. code-block:: python

    from eliot.testing import LoggedAction, LoggedMessage, validate_logging
    import searcher

    class LoggingTests(TestCase):
        @validate_logging(None)
        def test_logging(self, logger):
            searcher = Search()
            searcher.logger = logger
            servers = [buildServer(), buildServer()]

            searcher.search(servers, "users", "theuser")
            action = LoggedAction.of_type(logger.messages, searcher.LOG_SEARCH)[0]
            messages = LoggedMessage.of_type(logger.messages, searcher.LOG_CHECK)
            # The action start message had the appropriate fields:
            assertContainsFields(self, action.start_message,
                                 {"database": "users", "key": "theuser"})
            # Messages were logged in the context of the action
            self.assertEqual(action.children, messages)
            # Each message had the respective server set.
            self.assertEqual(servers, [msg.message["server"] for msg in messages])


Or we can simplify further by using ``assertHasMessage`` and ``assertHasAction``:

.. code-block:: python

    from eliot.testing import LoggedAction, LoggedMessage, validate_logging
    import searcher

    class LoggingTests(TestCase):
        @validate_logging(None)
        def test_logging(self, logger):
            searcher = Search()
            searcher.logger = logger
            servers = [buildServer(), buildServer()]

            searcher.search(servers, "users", "theuser")
            action = assertHasAction(self, logger, searcher.LOG_SEARCH, succeeded=True,
                                     startFields={"database": "users",
                                                  "key": "theuser"})

            # Messages were logged in the context of the action
            messages = LoggedMessage.of_type(logger.messages, searcher.LOG_CHECK)
            self.assertEqual(action.children, messages)
            # Each message had the respective server set.
            self.assertEqual(servers, [msg.message["server"] for msg in messages])


Serialization Errors
--------------------

While validation only happens in ``MemoryLogger.validate`` (either manually or when run by ``@validate_logging``), serialization must run in the normal logging code path.
Eliot tries to very hard never to raise exceptions from the log writing code path so as not to prevent actual code from running.
If a message fails to serialize then a ``eliot:traceback`` message will be logged, along with a ``eliot:serialization_failure`` message with an attempt at showing the message that failed to serialize.

.. code-block:: json

    {"exception": "exceptions.ValueError",
     "timestamp": "2013-11-22T14:16:51.386745Z",
     "traceback": "Traceback (most recent call last):\n  ... ValueError: invalid literal for int() with base 10: 'hello'\n",
     "system": "eliot:output",
     "reason": "invalid literal for int() with base 10: 'hello'",
     "message_type": "eliot:traceback"}
    {"timestamp": "2013-11-22T14:16:51.386827Z",
     "message": "{u\"u'message_type'\": u\"'test'\", u\"u'field'\": u\"'hello'\", u\"u'timestamp'\": u\"'2013-11-22T14:16:51.386634Z'\"}",
     "message_type": "eliot:serialization_failure"}
