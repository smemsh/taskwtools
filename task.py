#!/usr/bin/env python3
"""
taskwarrior, timewarrior wrapper utilities for task and time management

  - taskdo: start task in timew, all taskw fql elements and tags as timew tags
  - taskid: get exactly one matching id from taskget or fail
  - taskids: get multiple matching ids from taskget algorithm
  - taskget: search tasks as ids, uuids, labels or from descriptions, and print
  - tasknow: show last started task and whether it's active
  - taskday: show labels of tasks from last 24 hours
  - taskweek: show labels of tasks from last 168 hours
  - taskfql: print fully qualified label of uniquely matching task
  - taskfqls: print fully qualified labels of several matching tasks
  - taskstop: stop the current started task in timewarrior
  - taskline: show output suitable for conferring status to window manager
  - timewtags: show all tags that a task would be assigned in timewarrior
  - on-modify.timew: hook runs on all task mods (via symlink in hooks/)

deps:
  - taskw python library with patch #151
  - timew python library with patches 9-13

"""
__url__     = 'http://smemsh.net/src/.task/'
__author__  = 'Scott Mcdermott <scott@smemsh.net>'
__license__ = 'GPL-2.0'

from re import search
from sys import argv, stdin, stdout, stderr, exit
from uuid import UUID as uuid
from json import loads as jloads, dumps as jdumps
from pprint import pp
from string import digits, hexdigits, ascii_lowercase as lowercase
from os.path import basename
from datetime import datetime, timedelta
from subprocess import check_output

from os import (
    getenv,
    EX_OK as EXIT_SUCCESS,
    EX_SOFTWARE as EXIT_FAILURE
)

from taskw import TaskWarrior
from timew import TimeWarrior
from timew.exceptions import TimeWarriorError

###

def err(*args, **kwargs):
    print(*args, file=stderr, **kwargs)

def bomb(*args):
    err(*args)
    exit(EXIT_FAILURE)

def dprint(*args, **kwargs):
    if not debug: return
    err('debug:', *args, **kwargs)

def exe(cmd):
    return check_output(cmd.split()).splitlines()

###

# fails if not exactly one match from lookup
def _taskone(taskarg, abort=True):

    tasks = _taskget(taskarg)
    n = len(tasks)
    if n == 1: return tasks[0]
    elif n == 0: errmsg = "no matches"
    elif n > 1: errmsg = "multiple matches"

    if abort: bomb(errmsg)
    else: err(errmsg); return {}

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

def _fqltask(fql):
    segs = fql.split('/')
    project = '.'.join(segs[0:-1])
    label = segs[-1]
    return {'project': project, 'label': label}

def taskfql(taskarg):
    print(_taskfql(taskarg) or '')

def taskfqls(taskarg=None):
    for t in _taskfqls(taskarg):
        print(t or '')

#

def _timewtags(task):

    tags = []

    if isinstance(task, str): fql = task
    elif isinstance(task, dict): fql = __taskfql(task)
    else: bomb("unsupported type for _timewtags() arg")

    if fql: fqlsegs = fql.split('/')
    else: fqlsegs = []
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

# arg: lookup task, switch to that one if not already
# noarg: start last task (timew continue)
#
def taskdo(taskarg=None):
    # there's exactly one match if _taskone() returns
    task = _taskone(taskarg) if taskarg else None
    return _taskdo(task)

def _taskdo(task=None):

    if task:
        tags = _timewtags(task)
        tagstr = '\x20'.join(tags)
        print("timewtags:", tagstr)
        if 'end' in task: bomb("cannot proceed on ended task")
        if 'start' not in task: bomb("do initial start in taskwarrior")
        stdout, stderr = timew.start(tags=tags)
        print(stdout, stderr)

    else:
        fql, active = _tasknow()
        if active:
            print(f"{fql} already")
            return
        else:
            task = _taskone(fql, abort=False)
            if task and task.get('end'):
                bomb("cannot restart ended task", fql)
            else:
                # either no task with fql from @1 was found (as
                # in case of timew-only tags like those in time/
                # namespace), or task can be worked on, ie not
                # yet ended, either case we will just try to
                # continue the last task.
                #
                # TODO maybe this whole part can be skipped and
                # we just always continue on taskdo(None)? it's
                # idempotent if already started
                #
                pass
            stdout, stderr = timew.cont(1)
            print(stdout, stderr)

