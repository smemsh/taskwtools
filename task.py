#!/usr/bin/env python3
"""
taskwarrior, timewarrior wrapper utilities for task and time management

  - taskdo: start task in timew, all taskw fql elements and tags as timew tags
  - taskid: print exactly one matching id (uuid if done) from taskget or fail
  - taskids: print multiple matching ids from taskget algorithm
  - taskget: search tasks as ids, uuids, labels or from descriptions, and print
  - tasknow: show last started task and whether it's active
  - taskday: show labels of tasks from last 24 hours
  - taskweek: show labels of tasks from last 168 hours
  - taskfql: print fully qualified label of uniquely matching task
  - taskfqls: print fully qualified labels of several matching tasks
  - taskstop: stop the current started task in timewarrior
  - taskline: show output suitable for conferring status to window manager
  - tasknotes: display formatted list of all the annotations of a task
  - timewtags: show all tags that a task would be assigned in timewarrior
  - on-modify.timew: hook runs on all task mods (via symlink in hooks/)

deps:
  - taskw python library with patch #151 and #159
  - timew python library with patches 9-13

"""
__url__     = 'https://github.com/smemsh/.task/'
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
from textwrap import fill
from argparse import ArgumentParser, RawTextHelpFormatter, Namespace
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

#

def addopt(p, flagchar, longopt, help=None, /, **kwargs):
    options = list(("-%s --%s" % (flagchar, longopt)).split())
    p.add_argument(*options, help=help, **kwargs)

def addarg(p, vname, vdesc, help=None, /, **kwargs):
    p.add_argument(vname, metavar=vdesc, help=help, **kwargs)

def addflag(*args, **kwargs):
    addopt(*args, action='store_true', **kwargs)

def addopts(*args, **kwargs):
    addopt(*args, action='store', **kwargs)

def addargs(*args, **kwargs):
    addarg(*args, nargs='*', **kwargs)

# allow cumulative option parsing.  the resulting Namespace() will be a
# union of all flag/option processing with later calls to addfoo()
# overriding earlier-specified attribute values with the same name
# (TODO: wrong, actually later *new* ones can join, but overrides won't
# occur, see comments when a Namespace is given as arg)
#
def optparse(name, argp, *args):

    global argns
    global argslast
    global argsall

    nsarg = None
    if len(args) and isinstance(args[0], Namespace):
        # we got a Namespace, which means args already got processed
        # once, which means any leftover (unrecognized from last time)
        # are in argslast. the Namespace given has what we parsed so
        # far.  we'll pass this namespace to parse_args so it can
        # override and/or append new members upon re-parsing the
        # leftovers.  then we'll again leave the still-leftovers in
        # there for any still-later arg parsing.  TODO this means first
        # use wins and the parsed flags will never be seen again by
        # later uses, which also means override isn't possible
        #
        nsarg = args[0]
        args = argslast
    ns = nsarg if nsarg else argns
    argns, argslast = argp.parse_known_args(*args, ns)
    if len(argslast): err(f"skipping unknown args: {argslast}")

    return argns

###

def dummy_match(n):
    if n == 0: dummy = "0fffffff-ffff-ffff-ffff-ffffffffffff"  # no matches
    elif n > 1: dummy =  "1fffffff-ffff-ffff-ffff-ffffffffffff"  # multiple
    else: bomb("n less than 0??? aborting")
    return dummy

# fails if not exactly one match from lookup
def __taskone(*args, **kwargs):
    tasks = _taskget(*args, **kwargs)
    n = len(tasks)
    if n == 1: return True, tasks.pop()
    else: return False, {'uuid': dummy_match(n)}

def _taskone(*args, **kwargs):
    abort = kwargs.get('abort', True)
    success, match = __taskone(*args, **kwargs)
    if not success and abort:
        print(match['uuid']) # cannot go to stderr because used in subshell
        exit(EXIT_FAILURE)
    return match

#

def __taskfql(task):
    prj = task.get('project')
    try:
        if prj: return f"{prj.replace('.', '/')}/{task['label']}"
    except KeyError:
        bomb("at least one task does not have a label")

def _taskfql(taskarg):
    task = _taskone(taskarg)
    return __taskfql(task)

def _taskfqls(*args):
    tasks = _taskget(*args)
    if not tasks: return []
    else: return [__taskfql(t) for t in tasks]

def _fqltask(fql):
    segs = fql.split('/')
    project = '.'.join(segs[0:-1])
    label = segs[-1]
    return {'project': project, 'label': label}

def taskfql(taskarg):
    print(_taskfql(taskarg) or '')

def taskfqls(*args):
    for t in _taskfqls(*args):
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

def mkargs():
    return ArgumentParser(
        prog            = invname,
        description     = __doc__.strip(),
        allow_abbrev    = False,
        formatter_class = RawTextHelpFormatter)

