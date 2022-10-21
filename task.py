#!/usr/bin/env python3
"""
taskwarrior, timewarrior wrapper utilities for task and time management

  - taskdo: start in timew, all taskw fql elements and tags as timew tags
  - taskid: print exactly one matching id or completed uuid from taskget
  - taskids: print multiple matching ids from taskget algorithm
  - taskuuid: print exactly one matching ids from taskget or fail
  - taskuuids: print multiple matching uuids from taskget algorithm
  - taskget: search tasks as ids, uuids, labels or from descs, and print
  - tasknow: show last started task and whether it's active
  - taskday: show labels of tasks from last 24 hours
  - taskweek: show labels of tasks from last 168 hours (syn: 'tasks')
  - taskfql: print fully qualified label of uniquely matching task
  - taskfqls: print fully qualified labels of several matching tasks
  - taskstop: stop the current started task in timewarrior
  - taskline: show output suitable for conferring status to window manager
  - tasknotes: display formatted list of all the annotations of a task
  - timewtags: show all tags that a task would be assigned in timewarrior
  - on-modify.timew: hook runs on all task mods (via symlink in hooks/)

deps:
  - tasklib python library with patch #117 and #119
  - timew python library with patches 9-13

"""
__url__     = 'https://github.com/smemsh/.task/'
__author__  = 'Scott Mcdermott <scott@smemsh.net>'
__license__ = 'GPL-2.0'

import sys

from re import search
from os import getenv, EX_OK as EXIT_SUCCESS, EX_SOFTWARE as EXIT_FAILURE
from copy import copy
from uuid import UUID as uuid
from enum import IntEnum as enum
from json import loads as jloads, dumps as jdumps
from pprint import pp
from select import select
from string import digits, hexdigits, ascii_lowercase as lowercase
from os.path import basename
from datetime import datetime, timedelta, timezone
from textwrap import fill
from argparse import ArgumentParser, RawTextHelpFormatter, Namespace, SUPPRESS
from subprocess import check_output

from tasklib import TaskWarrior, Task
from timew import TimeWarrior
from timew.exceptions import TimeWarriorError

###