#

def isfql(s):
    labelre = r'[0-9a-zA-Z-_]+'
    fqlre = f"(({labelre}/)+)({labelre})$"
    return bool(search(fqlre, s))

# no way to know tags of @1 besides export all and filter for id
# number 1; should add this capability to timewarrior itself
#
def _tasknow():

    timedata = timew.export()

    try:
        curtask = next(filter(lambda task: task['id'] == 1, timedata))
        fql = next(filter(isfql, curtask.get('tags')))
    except:
        bomb("task @1 must exist and have an fql tag")

    active = not bool(curtask.get('end'))
    return fql, active

def tasknow():
    current, active = _tasknow()
    print(current, 'started' if active else 'stopped')

#

def taskline():
    nowtimefmt = datetime.now().strftime("%Y%m%d%H%M%S")
    fql, active = _tasknow()
    active = '*' if active else '-'
    print(fql, active, nowtimefmt)

#

def tasks(): taskweek()
def taskweek(): taskday(7)
def taskday(ndays=1):

    def fql_among_tags(task):
        filtered = list(filter(isfql, task['tags']))
        if len(filtered) != 1:
            bomb("filtered more than one fql tag for task")
        return filtered[0]

    def label_from_tags(task):
        fql = fql_among_tags(task)
        label = fql.split('/')[-1]
        return label

    filterfn = label_from_tags

    ago = datetime.now() - timedelta(days=int(ndays))
    tasks = timew.export(start_time=ago)

    # set would work but loses order
    labels = reversed(list(dict.fromkeys(
        [filterfn(task) for task in tasks])))

    print('' if tasks[-1].get('end') else '*', end='')
    print('\x20'.join(labels))

#

def taskstop(taskarg=None):

    if (taskarg):
        bomb("taskstop: no args allowed")

    _, active = _tasknow()
    if active:
        stdout, stderr = _taskstop()
        print(stdout, stderr)
    else:
        print("already stopped")

def _taskstop(task=None):

    if task:
        # takes task arg when run from on-modify, but wont from
        # cli.  from on-modify, 'new' is passed, and we already
        # know it contains 'end', so 'start' cannot be present
        # (although see TW#2516 discussion for possible changes
        # to this later). however it might still be the active timew
        # task, in which case we have to stop it in timewarrior
        # before allowing taskwarrior to mark it completed.  for
        # this we just compare to _tasknow(), this is not done a
        # second time since taskstop() is not called from
        # on-modify (and won't pass a 'task' to this function),
        # but rather _taskstop()
        #
        fql, active = _tasknow()
        if active and __taskfql(task) == fql:
            return timew.stop()
        else:
            print("task already stopped or never started")
    else:
        return timew.stop()

#

def taskget(taskarg=None):
    tasks = _taskget(taskarg)
    pp(tasks)

def taskids(taskarg):
    tasks = taskget_(taskarg)
    pp([t['id'] for t in tasks])

def taskid(taskarg):
    task = _taskone(taskarg)
    pp(task['id'])

