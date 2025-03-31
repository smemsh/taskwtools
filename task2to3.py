#!/usr/bin/env python3
"""
task2to3:
  taskwarrior v2 to v3 import via undo.data, preserving history

usage:
  task2to3.py < undo.data

desc:
  - imports all records from an undo.data log on stdin, into taskwarrior3
  - does a full read of the undo data first to ensure no parse errors
  - for each record, exec "faketime <time> task3 import", task json on stdin

records:
  - input records must be valid utf8 (moreutils "isutf8 -v" is helpful here)
  - each record has either two or three lines separated by '\n---\n'
  - each record's first line is always 'time <time_t>' (unix time of event)
  - optional line follows: 'old [<task_ff4>]' (line not present if new task)
  - last line always looks like 'new [<task_ff4>]' (new or modified task)
  - all brackets in the task data are encoded as "&open;" and "&close;"
  - FF4 record format documentation would be in {TF2,Task}.cpp prior to v3

note:
  - requires 'task3' executable in PATH (see 'TASKCMD')
  - requires 'faketime' executable in PATH
  - only tested on my own data, with linux taskwarrior-3.4.1

"""
__url__     = 'https://github.com/smemsh/taskwtools/'
__author__  = 'Scott Mcdermott <scott@smemsh.net>'
__license__ = 'GPL-2.0'

from sys import exit, hexversion
if hexversion < 0x030a00f0: exit("minpython: %s" % hexversion)

from re import findall, finditer
from sys import stdin, stdout, stderr
from json import loads as jsonload, dumps as jsonstore
from time import localtime, strftime
from select import select
from shutil import which
from traceback import print_exc
from subprocess import STDOUT, check_output as cmd

from os import (
    getenv, unsetenv,
    isatty, dup,
    close as osclose,
    EX_OK as EXIT_SUCCESS,
    EX_SOFTWARE as EXIT_FAILURE,
)

###

TASKCMD = "task3"

###

def err(*args, **kwargs):
    print(*args, file=stderr, **kwargs)

def bomb(*args, **kwargs):
    err(*args, **kwargs)
    exit(EXIT_FAILURE)

def lerr(*args, **kwargs):
    global errs
    err(*(tuple(['line', f"{str(linenum)}:"]) + args), **kwargs)
    errs += 1

###

# see TW github issue 3286
def fix_utf16be_in_utf8(line):

    offset = 0
    utf16be_regex = rb'\xd8[\x00-\xff]\xdd[\x00-\xff]'

    try:
        decoded = line.decode('utf-8', errors='ignore')
        matches = finditer(utf16be_regex, line)
        recoded = bytearray()
        segments = [
            decoded[offset:m.start()].encode('utf-8') +
            m.group(0).decode('utf-16-be').encode('utf-8')
            for m in matches
        ]
        recoded.extend(b''.join(segments))
        recoded.extend(decoded[offset:].encode('utf-8'))
        return recoded.decode('utf-8')

    except UnicodeDecodeError:
        return False


def getline():

    global linenum

    try:
        linenum += 1
        line = next(infile)
        line = line.decode()

    except UnicodeDecodeError:
        if not (line := fix_utf16be_in_utf8(line)):
            lerr("decoding error, skipping")
            line = "\n"

    except StopIteration:
        line = ""

    return line

###