def tasknow(*args):

    argp = mkargs()
    for short, long, desc in [
        (short, long, f"show {long} of current task")
        for short, long in [
            ('i', 'id'), ('u', 'uuid'), # call taskid/taskuuid
            ('f', 'fql') # default behavior
        ]
    ]: addflag(argp, short, long, desc)
    args = optparse('tasknow', argp, args)

    current, active = _tasknow()

    # if user specified an output format (besides fql, the default), we
    # just print the requested format only, by jumping to _taskids()
    # and using kwargs in the call to specify requested output format
    #
    usefmt = False
    ofmts = ['uuid', 'id']
    kwargs = {f"use{k}": False for k in ofmts}
    for fmt in ofmts:
        if getattr(args, fmt, None):
            usefmt = True
            kwargs.update({f"use{fmt}": True})

    if usefmt:
        print(_taskids(current, onlyone=True, **kwargs))
    else:
        output = current
        if not usefmt and not args.fql:
            # user didnt specify format so we use one that includes status
            output = [output] + ['started'] if active else ['stopped']
            output = '\x20'.join(output)
        print(output)

#

def taskline():
    nowtimefmt = datetime.now().strftime("%Y%m%d%H%M%S")
    fql, active = _tasknow()
    active = '*' if active else '-'
    print(fql, active, nowtimefmt)

def tasknotes(taskarg=None):
    if not taskarg: taskarg = _tasknow()[0]
    task = _taskone(taskarg)
    desc = task['description']
    notes = task.get('annotations')
    fillargs = {
        'initial_indent': "-\x20",
        'subsequent_indent': "\x20\x20",
        'drop_whitespace': False,
        'break_on_hyphens': False,
        'break_long_words': False,
        'replace_whitespace': False,
        'width': 79,
    }
    if notes:
        print('=', desc)
        print("\n".join([fill(note, **fillargs) for note in notes]))
    else:
        print(desc)
#

def tasks(*args): taskweek(*args)
def taskweek(*args): taskday(*args, '7')
def taskday(*args):

    def fql_among_tags(task):
        filtered = list(filter(isfql, task['tags']))
        if len(filtered) != 1:
            bomb("filtered more than one fql tag for task")
        return filtered[0]

    def label_from_tags(task):
        fql = fql_among_tags(task)
        label = fql.split('/')[-1]
        return label

    argp = mkargs()
    addflag(argp, '1', 'column', 'delimit by lines instead of spaces')
    addflag(argp, 'f', 'fql', 'show fully qualified labels', dest='showfql')
    addarg(argp, 'ndays', 'days of history (default 1)', nargs='?')
    args = optparse('taskday', argp, args)

    filterfn = fql_among_tags if args.showfql else label_from_tags
    ndays = args.ndays if args.ndays is not None else 1

    ago = datetime.now() - timedelta(days=int(ndays))
    tasks = timew.export(start_time=ago)

    labels = list(dict.fromkeys(reversed(
        [filterfn(task) for task in tasks])))

    if len(labels) and not tasks[-1].get('end'):
        labels[0] = f"*{labels[0]}"

    print(('\n' if args.column else '\x20').join(labels))

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

def _taskids(*args, onlyone=False, useid=True, useuuid=False):

    if onlyone:
        if len(args) != 1: bomb("should not use multiple args")
        tasks = [_taskone(*args)]
    else: tasks = _taskget(*args)

    taskids = [
        task['id']
        if task['id'] and not useuuid
        else task['uuid']
        for task in tasks]
    if taskids:
        if onlyone: return taskids[0]
        else: return [str(t) for t in taskids]

def _taskid(*args, **kwargs):
    if len(args) == 0:
        args, _ = _tasknow()
        args = [args]
    print(_taskids(*args, onlyone=True, **kwargs))

def taskid(*args):
    return _taskid(*args)

def taskuuid(*args):
    return _taskid(*args, useuuid=True)

def taskids(*args):
    print('\x20'.join(_taskids(*args)))

def taskuuids(*args):
    print('\x20'.join(_taskids(*args, useuuid=True)))


#

def taskget(*args):
    tasks = _taskget(*args)
    pp(tasks)

