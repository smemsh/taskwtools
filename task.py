#!/usr/bin/env python3
"""
taskwarrior utilities, especially for coordination with timewarrior
  - taskget: search tasks as ids, uuids, labels or from descriptions, and print

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

###

def err(*args, **kwargs):
    print(*args, file=stderr, **kwargs)

def bomb(*args):
    err(*args)
    exit(EXIT_FAILURE)

def exe(cmd):
    return check_output(cmd.split()).splitlines()

###

def taskget(taskarg):
    tasks = _taskget(taskarg)
    pp(tasks)

def _taskget(taskarg):

    taskw = TaskWarrior(marshal=True)
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
            lsegments = taskarg.split('/')
            project = '.'.join(lsegments[0:-1])
            label = lsegments[-1]
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

    if debug: breakpoint()

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
    if bool(getenv('DEBUG')):
        from pprint import pp
        debug = True
        err('debug-mode-enabled')
    else:
        debug = False

    invname = basename(argv[0])
    args = argv[1:]

    try: main(args[0])
    except BdbQuit: bomb("debug-stop")
