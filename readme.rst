Taskwtools
==============================================================================

Taskwarrior and Timewarrior Tools

These are wrappers and hooks used to work with `Taskwarrior`_ and
`Timewarrior`_.  Someone might find them useful.

Mainly implemented in Python, with ``task.py`` implementing the bulk
of commands and hooks.  Some auxiliary commands are implemented in
bourne again syntax within ``task.sh``.

``jq`` command scripts are sometimes embedded in the shell scripts, and
that tool is required for functionality.

Tested versions:

:taskwarrior: 2.6.2
:timewarrior: 1.7.1
:python-timew: 0.2.0
:jq: 1.7.1
:tasklib: https://github.com/smemsh/tasklib/ 83619b1 (with PRs 117, 119)

.. contents::

.. _Taskwarrior: https://github.com/GothenburgBitFactory/taskwarrior
.. _Timewarrior: https://github.com/GothenburgBitFactory/timewarrior


Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

At last the following taskwarrior config are assumed by the scripts::

  data.location = ~/.task
  dateformat = YMD
  uda.label.type = string
  uda.label.label = label


Task Labels and FQLs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

One of the central concepts of the interaction framework is that all
tasks have a UDA string field known as their ``label``, used to refer to
the task with the various tool interfaces.  For example, the task in my
task database used for initial release of this project has label
``taskwtools``.

The ``label`` field is non-unique globally, but is guaranteed to be
unique within a given project hierarchy.  The combination of a project,
subproject_, and label is called an ``fql`` or *Fully Qualified Label*.

  *Note: (actually, the label is forcibly unique also at this
  time, but work is underway to remove this limitation, so that
  the above paragraph is accurate, and only fqls need be unique)*

In **taskwtools**, fql components are delimited by slash characters
(like filesystem paths).  For example, the fql for this project in my
task database is ``/src/taskw/taskwtools`` and corresponds to a task
with project ``src.taskw`` and label ``taskwtools``.

Using labels and fqls avoids having to work with task IDs -- which
themselves are ephemeral and get rearranged during *taskwarrior* garbage
collection -- and allows for easy display and reference of tasks with
enough information to remember what they are, without needing their
description.

*Note*: in most places, the leading ``/`` of an fql does not have to be
specified, and will not be displayed.

.. _subproject: GothenburgBitFactory/taskwarrior@fd7bb9da


Timewarrior Tags
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

As tasks are worked on, their fqls are automatically inserted into the
*timewarrior* database (by tooling hooks), broken down into their
components, along with *taskwarrior* tags (which get prefixed with
``+``).  This way we can easily select and report on time spent for all
tasks that have certain tags, or are at a certain project hierarchy
level.

For example, the task fql ``/src/taskw/taskwtools`` with tags ``github``
and ``taskwarrior`` would have the following tags added to *timewarrior*
events::

    +taskwarrior +github src/, src/taskw/, src/taskw/taskwtools

Tags with a trailing slash are non-leaf -- i.e. project components --
whereas the task fql will be the only one without a trailing slash or a
``+`` prefix.

Use of this scheme allows for tracking and reporting of time spent
cumulatively on (1) all tasks within any given levels of project
hierarchy, (2) on the task itself, or (3) with given *taskwarrior* tags.


Timewarrior pseudo-tasks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This implementation reserves the namespace prefix ``time/`` as
corresponding to tasks which will get tracked in *timewarrior*, but
won't have a backing *taskwarrior* task.  This is for pseudo-tasks which
eat time but aren't real discrete tasks (*todo*: make configurable)

For example someone might use ``time/todo`` to track time spent figuring
out what to do next, ie querying the task database, or doing task
maintenance.  This is useful to track because it represents a particular
kind of overhead.  One might also use ``time/quick`` to track work too
short or trivial to have an actual task, such as for one-off trivial
fixes that nonetheless take a small bit of time.

These do add up, and are worth tracking for time, but aren't significant
enough to warrant their own task.

There is a shortcut ``timedo`` for starting pseudo-tasks, for example::

    $ timedo github
    $ taskstop
    $ timecont

can be used to start, stop and continue the ``time/github`` pseudo-task.
The default for ``timedo`` with no arguments is ``time/todo``.


Taskget
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The main driver function in ``task.py`` for task selection is
``_taskget()``.  It implements the task search algorithm when given a
query string.  Most **taskwtools** commands will use this function when
given a string reference, to resolve a task for acting upon or displaying.

Roughly, the lookup algorithm is the first successful match, attempted
in the following order:

#. task id number
#. full task uuid string
#. initial substring of task uuid
#. task ``label`` field (if no ``/`` present)
#. full task fql string (if contains ``/``)
#. project substring of fql (if contains ``/``)
#. within description, label and project as substring, if requested
#. within description, label and project as regex, if requested

The interfaces to the ``_taskget()`` algorithm are many, such as
``taskdo``, ``taskid``, ``taskget``, ``taskfql``, ``tasknotes`` and
``taskgrep``.

Various flags can be used to modify the search behavior (typically
common to commands which use ``_taskget()`` internally), such as forcing
an exact match, looking only at ID-like fields, etc.

In the future, it taskget results can be sorted (ie, for surfacing the
best one) either by timew or taskw modtime (after other filters match),
but currently only by-taskw-modtime sorting is implemented.