def _taskget(*args, **kwargs):

    ran = False
    tasks = set()

    # TaskWarrior.filter_tasks() returns a list of dicts (tasks) that will all
    # have a 'uuid' member, so we can add them in sets -- and thus deduplicate
    # results from multiple filters -- by hashing the dicts' uuids
    #
    class UUIDHashableDict(dict):
        def __hash__(self):
            return hash(self['uuid'])

    def taskfilter(filterdict):
        filterdict.update(dict(list(tagfilters.items()))) # add tags to filter
        return [UUIDHashableDict(d) for d in taskw.filter_tasks(filterdict)]

    argp = mkargs()
    addflag(argp, 'a', 'all', 'show most possible matches', dest='matchall')
    addflag(argp, 'z', 'zero', 'show non-existent uuid on zero matches')
    addargs(argp, 'taskargs', 'task lookup argument', default=[None])
    args = optparse('taskget', argp, args)
    multi = args.matchall

    taskargs = []
    tagfilters = {}; tags_yes = []; tags_no = []

    for taskarg in args.taskargs:
        for var, char in [(tags_yes, '+'), (tags_no, '-')]:
            if taskarg is not None and taskarg[0] == char:
                var.append(taskarg[1:]); break
        else: taskargs.append(taskarg)

    for var, key in [(tags_yes, 'tags.word'), (tags_no, 'tags.noword')]:
        if len(var): tagfilters.update({key: ','.join(var)})

    if not taskargs:
        # still need to enter taskargs loop so we need an item
        taskargs = [None]

    for taskarg in taskargs:

        # make sure loop runs at least once
        if ran and not multi: return tasks
        else: ran = True

        # all tasks if nothing specific requested
        if not taskarg:
            tasks.update(taskfilter({'status.any': ''}))
            break

        # taskid
        try:
            arg = int(taskarg)
            matches = taskfilter({'id': arg})
            if not matches:
                if not multi: bomb(f"failed to find integer task {arg}")
                else: continue
            if len(matches) != 1: bomb(f"integer id {arg} not unique")
            tasks.update(matches)
            if multi: continue
            else: break
        except ValueError: pass

        # taskuuid
        try:
            arg = uuid(taskarg)
            matches = taskfilter({'uuid': arg})
            if not matches:
                if not multi: bomb(f"failed to find task by uuid: {arg}")
                else: continue
            if len(matches) != 1: bomb(f"uuid lookup for {arg} not unique")
            tasks.update(matches)
            if multi: continue
            else: break
        except ValueError: pass

        # taskuuid-initial
        if set(taskarg).issubset(f"{hexdigits}-"):
            matches = taskfilter({'uuid': taskarg})
            if len(matches):
                tasks.update(matches)
                if multi: continue
                else: break

        # label
        if set(taskarg).issubset(f"{lowercase}{digits}-/"):
            if '/' in taskarg: f = _fqltask(taskarg) # fql
            else: f = {'label': taskarg} # label
            matches = taskfilter(f)
            if len(matches):
                tasks.update(matches)
                if not multi: break

        # for description, label, project try substring, then regex
        ftasks = set()
        for filt in [
            field + clause for clause in ['.contains', '.has']
            for field in ['description', 'label', 'project']
        ]:
            fftasks = taskfilter({filt: taskarg})
            if len(fftasks):
                ftasks.update(fftasks)
                if not multi: break
        tasks.update(ftasks)

        if len(tasks) and not multi:
            break

    if len(tasks) == 0:
        if args.zero: return [dict(id=0, uuid=dummy_match(0))]
        else: return []
    else: return tasks

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

    if debug:
        debugstr = ''
        for c, d in [('+', added), ('-', deleted), ('*', changed)]:
            for k, v in d.items():
                debugstr += f"{c}{k}:{v}\x20"
        dprint(f"delta: {debugstr}")

    #

    if 'start' in new:

        if 'start' not in old:
            _taskdo(new)

        timekeys = set(['start', 'end'])
        if set(old).intersection(timekeys):
            if set(changed).intersection(timekeys):
                attrlist = ",\x20".join(timekeys)
                bomb(f"timew propagation not implemented for {attrlist}")

    elif 'start' in old:

        if 'end' in new and 'end' not in old:
            _taskstop(new)

        if 'end' not in new:
            print("disallowing pause, use timewarrior until 'done'")
            exit(EXIT_FAILURE)

    if set(_timewtags(old)) != set(_timewtags(new)):
        if old.get('label'): # skip new taskadd with no label yet
            retimew(old, new)

    print(jdumps(new))


###

def main():

    if debug == 1: breakpoint()

    try: subprogram = globals()[invname]
    except (KeyError, TypeError):
        bomb(f"unimplemented command '{invname}'")

    try: instcnt = subprogram(*args)
    except BrokenPipeError:
        # todo: for some reason exit code doesn't work? always zero.
        # is it because we're already in exception handler?
        exit(EXIT_FAILURE)

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
    invname = invname.replace('-', '_').replace('.', '_') # for triggers
    argslast = list()
    argns = Namespace()
    args = argv[1:]

    taskw = TaskWarrior(marshal=True)
    timew = TimeWarrior()

    try: main()
    except BdbQuit: bomb("debug: stop")
