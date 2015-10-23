"""
Parse a stream of serialized messages into a forest of
``WrittenAction`` and ``WrittenMessage`` objects.

# XXX maybe move Written* here.
"""

from __future__ import unicode_literals

from pyrsistent import PClass, pmap_field

from ._message import WrittenMessage, TASK_UUID_FIELD
from ._action import (
    TaskLevel, WrittenAction, ACTION_STATUS_FIELD, STARTED_STATUS,
    ACTION_TYPE_FIELD,
)


class Task(PClass):
    """
    A tree of actions with the same task UUID.
    """
    _nodes = pmap_field(TaskLevel, (WrittenAction, WrittenMessage))

    _root_level = TaskLevel(level=[])

    def root(self):
        return self._nodes[self._root_level]

    def _insert_action(self, node):
        task = self.transform(["_nodes", node.task_level], node)
        return task._ensure_node_parents(node)

    def _ensure_node_parents(self, child):
        """
        Ensure the node (WrittenAction/WrittenMessage/MissingAction) is
        referenced by parent nodes.

        MissingAction will be created as necessary.
        """
        task_level = child.task_level
        if task_level.parent() is None:
            return self

        parent = self._nodes.get(task_level.parent())
        if parent is None:
            parent = WrittenAction(task_level=task_level.parent(),
                                   task_uuid=child.task_uuid)
        parent = parent._add_child(child)
        return self._insert_action(parent)

    def add(self, message_dict):
        is_action = message_dict.get(ACTION_TYPE_FIELD) is not None
        written_message = WrittenMessage.from_dict(message_dict)
        if is_action:
            action_level = written_message.task_level.parent()
            action = self._nodes.get(action_level)
            if action is None:
                action = WrittenAction(task_level=action_level,
                                       task_uuid=message_dict[TASK_UUID_FIELD])
            if message_dict[ACTION_STATUS_FIELD] == STARTED_STATUS:
                # Either newly created MissingAction, or one created by
                # previously added descendant of the action.
                action = action._start(written_message)
            else:
                action = action._end(written_message)
            return self._insert_action(action)
        else:
            # Special case where there is no action:
            if written_message.task_level.level == [1]:
                return self.transform(
                    ["_nodes", self._root_level], written_message)
            else:
                return self._ensure_node_parents(written_message)