Main Commands
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Using the ``--help`` flag when invoking a **taskwtools** command will
generally show the available flags and/or syntax.  The main ones are:

:taskadd:   add a task with label and short description
:taskdo:    starts clock on taskget-matching task (no args: last task)
:taskstop:  stops clock on the currently tracked task
:taskget:   matches task using taskget algorithm and pretty-prints
:taskcont:  continues the last task, excluding `Timewarrior pseudo-tasks`_
:timecont:  continues the last task, including any in `time/`

The first time a task is started, *taskwarrior* must be used, e.g.::

  $ taskadd src/taskpy/addhelp +taskw 'add help text to all timewtools'
  $ task `taskid addhelp` start
  $ taskstop
  $ taskdo

Subsequently, ``taskdo`` can be used to start the clock.  It picks the
last task worked on if no args are given, otherwise it uses the taskget
algorithm to find the task to track time against.

Use ``timecont`` to consider starting also those in ``time/`` namespace,
otherwise ``taskcont`` or ``taskdo`` will go back to the last taskw task
that has an interval in timew.


Command Reference
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


actions
------------------------------------------------------------------------------

=============== =========== ==================================================
invocation      script      description
=============== =========== ==================================================
taskdo          task.py     start clock on named task
timedo          task.sh     start non-taskw interval named time/${1:-todo}
tasklast        taskcont    start the one before last task excluding time/
timelast        taskcont    start the one before last task including time/
timecont        taskcont    start the last task including time/
taskcont        taskcont    start the last task excluding time/
taskstop        task.py     stop the current timew tracking
taskdone        task.sh     complete given/current task, start time/todo
taskrestart     task.sh     change task back to pending with new start
tasktmp         task.sh     make task and start: /task/tmp<random>
timetmp         task.sh     timew start /time/tmp<random>
taskget         task.py     show taskget resolution for the given tasks
taskdel         task.sh     delete, collect, and purge a task
taskgc          task.sh     run taskwarrior garbage collection
taskundo        task.sh     undo the previous taskwarrior operation
timeundo        task.sh     timew undo
timefill        task.sh     move arg/current interval's start to last end
=============== =========== ==================================================


queries
------------------------------------------------------------------------------

=============== =========== ==================================================
taskdummy       task.py     print a cannot-match uuid, exits nonzero
taskfql         task.py     print current or uniquely matching task
taskfqls        task.py     print all the matching fqls
taskid          task.py     print best matching task
taskids         task.py     print all matching tasks
tasklabel       task.py     print label of best matching task
tasklabels      task.py     print labels of all matching tasks
taskline        task.py     print current fql, tracking status symbol, date
tasknow         task.py     print current fql, tracking status english
tasknotes       task.py     print from ~/.task/notes/<uuid>.rst
taskone         task.py     print matching task uuid, failure if non-unique
taskuuid        task.py     print best matching task uuid
taskuuids       task.py     print all matching task uuids
taskfield       task.sh     print the single given task's named field
timecur         task.sh     print time so far in current interval
timein          task.sh     print the timewfmt time at now + $@
timeline        task.sh     print time spent in recent calendars
timeopen        task.sh     print time tracked since clock last off
timels          task.sh     print list of timew entries in time/ fqlspace
timevals        task.sh     print all intervals that tracked given taskfql
timewk          task.sh     print the timew time given ISO week num begins
timewtags       task.py     print the timew tags of current or given task
taskday         task.py     print labels of tasks from last N[=1] days
taskall         task.py     taskday 0 (all tasks)
taskmonth       task.py     taskday 30
tasks           task.py     taskday 7
taskweek        task.py     taskday 7
taskyear        task.py     taskday 365
=============== =========== ==================================================


select
------------------------------------------------------------------------------

=============== =========== ==================================================
taskcur         task.sh     select the active task
taskdeps        task.sh     select all dependents of given tasks
taskl           task.sh     select task with given unique label substring
taskgrep        task.sh     search by taskget/rst grep, default report
taskgrepp       task.sh     taskgrep with report all
taskgrepu       task.sh     taskgrep -u (display only uuids)
taskgrepx       task.sh     taskgrep -x (export as json)
=============== =========== ==================================================


utility
------------------------------------------------------------------------------

=============== =========== ==================================================
fqlfmt          task.sh     print label, project hierarchy cols from fqls
timewfmt        task.sh     completes partial YYYYDDMMHHMMSS as timew time
tasknote        taskopen    display ~/.task/notes/<uuid.rst>, -e to edit
taskopen        taskopen    scrape task notes/rst for urls and pick one
=============== =========== ==================================================

report
------------------------------------------------------------------------------

=============== =========== ==================================================
taskrecent      taskrecent  displays recent tasks by taskw modtime, has flags
timerecent      taskrecent  taskrecent but by timew modtime, not task metadata
timesum         task.sh     calculates time tracked since arg or :all
timestat        task.sh     timew summary for the args or :all
taskreport      task.sh     print unique fqls/times during given time range
=============== =========== ==================================================


On-modify Hook
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**TODO**: document that the hook (in ``task.py``) handles propagating
changes in label and project to timew, and other things like safety,
preventing duplicates, etc



Tasklib
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The tasklib we use needs patches, but no response to my PRs in 2+ years,
project is stalled or abandoned, so my forked tasklib is used, see "Tested
versions" above.
