"""
Eliot actions are not quite the same as a callstack since a child can
live on after a parent.

Imagine the following tree:

|-----[root]-----|
   |-[child]-|
      |--[grandchild]--|

A sampling of running actions would likely find:

rrr           rrrr
   ccc
      gggggggggggggggggg

The fact that grandchild overlaps with root in the end after child has
ended means they're likely both running at same time. Thus a sampling
strategy would have found both. Otherwise it's not clear how the root
could ever end.

We can use the following algorithm to implement this:
Record each action's callstack (its type and ancestor actions' types) for
the time span from start to end where it has no child actions
running. Descendants don't count, only children.  This can easily be
calculated by constructing a tree of actions and traversing it from the
root.

This is not a guarantee that is what is going on exactly but it's likely
a reasonable approximation, and will be accurate for blocking code.

Consider using intervaltree library.

The code below is a broken sketch of a previous attempt.
"""
from sys import stdin, stdout

from intervaltree import IntervalTree

from pyrsistent import pvector

from ._message import (
    TIMESTAMP_FIELD, TASK_UUID_FIELD, TASK_LEVEL_FIELD,
)
from ._action import (
    WrittenAction,
)
from ._bytesjson import loads
from ._parse import Parser


def json_messages():
    for line in stdin:
        yield loads(line)


def task_to_call_stacks(root_action):
    interval_tree = IntervalTree()

    def add(ancestors, current):
        ancestors = ancestors.append(current.action_type)
        # Add initial estimate of action interval:
        start = current.start_message.timestamp
        end = current.end_message.timestamp
        interval_tree.addi(start, end, ancestors)
        # Remove any overlap with parent, since we're higher on call stack:
        interval_tree.slice(start)
        interval_tree.slice(end)
        interval_tree.discardi(start, end, ancestors[:-1])
        # Add children:
        for child in current.children:
            if isinstance(child, WrittenAction):
                add(ancestors, child)
    add(pvector(), root_action)
    # Parallel, same-type actions probably shouldn't be counted twice;
    # it's confusing enough with different types:
    # interval_tree.merge_overlaps()
    return interval_tree


def _main():
    for parsed_task in Parser.parse_stream(json_messages()):
        root = parsed_task.root()
        if not isinstance(root, WrittenAction):
            continue
        for interval in task_to_call_stacks(root):
            stdout.write(";".join(interval.data) + " %d\n" % (
                interval.length() * 1000000),)


if __name__ == '__main__':
    _main()
