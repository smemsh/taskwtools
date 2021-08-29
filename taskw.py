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
    environ,
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

def taskget():
    tasks = _taskget(args[0])
    pp(tasks)

def _taskget(taskarg):

    taskw = TaskWarrior(marshal=True)
    task_as_set = set(taskarg)

    # taskid
    try:
        taskarg = int(taskarg)
        task = taskw.get_task(id=taskarg)
        if not task:
            bomb(f"could not find task with integer id {taskarg}")
        return task
    except ValueError: pass

    # taskuuid
    try:
        taskarg = uuid(taskarg)
        task = taskw.get_task(uuid=taskarg)
        if not task:
            bomb(f"could not find task with uuid {taskarg}")
        return task
    except ValueError: pass

    # taskuuid-initial
    if task_as_set.issubset(f"{hexdigits}-"):
        task = taskw.filter_tasks(dict(uuid=taskarg))
        if task:
            return task

    # label
    if task_as_set.issubset(f"{lowercase}{digits}-/"):
        if '/' not in task_as_set:
            # label
            task = taskw.filter_tasks(dict(label=taskarg))
            if task:
                return task
        else:
            # fully qualified label path
            lsegments = taskarg.split('/')
            project = '.'.join(lsegments[0:-1])
            label = lsegments[-1]
            task = taskw.filter_tasks(dict(project=project, label=label))
            if task:
                return task

    # description substring
    task = taskw.filter_tasks(dict(description=taskarg))
    if task: return task

    # description regex
    task = taskw.filter_tasks({'description.has': taskarg})
    if task: return task

    return None

###

def main():

    if debug: breakpoint()

    try: subprogram = globals()[invname]
    except (KeyError, TypeError):
        bomb(f"unimplemented command '{invname}'")

    instcnt = subprogram()

###

if __name__ == "__main__":

    from sys import version_info as pyv
    if pyv.major < 3 or pyv.major == 3 and pyv.minor < 9:
        bomb("minimum python 3.9")

    invname = basename(argv[0])
    args = argv[1:]

    try:
        from bdb import BdbQuit
        if bool(environ['DEBUG']):
            debug = True
            err('debug-mode-enabled')
        else:
            raise KeyError

    except KeyError:
        debug = False

    try: main()
    except BdbQuit: bomb("debug-stop")
