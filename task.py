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
  - taskw python library with patch #151 and #159
  - timew python library with patches 9-13

"""
__url__     = 'https://github.com/smemsh/.task/'
__author__  = 'Scott Mcdermott <scott@smemsh.net>'
__license__ = 'GPL-2.0'

from re import search
from os import getenv, EX_OK as EXIT_SUCCESS, EX_SOFTWARE as EXIT_FAILURE
from sys import argv, stdin, stdout, stderr, exit
from copy import copy
from uuid import UUID as uuid
from enum import IntEnum as enum
from json import loads as jloads, dumps as jdumps
from pprint import pp
from string import digits, hexdigits, ascii_lowercase as lowercase
from os.path import basename
from datetime import datetime, timedelta
from textwrap import fill
from argparse import ArgumentParser, RawTextHelpFormatter, Namespace, SUPPRESS
from subprocess import check_output

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

def failuuid(maskenum):
    return uuid(int=((1 << getattr(FailMask, maskenum)) - 1))

def isfailuuid(uuidstr):
    return uuid(uuidstr) >= FAILUUID

def dummy_match(n):
    if n == 0: dummy = str(failuuid('NONE'))
    elif n > 1: dummy = str(failuuid('MULTI'))
    else: bomb("n less than 0??? aborting")
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
    return success, onetask

def _taskone(*args, **kwargs):
    abort = kwargs.get('abort', True)
    success, match = __taskone(*args, **kwargs)
    if not success and abort:
        m = match.get('uuid')
        if m: print(m)
        exit(EXIT_FAILURE)
    return match

#

def __taskfql(task):
    prj = task.get('project')
    try:
        if prj: return f"{prj.replace('.', '/')}/{task['label']}"
    except KeyError:
        bomb("at least one task does not have a label")

def _taskfql(*args):
    task = _taskone(*args)
    return __taskfql(task)

def _taskfqls(*args):
    tasks = _taskget(*args)
    if not tasks: return []
    else: return [__taskfql(t) for t in tasks]

def taskfql(*args):
    print(_taskfql(*args))

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
def taskdo(*args):
    # there's exactly one match if _taskone() returns
    task = _taskone(*args, matchone=True, idonly=True, abort=True)
    return _taskdo(task)

# if called from the modify hook (only other entrance besides taskdo()),
# arg is the new task struct.  otherwise it's the one retrieved by
# _taskone() given the cli argument, and it already failed if invalid
#
def _taskdo(task):

    if 'end' in task: bomb("cannot proceed on ended task")
    if 'start' not in task: bomb("do initial start in taskwarrior")

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

    tasks = _taskget(*args)
    for task in tasks:
        output = ""
        desc = task['description']
        notes = task.get('annotations')
        label = task.get('label')
        project = task.get('project')
        output += f"/{project.replace('.', '/')}/{label}\n"
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
            output += f"{headchar} {desc}\n"
            output += "\n".join([fill(note, **fillargs) for note in notes])
        else:
            output += desc
        outputs += [output]

    print(("\n\n" if len(outputs) > 1 else "\n").join(outputs))

#

def tasks(*args): taskweek(*args)
def taskweek(*args): taskday(*args, '7')
def taskmonth(*args): taskday(*args, '30')
def taskday(*args):

    def get_status_char(fql, status):
        if not status:
            return ''
        statmap = {
            'completed': '-',
            'started': '', # pseudo-status we inject for started
            'pending': '+', # real status we use for not yet started
            'deleted': '!',
        }
        success, task = __taskone(fql, idonly=True)
        if success:
            taskstat = task.get('status')
            taskstart = task.get('start')
        else:
            return '^' # not "real" task, ie timew tag not backed by taskw
        if not taskstat:
            bomb("no status: ", task, sep='\n')
        if taskstat in statmap:
            if taskstat == 'pending':
                if taskstart:
                    taskstat = 'started' # synthetic status we inject
            return statmap[taskstat]
        else: return '?'

    def fql_among_tags(task, status=False):
        filtered = list(filter(isfql, task['tags']))
        if len(filtered) != 1:
            bomb("filtered more than one fql tag for task")
        fql = filtered[0]
        stchar = get_status_char(fql, status)
        return f"{fql}{stchar}"

    def label_from_tags(task, status=False):
        fql = fql_among_tags(task, status=status)
        label = fql.split('/')[-1]
        return label

    argp = mkargs()
    addflag(argp, '1', 'column', 'delimit by lines instead of spaces')
    addflag(argp, 's', 'status', 'show status characters')
    addflag(argp, 'f', 'fql', 'show fully qualified labels')
    addarg(argp, 'ndays', 'days of history (default 1)', nargs='?')
    args = optparse('taskday', argp, args)

    filterfn = fql_among_tags if args.fql else label_from_tags
    ndays = args.ndays if args.ndays is not None else 1

    ago = datetime.now() - timedelta(days=int(ndays))
    tasks = timew.export(start_time=ago)

    labels = list(dict.fromkeys(reversed(
        [filterfn(task, status=args.status) for task in tasks])))

    if len(labels) and not tasks[-1].get('end') and args.status:
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
    pp(tasks)

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
    class UUIDHashableDict(dict):
        def __hash__(self):
            return hash(self['uuid'])

    def taskfilter(filterdict):
        filterdict.update(dict(list(tagfilters.items()))) # add tags to filter
        return [UUIDHashableDict(d) for d in taskw.filter_tasks(filterdict)]

    def taskupdate(matches):
        nonlocal firstmatch
        nonlocal tasks
        # save the first match because if we got --one we will be
        # printing it, and often the first one found following
        # taskget search flow is the one we want anyways
        if firstmatch is None:
            # if an id-types match this will be a one-match list anyways
            firstmatch = list(matches)[0] if len(matches) else []
        tasks.update(matches)

    def fromargs(name, args1, args2, default):

        # let caller specify kwargs vs args precedence by parameter order
        def bytype(arg, name):
            if isinstance(arg, Namespace): return bool(getattr(arg, name))
            elif isinstance(arg, dict): return bool(arg[name])
            else: bomb("fromargs: bytype: unknown type")

        for argset in [args1, args2]:
            if name in argset:
                return bytype(argset, name)

        return default

    ##

    argp = mkargs()
    addflag(argp, 'a', 'all', 'show all matches', default=True, dest='matchall')
    addflag(argp, 'o', 'one', 'only show first match', dest='matchone')
    addflag(argp, 'z', 'zero', 'show non-existent uuid on zero matches')
    addflag(argp, 'x', 'exact', 'exact (not substring) project/label match')
    addflag(argp, 'n', 'idonly', 'just fql, label, id, uuid', default=SUPPRESS)
    addargs(argp, 'taskargs', 'task lookup argument', default=[])
    args = optparse('taskget', argp, args)

    multi = False \
        if fromargs('matchone', args, kwargs, False) \
        else fromargs('matchall', args, kwargs, True)
    idonly = True \
        if not args.taskargs \
        else fromargs('idonly', args, kwargs, False)
        # ^^^ if no args, we will just tasknow(), so skip extra checks
    zero = fromargs('zero', args, {}, False)
    exact = fromargs('exact', args, {}, False)

    taskargs = []
    tagfilters = {}; tags_yes = []; tags_no = []

    for taskarg in args.taskargs:
        for var, char in [(tags_yes, '+'), (tags_no, '-')]:
            if taskarg is not None and taskarg[0] == char:
                var.append(taskarg[1:]); break
        else: taskargs.append(taskarg)

    for var, key in [(tags_yes, 'tags.word'), (tags_no, 'tags.noword')]:
        if len(var): tagfilters.update({key: ','.join(var)})

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
            taskupdate(taskfilter({'status.any': ''}))
            break

        # taskid
        try:
            arg = int(taskarg)
            matches = taskfilter({'id': arg})
            if not matches:
                if not multi: bomb(f"failed to find integer task {arg}")
                else: continue
            if len(matches) != 1: bomb(f"integer id {arg} not unique")
            taskupdate(matches)
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
            taskupdate(matches)
            if multi: continue
            else: break
        except ValueError: pass

        # taskuuid-initial
        if set(taskarg).issubset(f"{hexdigits}-"):
            matches = taskfilter({'uuid': taskarg})
            if len(matches):
                taskupdate(matches)
                if multi: continue
                else: break

        # label or fql
        if set(taskarg).issubset(f"{lowercase}{digits}-/"):
            matchop = 'is' if exact else 'has'
            if '/' in taskarg:
                segs = taskarg.split('/')
                project = '.'.join(segs[0:-1])
                label = segs[-1]
                f = {f"project.{matchop}": project,
                     f"label.{matchop}": label}
            else:
                f = {f"label.{matchop}": taskarg}
            matches = taskfilter(f)
            if len(matches):
                taskupdate(matches)
                if not multi: break

        # don't look beyond fql, label, id, uuid if requested
        if idonly:
            if multi: continue
            else: break

        # for description, label, project try substring, then regex
        ftasks = set()
        for filt in [
            field + clause for clause in ['.has']
            for field in ['description', 'label', 'project']
        ]:
            fftasks = taskfilter({filt: taskarg})
            if len(fftasks):
                ftasks.update(fftasks)
                if not multi: break
        taskupdate(ftasks)

        if len(tasks) and not multi:
            break

    if len(tasks) == 0:
        if zero:
            dummy = [dummy_task(0)]
            cached = cache_insert(taskkey, dummy)
            return cached
        else:
            noresult = []
            cached = cache_insert(taskkey, noresult)
            return cached
    else:
        if len(tasks) > 1 and not multi:
            # tasks are in a set, which doesn't have order.  when we can
            # only return one result, we want the first match found
            # because it's typically right, so we have saved it
            #
            tasks = [firstmatch]

        cached = cache_insert(taskkey, tasks)
        return cached

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

    getcache = {}
    nowcache = {}

    FAILBASE = 124
    failures = ['NONE', 'MULTI']
    FailMask = enum('', failures, start=FAILBASE)
    FAILUUID = failuuid(FailMask(FAILBASE).name)

    taskw = TaskWarrior(marshal=True)
    timew = TimeWarrior()

    try: main()
    except BdbQuit: bomb("debug: stop")
