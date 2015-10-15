"""
Parse a stream of serialized messages into a forest of
``WrittenAction`` and ``WrittenMessage`` objects.

# XXX maybe move Written* here.
"""

from pyrsistent import PClass, field, pmap_field, optional, pvector

from ._message import WrittenMessage
from ._action import (
    TaskLevel, WrittenAction, ACTION_STATUS_FIELD, STARTED_STATUS,
)


#@implementer(IWrittenAction)
class MissingAction(PClass):
    _task_level = field(type=TaskLevel, mandatory=True)
    end_message = field(type=optional(WrittenMessage), mandatory=True,
                        initial=None)
    _children = pmap_field(TaskLevel, object)

    def task_level(self):
        return self._task_level

    def action_type(self):
        return u"*unknown*"

    @property
    def children(self):
        """
        The list of child messages and actions sorted by task level, excluding the
        start and end messages.
        """
        return pvector(sorted(self._children.values(), key=lambda m: m.task_level))


_NODES = (MissingAction, WrittenAction, WrittenMessage)


class Task(PClass):
    """
    A tree of actions with the same task UUID.
    """
    _nodes = pmap_field(TaskLevel, object) # XXX _NODES

    @classmethod
    def create(cls, first_message):
        task = Task()
        return task.add(first_message)

    def root(self):
        return self._nodes[TaskLevel(level=[])]

    def _add_new_node(self, new_node, initial_task_level):
        task = self
        child = new_node
        task_level = initial_task_level
        while task_level.parent() is not None:
            parent = self._nodes.get(task_level.parent())
            if parent is None:
                parent = MissingAction(_task_level=task_level.parent())
            parent = parent.transform(["_children", task_level], child)
            task = task.transform(["_nodes", parent.task_level()], parent)
            child = parent
            task_level = parent.task_level()
        return task

    def add(self, message_dict):
        task = self
        is_action = message_dict.get("action_type") is not None
        written_message = WrittenMessage.from_dict(message_dict)
        action_level = written_message.task_level
        if is_action:
            current_action = self._nodes.get(action_level)
            if message_dict[ACTION_STATUS_FIELD] == STARTED_STATUS:
                if current_action is None:
                    new_node = WrittenAction.from_messages(written_message)
                else:
                    new_node = current_action.to_written_action(
                        written_message)
            else:
                new_node = current_action.set(end_message=written_message)
            task_level = new_node.task_level()
        else:
            new_node = written_message
            task_level = written_message.task_level
        task = task._add_new_node(new_node, task_level)
        return task