def get_tasks():

    global nrecords

    time_t = 0
    tasks = []
    times = []
    skipping = False

    if debug == 1:
        breakpoint()

    while line := getline():

        if line == "\n":
            continue

        if line == "---\n":
            nrecords += 1
            if skipping: skipping = False
            elif 'taskdict' in vars(): del taskdict  # record complete
            else: lerr("ended unfinished, skipping")
            continue

        if skipping:
            continue

        if line.startswith("time\x20"):
            old_time_t = time_t
            time_t = int(line.split()[-1])
            if old_time_t > time_t:
                lerr('non-sequential record, skipping')
                skipping = True
                time_t = old_time_t
                continue
            line = getline()
            if line.startswith("old\x20"):
                line = getline()  # ignore old version
            if not line.startswith("new\x20"):
                if line != "":
                    lerr('should be a "new", skipping')
                skipping = True
                continue
        else:
            lerr('should be a "time", skipping')
            skipping = True
            continue

        if line[4] != '[' or line[-2] != ']':  # -1 is "\n"
            lerr('malformed, skipping')
            skipping = True
            continue

        # parse out line data by stripping line type keyword, delimiter
        # brackets, and decoding any inline brackets ala TF2::decode()
        #
        linedata = line[5:-2]  # "new [<linedata>]\n"
        for replace in [('&open;', '['), ('&close;', ']')]:
            linedata = str.replace(linedata, replace[0], replace[1])

        # linedata is a series of 'key:"value"' pairs where any '"'
        # inside quotes must be preceded by backslash, so value strings
        # go until the next quote that isn't preceded by a backslash
        #
        keypairs = findall(r'\s*([^:]+):"(.*?)(?<!\\)"', linedata)
        taskdict = dict([(k, jsonload(f'"{v}"')) for k, v in keypairs])

        # 'tags' and 'depends' have two variants seen in the undo file,
        # one a comma separated list and the other multiple prefixed
        # keys, sometimes both in the same record, so we make a union
        #
        for field in [('depends', 'dep'), ('tags', 'tags')]:
            multival = field[0]  # multival:"val1,val2"
            prefixed = field[1]  # prefixed_val1:"x", prefixed_val2:"x"
            values = set()
            for key in list(taskdict.keys()):
                if key == multival:
                    commasep = taskdict[key]
                    separated = [v for v in commasep.split(',') if v]
                    values.update(separated)
                elif key.startswith(f"{prefixed}_"):
                    value = key[(len(prefixed)+1):]
                    values.add(value)
                    del taskdict[key]
            taskdict.update({multival: list(values)})

        tasks += [taskdict]
        times += [time_t]

    if errs:
        errstr = 'error' + ('s' if errs > 1 else '')
        bomb(f"encountered {errs} {errstr}, aborting import")

    return zip(tasks, times)


def load_tasks(tasks):

    count = 0
    for task in tasks:
        count += 1
        taskjson = jsonstore(task[0])
        fakestamp = localtime(task[1])
        cmdv = [
            which('faketime'),
            strftime("%Y-%m-%d %H:%M:%S", fakestamp),
            which(TASKCMD),
            'rc.hooks=0',  # see TW issue 3314
            'import',
        ]
        cmd(cmdv, input=taskjson, text=True, encoding='utf-8', stderr=STDOUT)
        print(f"{count}/{nrecords}", "\r", end='')

    print(f"imported {count} undo log records")

###

def main():

    tasks = get_tasks()
    load_tasks(tasks)


if __name__ == "__main__":

    # move stdin, pdb needs stdio fds itself
    stdinfd = stdin.fileno()
    if not isatty(stdinfd) and select([stdin], [], [])[0]:
        infile = open(dup(stdinfd), 'rb')
        osclose(stdinfd)  # cpython bug 73582
        try: stdin = open('/dev/tty')
        except: pass  # no ctty, but then pdb would not be in use
    else:
        bomb("must supply input on stdin")

    from bdb import BdbQuit
    if debug := int(getenv('DEBUG') or 0):
        import pdb
        from pprint import pp
        err('debug: enabled')
        unsetenv('DEBUG')  # otherwise forked children hang

    nrecords = 0
    linenum = 0
    errs = 0

    try: main()
    except BdbQuit: bomb("debug: stop")
    except SystemExit: raise
    except KeyboardInterrupt: bomb("interrupted")
    except:
        print_exc(file=stderr)
        if debug: pdb.post_mortem()
        else: bomb("aborting...")
    finally:  # cpython bug 55589
        try: stdout.flush()
        finally:
            try: stdout.close()
            finally:
                try: stderr.flush()
                except: pass
                finally: stderr.close()