def _taskget(taskarg=None):

    # all tasks if nothing specific requested
    if not taskarg:
        return taskw.filter_tasks({'status.any': ''})

    # taskid
    try:
        taskarg = int(taskarg)
        tasks = taskw.filter_tasks({'id': taskarg})
        if not tasks: bomb(f"failed to find integer task {taskarg}")
        if len(tasks) != 1: bomb(f"integer id {taskarg} not unique")
        return tasks
    except ValueError: pass

    # taskuuid
    try:
        taskarg = uuid(taskarg)
        tasks = taskw.filter_tasks({'uuid': taskarg})
        if not tasks: bomb(f"failed to find task by uuid: {taskarg}")
        if len(tasks) != 1: bomb(f"uuid lookup for {taskarg} not unique")
        return tasks
    except ValueError: pass

    # taskuuid-initial
    if set(taskarg).issubset(f"{hexdigits}-"):
        tasks = taskw.filter_tasks({'uuid': taskarg})
        if tasks:
            return tasks

    # label
    if set(taskarg).issubset(f"{lowercase}{digits}-/"):
        if '/' in taskarg: f = _fqltask(taskarg) # fql
        else: f = {'label': taskarg} # label
        tasks = taskw.filter_tasks(f)
        if tasks:
            return tasks

    # description substring
    tasks = taskw.filter_tasks({'description': taskarg})
    if tasks: return tasks

    # description regex
    tasks = taskw.filter_tasks({'description.has': taskarg})
    if tasks: return tasks

    return []

###

def on_modify_timew(*args):

    def timewids(fql):
        return [ival['id'] for ival in timew.export(tags=[fql])]

    def retimew(oldtask, newtask):

        adds = []
        removes = []

        old = set(_timewtags(oldtask))
        new = set(_timewtags(newtask))
        both = old.union(new)
        for t in both:
            if t not in old: adds.append(t)
            if t not in new: removes.append(t)
        dprint(f"adds: {adds}")
        dprint(f"removes: {removes}")

        for timewid in timewids(__taskfql(oldtask)):
            try:
                if adds: timew.tag(timewid, adds)
                if removes: timew.untag(timewid, removes)
            except TimeWarriorError as e:
                print(f"returned: {e.code}, stderr: {e.stderr}")
                raise
    #

    for i in range(len(args)):
        dprint(f"${i+1} {args[i]}")

    old = jloads(stdin.readline())
    new = jloads(stdin.readline())
    dprint(f"old: {old}")
    dprint(f"new: {new}")

    keyset = sorted(set(old).union(new))
    dprint(f"union: {keyset}\x20")

    added = {}; changed = {}; deleted = {}
    for k in keyset:
        if k not in old: added.update({k: new[k]})
        elif k not in new: deleted.update({k: old[k]})
        elif old[k] != new[k]: changed.update({k: new[k]})

    debugstr = ''
    for c, d in [('+', added), ('-', deleted), ('*', changed)]:
        for k, v in d.items():
            debugstr += f"{c}{k}:{v}\x20"
    dprint(f"delta: {debugstr}")

    #

    oldtimew = _timewtags(old)
    newtimew = _timewtags(new)
    retag = False if set(oldtimew) == set(newtimew) else True

    if 'start' in new:

        if 'start' not in old:
            _taskdo(new)

        timekeys = set(['start', 'end'])
        if set(old).intersection(timekeys):
            if set(changed).intersection(timekeys):
                attrlist = ',\x20'.join(timekeys)
                bomb(f"timew propagation not implemented for {attrlist}")
            if retag:
                retimew(old, new)

    elif 'start' in old:

        if 'end' in new and 'end' not in old:
            if retag: retimew(old, new)
            _taskstop(new)

        if 'end' not in new:
            print("disallowing pause, use timewarrior until 'done'")
            exit(EXIT_FAILURE)

    print(jdumps(new))


###

def main():

    if debug == 1: breakpoint()

    try: subprogram = globals()[invname]
    except (KeyError, TypeError):
        bomb(f"unimplemented command '{invname}'")

    instcnt = subprogram(*args)

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

    # support invocation as taskw trigger symlink
    invname = invname.replace('-', '_').replace('.', '_')

    taskw = TaskWarrior(marshal=True)
    timew = TimeWarrior()

    try: main()
    except BdbQuit: bomb("debug: stop")