def err(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

def bomb(*args, **kwargs):
    err(*args, **kwargs)
    sys.exit(EXIT_FAILURE)

def dprint(*args, **kwargs):
    if not debug: return
    err('debug:', *args, **kwargs)

def exe(cmd):
    return check_output(cmd.split()).splitlines()

def getitem(obj, member):
    try: return obj[member]
    except KeyError: return None

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

def mkargs():
    return ArgumentParser(
        prog            = invname,
        description     = __doc__.strip(),
        allow_abbrev    = False,
        formatter_class = RawTextHelpFormatter)

# allow cumulative option parsing.  the resulting Namespace() will be a
# union of all flag/option processing with later calls to addfoo()
# overriding earlier-specified attribute values with the same name
# (TODO: wrong, actually later *new* ones can join, but overrides won't
# occur, see comments when a Namespace is given as arg)
#
def optparse(name, argp, *args):

    global argns
    global argslast

    nsarg = None
    if args and isinstance(args[0], Namespace):
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
    if argslast: err(f"skipping unknown args: {argslast}")

    return argns

###

def failuuid(maskenum):
    return uuid(int=((1 << getattr(FailMask, maskenum)) - 1))

def isfailuuid(arg):
    if type(arg) is str: arg = uuid(arg)
    if type(arg) is not uuid: bomb("isfailuuid")
    return arg.int & FAILUUID.int == FAILUUID.int

def dummy_match(n):
    if n == 0: dummy = str(failuuid('NONE'))
    elif n > 1: dummy = str(failuuid('MULTI'))
    elif n == 1: dummy = str(failuuid('WRONG'))
    else: bomb("n < 0 should never happen")
    return dummy

def dummy_task(n):
    return {'id': 0, 'uuid': dummy_match(n)}

# fails if not exactly one match from lookup, or the lookup
# result is a failure
#
def __taskone(*args, **kwargs):
    tasks = _taskget(*args, **kwargs)
    ntasks = len(tasks)
    success = False
    onetask = tasks.pop() if tasks else {}
    if ntasks == 1:
        if not isfailuuid(onetask['uuid']):
            success = True # only possible success case
    elif ntasks > 1:
        onetask = dummy_task(ntasks) if argns.zero else {}
    return success, onetask

def _taskone(*args, **kwargs):
    abort = kwargs.get('abort', True)
    success, match = __taskone(*args, **kwargs)
    if not success and abort:
        m = getitem(match, 'uuid')
        if m: print(m)
        sys.exit(EXIT_FAILURE)
    return match

#

def __taskfql(task, labelonly=False):
    prj = getitem(task, 'project')
    label = getitem(task, 'label')
    if not prj or not label: return # taskadd or nonconforming
    if labelonly: return label
    return f"{prj.replace('.', '/')}/{label}"

def _taskfql(*args, **kwargs):
    task = _taskone(*args, **kwargs)
    return __taskfql(task, **kwargs)

def _taskfqls(*args, **kwargs):
    tasks = _taskget(*args, **kwargs)
    if not tasks: return []
    else: return [__taskfql(t, **kwargs) for t in tasks]

def taskfql(*args, **kwargs):
    print(_taskfql(*args, **kwargs))

def taskfqls(*args, **kwargs):
    for t in _taskfqls(*args, **kwargs):
        print(t or '')

def tasklabels(*args):
    taskfqls(*args, labelonly=True)

def tasklabel(*args):
    taskfql(*args, labelonly=True)

#

def _timewtags(task):

    tags = []

    if isinstance(task, str): fql = task
    elif isinstance(task, dict) or isinstance(task, Task):
        fql = __taskfql(task)
    else: bomb("unsupported type for _timewtags() arg")

    if fql: fqlsegs = fql.split('/')
    else: fqlsegs = []
    nsegs = len(fqlsegs)

    for i in range(1, nsegs + 1):
        tags.append('/'.join(fqlsegs[0:i]) + ('/' if i < nsegs else ''))

    tasktags = getitem(task, 'tags')
    if (tasktags):
        tags.extend([f"+{t}" for t in tasktags])

    return tags

def timewtags(*args):
    task = _taskone(*args, idonly=True, zero=False, exact=True)
    print("\x20".join(_timewtags(task)))

#

# arg: lookup task, switch to that one if not already
# noarg: start last task (timew continue)
#
def taskdo(*args):
    # there's exactly one match if _taskone() returns
    task = _taskone(*args, matchone=True, idonly=True, abort=True)
    return _taskdo(task)

# if called from the modify hook (only other entrance besides taskdo()),
# arg is the new task struct.  otherwise it's the one retrieved by
# _taskone() given the cli argument, and it already failed if invalid
#
def _taskdo(task):

    if getitem(task, 'end'): bomb("cannot proceed on ended task")
    if not getitem(task, 'start'): bomb("do initial start in taskwarrior")

    # we must do our own _tasknow() even if the task we got came
    # from noargs _taskget() (which calls _tasknow()) since we
    # do not know if passed-in task is current task TODO refactor
    #
    curfql, active = _tasknow()
    rqfql = __taskfql(task)

    if curfql == rqfql:
        if active:
            print(f"{curfql} already")
            return
        stdout, stderr = timew.cont(1)
    else:
        tags = _timewtags(task)
        tagstr = '\x20'.join(tags)
        print("timewtags:", tagstr)
        stdout, stderr = timew.start(tags=tags)

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

    global nowcache # only run once, return cached value thereafter
    cachevals = ['fql', 'active']

    if not nowcache:
        timedata = timew.export()
        try:
            curtask = next(filter(lambda task: task['id'] == 1, timedata))
            fql = next(filter(isfql, curtask.get('tags')))
        except:
            bomb("task @1 must exist and have an fql tag")
        active = not 'end' in curtask

        for v in cachevals: nowcache[v] = copy(vars()[v])

    return (nowcache[v] for v in cachevals)


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
            output += "\x20"
            output += 'started' if active else 'stopped'
        print(output)

#

def taskline():
    nowtimefmt = datetime.now().strftime("%Y%m%d%H%M%S")
    fql, active = _tasknow()
    active = '*' if active else '-'
    print(fql, active, nowtimefmt)

def tasknotes(*args):

    headchar = '='
    outputs = []
    interactive = sys.stdout.isatty()

    colordict = {
        'YELLOW':   "93",
        'CYAN':     "96",
        'MAGENTA':  "95",
        'GREEN':    "92",
        'RED':      "91",
        'WHITE':    "97",
        'CYBLUE':   "96;44",
        'WHIGREY':  "100;97;3",
        'INVERT':   "100",
        'UNDERLN':  "4",
        'DEFAULT':  "0",
    }

    class C:
        for k, v in colordict.items():
            vars()[k] = f"\033[{v}m" if interactive else ''

    def fqlcolor(fql):
        output = ''
        segments = fql[1:].split('/')
        label = segments.pop(-1)
        sep = f"{C.GREEN}/{C.DEFAULT}"
        for s in segments:
            output += sep
            output += f"{C.WHITE}{s}{C.DEFAULT}"
        output += sep
        output += f"{C.YELLOW}{label}{C.DEFAULT}"
        return output

    tasks = _taskget(*args)
    for task in tasks:
        output = ""
        desc = task['description']
        notes = list(map(str, task['annotations']))
        label = task['label']
        project = task['project']
        fqlabel = f"/{project.replace('.', '/')}/{label}\n"
        output += fqlcolor(fqlabel)
        fillargs = {
            'initial_indent': f"{C.MAGENTA}-\x20{C.DEFAULT}",
            'subsequent_indent': "\x20\x20",
            'drop_whitespace': True,
            'break_on_hyphens': False,
            'break_long_words': False,
            'replace_whitespace': False,
            'width': 79,
        }
        colordesc = f"{C.WHIGREY}{desc}{C.DEFAULT}"
        if notes:
            output += f"{C.RED}{headchar}{C.DEFAULT}\x20{colordesc}\n"
            output += "\n".join([fill(note, **fillargs) for note in notes])
        else:
            output += colordesc
        outputs += [output]

    print("\n\n".join(outputs))

#

def tasks(*args): taskweek(*args)
def taskweek(*args): taskday(*args, '7')
def taskmonth(*args): taskday(*args, '30')
def taskyear(*args): taskday(*args, '365')
def taskday(*args):

    statmap = {
        'completed': '-',
        'started': '', # pseudo-status we inject for started
        'pending': '+', # real status we use for not yet started
        'deleted': '!',
        'virtual': '^', # tasks in timew but not taskw
        'unknown': '?',
        'waiting': '&',
        'waited': '#',
    }
    charmap = {v: k for k, v in statmap.items()}

    def select_with_status(fql):
        status = None
        success, task = __taskone(fql, idonly=True, held=args.held,
                                  blocked=args.blocked)
        if success:
            waitend = getitem(task, 'wait')
            if waitend:
                if waitend < datetime.now(waitend.tzinfo):
                    taskstat = 'waited'
                else: taskstat = 'waiting'
            else:
                taskstat = task['status']
                taskstart = task['start']
            if not taskstat:
                bomb("no status: ", task, sep='\n')
            if taskstat in statmap:
                if taskstat == 'pending' and taskstart:
                    taskstat = 'started'
            else:
                taskstat = 'unknown'
        else:
            taskstat = 'virtual' # likely a timew-only tag
        status = taskstat
        retchar = statmap[taskstat]
        return status, statmap[taskstat]

    # selectfn
    def fql_among_tags(task, statuses):
        selected = list(filter(isfql, task['tags']))
        if len(selected) != 1:
            bomb("selected more than one fql tag for task")
        fql = selected[0]
        status, stchar = select_with_status(fql)
        if status not in statuses: fql = None
        return fql, stchar

    # selectfn
    def label_from_tags(task, statuses):
        fql, stchar = fql_among_tags(task, statuses)
        if fql: fql = fql.split('/')[-1]
        return fql, stchar

    argp = mkargs()
    addflag(argp, 'f', 'fql', 'show fully qualified labels')
    addflag(argp, 'd', 'done', 'include completed tasks')
    addflag(argp, 'H', 'held', 'only match waiting tasks')
    addflag(argp, 't', 'this', 'this-dwmy instead of 24h, 7d, 30d, 365d')
    addflag(argp, 's', 'status', 'show status characters')
    addflag(argp, '1', 'column', 'delimit by lines instead of spaces')
    addflag(argp, 'b', 'blocked', 'only show blocked, normally not shown')
    addflag(argp, 'T', 'alltasks', 'pending, completed and timew-only')
    addflag(argp, 'i', 'timetasks', 'include timew-only tasks')
    addarg (argp, 'ndays', 'days of history (default 1)', nargs='?')
    args = optparse('taskday', argp, args)

    selectfn = fql_among_tags if args.fql else label_from_tags

    if args.held:
        statuses = set(['waiting', 'waited'])
        if args.alltasks or args.timetasks:
            bomb("held tasks should be selected alone")
    else:
        statuses = set(['pending', 'started'])
        if args.alltasks: args.timetasks = True; args.done = True
        if args.timetasks: statuses.update([None]) # timew-only task
        if args.done: statuses.update(['completed'])

    ndays = int(args.ndays if args.ndays is not None else '1')
    if args.this:
        now = datetime.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if   ndays <=   0: bomb("must be positive ndays")
        if   ndays ==   7: start = today - timedelta(days=now.weekday())
        elif ndays ==  30: start = today.replace(day=1)
        elif ndays == 365: start = today.replace(month=1, day=1)
        else: bomb("--this ndays must be aligned")
    else: start = datetime.now() - timedelta(days=ndays)
    tasks = timew.export(start_time=start)

    # create list of (fql, stchr) pairs, filtering None fqls
    selected = [selectfn(task, statuses) for task in tasks]
    curchar = selected[-1][1] # stash status of current task
    filtered = list(filter(lambda f: f[0], selected))
    outputs = list(dict.fromkeys(reversed(filtered))) # deduplicate

    if args.status:
        outputs = [''.join(o) for o in outputs]
        if outputs and not tasks[-1].get('end'):
            achar = '%' if charmap[curchar] == "virtual" else '*'
            outputs[0] = f"{achar}{outputs[0]}"
    else:
        outputs = [o[0] for o in outputs]

    if outputs:
        print(('\n' if args.column else '\x20').join(outputs))

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

def _taskids(*args, onlyone=False, useid=True, useuuid=False, idonly=False):

    matchall = False if onlyone else True
    abort = False if onlyone else True

    tasks = _taskget(*args, idonly=idonly, matchall=matchall, abort=abort)
    taskids = [
        task['id']
        if task['id'] and not useuuid
        else task['uuid']
        for task in tasks]
    if taskids:
        if onlyone: return taskids[0]
        else: return [str(t) for t in taskids]
    else:
        dummy = dummy_match(0)
        return dummy if onlyone else [dummy]

def _taskid(*args, **kwargs):
    return _taskids(*args, onlyone=True, idonly=True, **kwargs)

def taskid(*args):
    print(_taskid(*args))

def taskuuid(*args):
    print(_taskid(*args, useuuid=True))

def taskids(*args):
    print('\x20'.join(_taskids(*args)))

def taskuuids(*args):
    print('\x20'.join(_taskids(*args, useuuid=True)))


#

def taskget(*args):
    tasks = _taskget(*args)
    pp([t._data for t in tasks])

def _taskget(*args, **kwargs):

    global getcache

    ran = False
    tasks = set()
    firstmatch = None

    def cache_index(args):
        return hash(tuple(args))

    def cache_insert(args, value):
        global getcache
        hashedargs = cache_index(args)
        # copy required for proper function (todo: why?)
        getcache.update({hashedargs: copy(value)})
        return value

    def cache_get(args):
        global getcache
        hashedargs = cache_index(args)
        # copy required for proper function (todo: why?)
        got = copy(getcache.get(hashedargs))
        return got

    # TaskWarrior.filter_tasks() returns a list of dicts (tasks) that will all
    # have a 'uuid' member, so we can add them in sets -- and thus deduplicate
    # results from multiple filters -- by hashing the dicts' uuids
    #
    # UPDATE: taskfilter doesn't need to use this class anymore because it
    # already provides __hash__() method for objects it contains which
    # works off uuid, and provides set methods, so we can treat taskw.filter()
    # object the same as a set of tasklib.task.Tasks (ie dict-like) objects,
    # that all have uuid member and are __hash__-able thereby
    #
    class UUIDHashableDict(dict):
        def __hash__(self):
            return hash(self['uuid'])

    def taskfilter(filterdict):
        if held: filterdict.update({'wait__after': 'now'})
        if blocked == True: filterwords = ['+BLOCKED']
        elif blocked == False: filterwords = ['-BLOCKED']
        else: filterwords = [] # None
        filterdict.update(dict(list(tagfilters.items()))) # add tags to filter
        filtered = taskw.filter(*filterwords, **filterdict)
        #filtered = [f._data for f in filtered]
        #filtered = [UUIDHashableDict(d) for d in filtered]
        return filtered

    def runfilters(filters):
        nonlocal matches
        for f in filters:
            matches = taskfilter(f)
            if matches:
                taskupdate(matches)
                if not multi: return

    def taskupdate(matches):
        nonlocal firstmatch
        nonlocal tasks
        # save the first match because if we got --one we will be
        # printing it, and often the first one found following
        # taskget search flow is the one we want anyways
        if firstmatch is None:
            # if an id-types match this will be a one-match list anyways
            firstmatch = list(matches)[0] if matches else []
        tasks.update(matches)

    def fromargs(name, default, *args):

        # let caller specify kwargs vs args precedence by parameter order
        def bytype(arg, name):
            if isinstance(arg, Namespace): return bool(getattr(arg, name))
            elif isinstance(arg, dict): return bool(arg[name])
            else: bomb("fromargs: bytype: unknown type")

        for argset in args:
            if name in argset:
                return bytype(argset, name)

        return default

    # try out match as an id and insert into caller's 'matches'
    # dictionary if found.  returns whether to loop again (True), stop
    # (False), or fallthrough (None).
    #
    def update_matches(idtype, arg):
        nonlocal matches
        matches = taskfilter({idtype: arg})
        if matches:
            if len(matches) != 1:
                bomb(f"{idtype} lookup for {arg} not unique")
            taskupdate(matches)
            if multi: return True
            else: return False
        if not multi:
            bomb(f"failed to resolve id: {arg}")
        elif not idstrings: return True

    ##

    argp = mkargs()
    addflag(argp, 'a', 'all', 'show all matches', default=True, dest='matchall')
    addflag(argp, 'o', 'one', 'only show first match', dest='matchone')
    addflag(argp, 'z', 'zero', 'show non-existent uuid on zero matches')
    addflag(argp, 'x', 'exact', 'exact (not substring) project/label match')
    addflag(argp, 'n', 'idonly', 'just fql, label, id, uuid', default=SUPPRESS)
    addflag(argp, 'i', 'idstrings', 'match ids in strings if no id match')
    addargs(argp, 'taskargs', 'task lookup argument', default=[])
    args = optparse('taskget', argp, args)

    multi = False \
        if fromargs('matchone', False, args, kwargs) \
        else fromargs('matchall', True, args, kwargs)
    idonly = True \
        if not args.taskargs \
        else fromargs('idonly', False, args, kwargs)
        # ^^^ if no args, we will just tasknow(), so skip extra checks

    held = fromargs('held', False, kwargs)
    blocked = fromargs('blocked', None, kwargs)

    zero = fromargs('zero', False, args)
    exact = fromargs('exact', False, kwargs, args)
    idstrings = fromargs('idstrings', False, args)

    taskargs = []
    tagfilters = {}; tags_yes = []; tags_no = []

    for taskarg in args.taskargs:
        for var, char in [(tags_yes, '+'), (tags_no, '-')]:
            if taskarg is not None and taskarg[0] == char:
                var.append(taskarg[1:]); break
        else: taskargs.append(taskarg)

    for var, key in [(tags_yes, 'tags__word'), (tags_no, 'tags__noword')]:
        if var: tagfilters.update({key: ','.join(var)})

    taskkey = taskargs + list(tagfilters.items())

    cacheval = cache_get(taskkey)
    if cacheval is not None:
        return cacheval

    if not taskargs:
        # default to the current task
        t, _ = _tasknow()
        taskargs = [t]

    for taskarg in taskargs:

        # more taskargs, but we already matched and no more were requested
        if ran and not multi: break
        else: ran = True

        # should not happen anymore TODO delete after a while
        if not taskarg:
            bomb("impossible: encountered pruned codepath: empty arg")
            # TODO: implement flag where we dump all tasks if
            # nothing specific requested, see task 3c01a357
            taskupdate(taskfilter({'status__any': ''}))
            break

        # taskid
        try:
            idkey = 'id'
            arg = int(taskarg)
            matches = taskfilter({idkey: arg})
            loopagain = update_matches(idkey, arg)
            if loopagain is not None:
                if loopagain: continue
                else: break
        except ValueError: pass

        # taskuuid
        try:
            idkey = 'uuid'
            arg = uuid(taskarg)
            loopagain = update_matches(idkey, arg)
            if loopagain is not None:
                if loopagain: continue
                else: break
        except ValueError: pass

        # taskuuid-initial
        if set(taskarg).issubset(f"{hexdigits}-"):
            idkey = 'uuid'
            arg = taskarg
            loopagain = update_matches(idkey, arg)
            if loopagain is not None:
                if loopagain: continue
                else: break

        # label or fql
        if set(taskarg).issubset(f"{lowercase}{digits}-/"):

            filters = []
            matchop = 'is' if exact else 'has'
            if '/' in taskarg:
                # fully/qualified/label
                segs = taskarg.split('/')
                project = '.'.join(segs[0:-1])
                label = segs[-1]
                filters += [{f"project__{matchop}": project,
                             f"label__{matchop}": label}]
                # fully/qualified
                if not exact:
                    filters += [{f"project__{matchop}":
                                taskarg.replace('/', '.')}]
            else:
                # label
                filters += [{f"label__{matchop}": taskarg}]

            runfilters(filters)
            if matches and not multi: break

        # don't look beyond fql, label, id, uuid if requested
        if idonly:
            if multi: continue
            else: break

        # for description, label, project try substring, then regex
        ftasks = set()
        for filt in [
            field + clause for clause in ['__has']
            for field in ['description', 'label', 'project']
        ]:
            fftasks = taskfilter({filt: taskarg})
            if fftasks:
                ftasks.update(fftasks)
                if not multi: break
        taskupdate(ftasks)

        if tasks and not multi:
            break

    taskn = len(tasks)
    if taskn == 0:
        if zero: items = [dummy_task(0)]
        else: items = []
    else:
        if taskn > 1 and not multi:
            # first match typically best if one result requested
            tasks = [firstmatch]
        items = tasks

    return cache_insert(taskkey, items)

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

    old = jloads(inlines[0])
    new = jloads(inlines[1])
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
            sys.exit(EXIT_FAILURE)

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

    try: ret = subprogram(*args)
    except BrokenPipeError:
        # todo: for some reason exit code doesn't work? always zero.
        # is it because we're already in exception handler?
        ret = EXIT_FAILURE
    sys.exit(ret or EXIT_SUCCESS)

###

if __name__ == "__main__":

    if sys.hexversion < 0x03090000:
        bomb("minimum python 3.9")

    invname = basename(sys.argv[0])
    replaced = invname.replace('-', '_').replace('.', '_')
    triggered = invname != replaced # ie for on-modify
    invname = replaced

    if triggered and select([sys.stdin], [], [], 0)[0]:
        # save stdin if given, pdb needs stdio fds itself
        inlines = sys.stdin.readlines()
        try: sys.stdin = open('/dev/tty')
        except: pass # no ctty, but then pdb would not be in use

    from bdb import BdbQuit
    debug = int(getenv('DEBUG') or 0)
    if debug:
        from pprint import pp
        err('debug: enabled')

    argslast = list()
    argns = Namespace()
    args = sys.argv[1:]

    getcache = {}
    nowcache = {}

    FAILBASE = 124
    failures = ['NONE', 'WRONG', 'MULTI']
    FailMask = enum('FailMask', failures, start=FAILBASE)
    FAILUUID = failuuid(FailMask(FAILBASE).name)

    taskw = TaskWarrior().tasks
    timew = TimeWarrior()

    try: main()
    except BdbQuit: bomb("debug: stop")
