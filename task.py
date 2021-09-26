#!/usr/bin/env python3
"""
taskwarrior, timewarrior wrapper utilities for task and time management

  - taskdo: start task in timew, all taskw fql elements and tags as timew tags
  - taskget: search tasks as ids, uuids, labels or from descriptions, and print
  - taskfql: print fully qualified label of uniquely matching task
  - taskfqls: print fully qualified labels of several matching tasks
  - timewtags: show all tags that a task would be assigned in timewarrior

deps:
  - taskw python library with patch #151

"""
__url__     = 'http://smemsh.net/src/.task/'
__author__  = 'Scott Mcdermott <scott@smemsh.net>'
__license__ = 'GPL-2.0'

from sys import argv, stdin, stdout, stderr, exit
from uuid import UUID as uuid
from pprint import pp
from string import digits, hexdigits, ascii_lowercase as lowercase
from os.path import basename
from subprocess import check_output

from os import (
    getenv,
    EX_OK as EXIT_SUCCESS,
    EX_SOFTWARE as EXIT_FAILURE
)

from taskw import TaskWarrior
from timew import TimeWarrior

###

def err(*args, **kwargs):
    print(*args, file=stderr, **kwargs)

def bomb(*args):
    err(*args)
    exit(EXIT_FAILURE)

def exe(cmd):
    return check_output(cmd.split()).splitlines()

###

def _taskone(taskarg):
    tasks = _taskget(taskarg)
    if len(tasks) == 0:
        bomb("no matches")
    elif len(tasks) > 1:
        bomb("multiple matches")
    return tasks[0]

#

def __taskfql(task):
    prj = task.get('project')
    if prj: return f"{prj.replace('.', '/')}/{task['label']}"

def _taskfql(taskarg):
    task = _taskone(taskarg)
    return __taskfql(task)

def _taskfqls(taskarg):
    tasks = _taskget(taskarg)
    if not tasks: return []
    else: return [__taskfql(t) for t in tasks]

def taskfql(taskarg):
    print(_taskfql(taskarg) or '')

def taskfqls(taskarg):
    for t in _taskfqls(taskarg):
        print(t or '')

#

def _timewtags(task):

    tags = []

    fqlsegs = __taskfql(task).split('/')
    nsegs = len(fqlsegs)

    for i in range(1, nsegs + 1):
        tags.append('/'.join(fqlsegs[0:i]) + ('/' if i < nsegs else ''))

    if 'tags' in task:
        tags.extend([f"+{t}" for t in task['tags']])

    return tags

def timewtags(taskarg):
    task = _taskone(taskarg)
    print('\x20'.join(_timewtags(task)))

#

def taskdo(taskarg):

    task = _taskone(taskarg)
    tags = _timewtags(task)

    if 'end' in task:
        bomb("cannot proceed on ended task")

    if 'start' not in task:
        bomb("perform initial start in taskwarrior")

    timew.start(tags=tags)

#

def taskget(taskarg):
    tasks = _taskget(taskarg)
    pp(tasks)

def _taskget(taskarg):

    task_as_set = set(taskarg)

    # taskid
    try:
        taskarg = int(taskarg)
        tasks = taskw.filter_tasks(dict(id=taskarg))
        if not tasks: bomb(f"failed to find integer task {taskarg}")
        if len(tasks) != 1: bomb(f"integer id {taskarg} not unique")
        return tasks
    except ValueError: pass

    # taskuuid
    try:
        taskarg = uuid(taskarg)
        tasks = taskw.filter_tasks(dict(uuid=taskarg))
        if not tasks: bomb(f"failed to find task by uuid: {taskarg}")
        if len(tasks) != 1: bomb(f"uuid lookup for {taskarg} not unique")
        return tasks
    except ValueError: pass

    # taskuuid-initial
    if task_as_set.issubset(f"{hexdigits}-"):
        tasks = taskw.filter_tasks(dict(uuid=taskarg))
        if tasks:
            return tasks

    # label
    if task_as_set.issubset(f"{lowercase}{digits}-/"):
        if '/' not in task_as_set:
            # label
            tasks = taskw.filter_tasks(dict(label=taskarg))
            if tasks:
                return tasks
        else:
            # fully qualified label path
            fqlsegs = taskarg.split('/')
            project = '.'.join(fqlsegs[0:-1])
            label = fqlsegs[-1]
            tasks = taskw.filter_tasks(dict(project=project, label=label))
            if tasks:
                return tasks

    # description substring
    tasks = taskw.filter_tasks(dict(description=taskarg))
    if tasks: return tasks

    # description regex
    tasks = taskw.filter_tasks({'description.has': taskarg})
    if tasks: return tasks

    return None

###

def main(taskarg):

    if debug == 1: breakpoint()

    try: subprogram = globals()[invname]
    except (KeyError, TypeError):
        bomb(f"unimplemented command '{invname}'")

    instcnt = subprogram(taskarg)

###

if __name__ == "__main__":

    from sys import hexversion
    if hexversion < 0x03090000:
        bomb("minimum python 3.9")

    from bdb import BdbQuit
    debug = int(getenv('DEBUG') or 0)
    if debug:
        from pprint import pp
        err('debug: enabled')

    invname = basename(argv[0])
    args = argv[1:]

    taskw = TaskWarrior(marshal=True)
    timew = TimeWarrior()

    try: main()
    except BdbQuit: bomb("debug: stop")
