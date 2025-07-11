#!/usr/bin/env bash
#
# task.sh
#   taskwtools shell wrappers
#
# scott@smemsh.net
# https://github.com/smemsh/.task/
# https://spdx.org/licenses/GPL-2.0
#
f=~/.taskenv; test -r $f && source $f; unset f

bomb () { echo "${FUNCNAME[1]}: ${*}, aborting" >&2; false; exit; }

### taskwarrior

taskcur ()
{
	local tasknow=($(tasknow))
	local status=${tasknow[1]}
	local name=${tasknow[0]}

	if [[ $status != 'started' ]]; then
		bomb "current task $name not engaged, aborting"
		false; return; fi

	task $(taskid -xn $name) "$@"
}

taskn ()
{
	task rc.hooks=0 "$@"
}

taskprjs ()
{
	task _unique project
}

taskann ()
{
	taskcur annotate -- "$@"
}

# look in more fields that have text via taskget, and also in notes
taskgrepu () { taskgrep -u "$@"; }
taskgrepx () { taskgrep -x "$@"; }
taskgrepp () { taskgrep -a "$@"; }
taskgrep  ()
{
	local pattern nofiles outuuid outjson
	local report=next

	local -a patexprs rstpaths noteuuids

	usage ()
	{
		cat <<- %
		usage: $FUNCNAME [option]... [searchpat]...

		search by taskget and rstnote grep; report or export
		  -u output only matching task UUIDs
		  -x output JSON export of matching tasks
		  -a use 'all' report (matches include closed ones)
		  -n do not look in rst notes of tasks for matching text
		%
	}

	eval set -- $(getopt -n $FUNCNAME \
	-o auxnh -l all,uuid,json,nofiles,help -- "$@")
	while true; do case $1 in
	(-a|--all)  report=all; shift;;
	(-u|--uuid) report=export outuuid=1; shift;;
	(-x|--json) report=export outjson=1; shift;;
	(-n|--nofiles) nofiles=1; shift;;
	(-h|--help) usage; true; return;;
	(--) shift; break;;
	(*) usage; false; return;;
	esac; done

	if ! (($#))
	then bomb "must supply one or more patterns"; fi

	if ((outuuid && outjson))
	then bomb "uuid/json outputs mutually exclusive"; fi

	if ((outuuid || outjson)) && [[ $report == "all" ]]
	then bomb "all report excludes json/uuid format"; fi

	if ! ((nofiles)); then
		for pattern; do patexprs+=(-e "$pattern"); done
		rstpaths=($(grep -Els "${patexprs[@]}" ~/.task/notes/*.rst))
	fi

	if ((${#rstpaths[@]}))
	then noteuuids=($(basename -s .rst ${rstpaths[@]}))
	else noteuuids=()
	fi

	notes=$(taskids -za -- "$@" ${noteuuids[@]})
	if ((outuuid || outjson))
	then
		((outuuid)) && filter="jq -r '.[].uuid'"
		((outjson)) && filter="jq -r ."
		task $notes $report | eval "$filter"
	else
		# taskwarrior uses stdout to get rc.defaultwidth, so
		# don't use pipe, even to 'cat' as we used to default
		# for $filter and use same code for everyone
		task $notes $report
	fi
}

taskgc ()
{
	task rc.gc=on rc.verbose=nothing // list >/dev/null
	(($(task +DELETED _unique uuid | wc -l))) &&
		task rc.bulk=0 +DELETED purge
}

taskdel ()
{
	task rc.hooks=0 "${@:?}" delete && taskgc &&
	task rc.hooks=0 "$@" purge
}

tasktmp ()
{
	local uuid=`uuid`
	local uuidpfx=${uuid%%-*}
	local taskn

	if taskn=$(taskadd task/tmp$uuidpfx $uuid)
	then task $taskn start || bomb "taskadd failed"; fi
}

# display contents of task $1 field $2, directly from its json export record
taskfield ()
{
	(($# == 2)) || bomb "wrong args"
	task $(taskid -x $1) export \
	| jq -r ".[].${2:?}"
}

fqlfmt ()
{
	awk -F / '{
	printf("%s ", $NF)
	for (i = 1; i < NF; i++) printf("%s/", $i)
	printf("\n")
	}' | column -t
}

taskrestart ()
{
	local t=`taskid $1`
	task $t mod status:pending end: start:$(timewfmt $(now))
	#taskdo $t # <-- see task e3400a1c, keeping commented out for now
}

# needed because taskwarrior 'depends:', is actually a string
# field containing comma-delimited uuids, see #2193, and note
# that #2569 may change the type of this field
# see also task 2196992f-b810-4c23-9874-cb1e3ff0d7c7
#
taskrdeps ()
{
	local t=${1:?}; shift
	t=$(taskone -n $t) || bomb "dependee lookup failed"
	task depends.has:$t "$@"
}

taskdeps()
{
	local deps
	local t=${1:?}; shift
	(($#)) || set -- all # default report to include completed
	t=$(taskone -n $t) || bomb "depender lookup failed"
	deps="$(task $t export | jq -r '.[].depends[]?')"
	task ${deps:-$(taskdummy)} "$@"
}

# completes the current task, if it's a real task with an fql
# keeps clock running on time/todo
#
taskdone ()
{
	local tasknow="$(tasknow)"  || bomb "failed tasknow"
	local taskfql=$(taskfql)    || bomb "failed taskfql"
	local taskuuid=$(taskuuid)  || bomb "failed taskuuid"

	[[ $tasknow =~ "^time/" ]]  && bomb "cannot complete time/ pseudo-tasks"
	[[ $tasknow =~ started$ ]]  || bomb "current task not in 'started' state"
	[[ $taskuuid ]]             || bomb "cannot look up current task uuid"
	[[ $taskfql ]]              || bomb "current task fails lookup as fql"
	uuid -d "$taskuuid" \
	    &>/dev/null             || bomb "current task uuid is malformed"

	task uuid:$taskuuid done    || bomb "could not 'done' task $taskuuid"
	timedo :fill                || bomb "failed timedo after task completion"
}

# taskl
#   run 'task' with rest of args on the unique task that looks up from $1
#
# desc
#   - run 'task uuid:<uuid>' with uuid obtained from 'taskuuid' lookup on $1
#   - uuid is guaranteed to be unique match for the lookup arg (via 'taskone')
#   - uses dummy id if multiple or no matches, so 'task' will fail
#
taskl ()
{
	task uuid:$(taskone -nz ${1:?}) "${@:2}"
}

taskundo ()
{
	task undo
}

taskredo ()
{
	timew move @1 `date -Iseconds`
}

### timewarrior

timefill ()
{
	(($# == 0)) && set -- @1
	(($# == 1)) || bomb "bad argn"
	[[ $1 =~ ^@[[:digit:]]+$ ]] || bomb "malformed"
	timew move $1 $(timew get dom.tracked.${1#@}.start) :fill
}

# start timew task "time/$1", with optional :hints, default "time/todo"
timedo ()
{
	local arg argc
	declare -a hints args

	for ((i = 1; i <= $#; i++)); do
		arg=${!i}
		if [[ $arg =~ ^: ]]
		then hints+=($arg)
		else args+=(time/$arg)
		fi
	done

	argc=${#args[@]}
	((argc > 1)) && bomb "only zero or one fql, and timew :hints allowed"
	((argc == 0)) && args=(time/todo)

	timew start $args ${hints[@]}
}

timetmp ()
{
	local uuid=`uuid`
	local uuidpfx=${uuid%%-*}
	timew start time/tmp$uuidpfx
}

taskinfo ()
{
	(($#)) || set -- `taskuuid`
	taskn \
		rc._forcecolor=0 \
		rc.detection=0 \
		rc.defaultwidth=0 \
		"$@" \
	| gawk '
	function print_row(type, startval)
	{
		printf("%s\t", type)
		for (i = startval; i <= NF; i++)
			printf("%s\x20", $i)
		printf("\n")
	}
	function print_values(type, wordcount, is_multiline)
	{
		print_row(type, wordcount + 1)
		if (!is_multiline) next
		while (getline) {
			if ($0 !~ /^[[:space:]]/) break
			print_row(type, 1)
		}
	}
	/^ID/                    { print_values("id",         1) }
	/^Description/           { print_values("desc",       1) }
	/^Status/                { print_values("stat",       1) }
	/^Project/               { print_values("proj",       1) }
	/^This task is blocking/ { print_values("rdep",       4, 1) }
	/^This task blocked by/  { print_values("dep",        4, 1) }
	/^Entered/               { print_values("entry",      1) }
	/^Start/                 { print_values("start",      1) }
	/^End/                   { print_values("end",        1) }
	/^Tags/                  { print_values("tags",       1) }
	/^Virtual tags/          { print_values("vtags",      2) }
	/^UUID/                  { print_values("uuid",       1) }
	/^Urgency/               { print_values("urg",        1) }
	/^Last modified/         { print_values("mtime",      2) }
	/^Priority/              { print_values("pri",        1) }
	/^[a-z]/                 { print_values($1,           1) }
	' \
	| tr -s $'\x20' \
	;
}

# todo: do this in totals.py instead, making a new report.py,
# adding tag counts and hierarchy counts
#
taskreport ()
{
	timew totals ${1:-:week} \
	| grep / \
	| awk '{print $2, $1}' \
	| grep -v /$ \
	| sort -nrk 1,1 \
	| awk '
	BEGIN { timeformat = "%3u:%02u:%02u" }
	{
		split($1, times, ":")
		fql = $2
		h = times[1]; m = times[2]; s = times[3]
		hours += h; minutes += m; seconds += s
		printf(timeformat " %s\n", h, m, s, fql)
	}
	END {
		minutes = minutes + (int(seconds / 60))
		seconds = seconds % 60
		hours = hours + int(minutes / 60)
		minutes = minutes % 60
		printf(timeformat " <-- TOTAL\n", hours, minutes, seconds)
	}'
}

timestat ()
{
	local i
	local all=:all

	for ((i = 1; i <= $#; i++)); do
		[[ ${!i} =~ / ]] && continue # fql component
		[[ ${!i} =~ ^\+ ]] && continue # taskw tag
		unset all
	done
	timew summary "$@" :ids $all
}

timesum ()
{
	timestat "$@" \
	| tac \
	| awk 'BEGIN {r = 1} NF == 1 {r = 0; print $1; exit} END {exit r}' \
	|| echo 0:00:00
}

timeline ()
{
	local opentime=$(timeopen)
	local weekago=$(task calc now - 1 week)
	local ydate=$(task calc now - 1 day)

	local q="Q$(date +%q) $(timesum :quarter)"; q=${q%:*}
	local m="M$(date +%-m) $(timesum :month)"; m=${m%:*}
	local l="W$(date -d $weekago +%-V) $(timesum :lastweek)"; l=${l%:*}
	local y="Y$(date +%y) $(timesum :year)"; y=${y%:*}
	local w="W$(date +%V) $(timesum :week)"; w=${w%:*}
	local d="D$(date -d $ydate +%-d) $(timesum :yesterday)"; yd=${d%:*}
	local d="D$(date +%-d) $(timesum :day)"; td=${d%:*}

	echo "$y / $q / $m / $l / $w / $yd / $td / $opentime"
}

timecur ()
{
	task calc \
		$(timew export @1 | jq -r '.[].start') - \
		$(timewfmt $(now))
}

# how long we have been doing a contiguous timew session (of however
# many intervals).  first, gets N where N is interval number going back
# that was first discontiguous with previous intervals (nonzero
# inter-interval duration).  then sums interval durations going back
# that many intervals
#
timeopen ()
{
	local endi iinterval ii_start ii_end duration
	local opentime

	# max intervals back to look for an inter-interval time > 1s
	local endmax=99

	for ((endi = 1; endi < endmax; endi++)); do
		iinterval=($(timew get \
			dom.tracked.$((endi+1)).end \
			dom.tracked.$endi.start))
		ii_start=${iinterval[0]}
		ii_end=${iinterval[1]}
		duration=$(task calc $ii_end - $ii_start)
		[[ $duration == PT[01]S ]] || break
	done

	((endi == endmax)) &&
		bomb "reached max $endmax inter-intervals audited for nonzero"

	opentime=$(task calc $(
		eval timew get dom.tracked.{1..$endi}.duration \
		| fmt -1 \
		| paste -sd+ \
	))
	opentime=${opentime#PT}
	opentime=${opentime,,?}
	printf $opentime
	tty -s && echo
}

timein ()
{
	task calc now + "$@"
}

timewk ()
{
	local week
	case ${#1} in
	(2) week=`date +%Y`-W$1;;
	(4) week=20${1:0:2}-W${1:2:2};;
	(6) week=${1:0:4}-W${1:4:2};;
	(*) bomb "bad usage";;
	esac
	task calc $week
}

timevals ()
{
	local -a ivals
	local lookupfql=$(taskfql ${1:-$(taskfql)})
	local i
	[[ $lookupfql ]] || { false; return; }

	for i in $(timew export $lookupfql | jq -r '.[].id')
	do ivals+=($i); done

	for ((i = 0; i < ${#ivals[@]}; i++))
	do printf $'@%u\x20' ${ivals[i]}; done
	if ((i)); then echo; fi
}

# convert from a yyyyddhhmmss to an iso8601 (less tz) time for timew
#
# any supplied substring is superimposed over rhs of current time, thus
# comprising a partially-specified time that has its unspecified
# remainder defaulted into by the current time.  if superimposed time is
# calculated to be later than the invocation time, the superimposition
# is recalculated over a time 24 hours prior to invocation.
#
timewfmt ()
{

	if ! [[ $1 =~ [[:digit:]]{1,14} ]]
	then bomb "invalid date given"; fi

	local fmt=%Y%m%d%H%M%S
	local now_t=${EPOCHSECONDS:?}
	local yester_t=$((now_t - 86400))
	local t

	printf -v now_d "%($fmt)T" $now_t
	printf -v yester_d "%($fmt)T" $yester_t

	rhsimpose () { printf -v t ${2:0:-${#1}}$1; }
	rhsimpose $1 $now_d
	if ((t > now_d))
	then rhsimpose $1 $yester_d; fi

	# todo: should this have a newline? it's normally in a subshell
	# with other args on the command line, not used standalone, so
	# no newline is appropriate.  should we use tty(1)?  but that
	# still wouldn't work correctly in most usage scenarios which
	# are backticks, not pipelines.  we could use $SHLVL but this
	# would be incorrect in a wide variety of situations...
	#
	printf ${t:0:4}-${t:4:2}-${t:6:2}T${t:8:2}:${t:10:2}:${t:12:2}
}

timels ()
{
	timew export \
	| jq -r '[.[].tags] | flatten | .[]' \
	| grep ^time/ \
	| sort \
	| uniq -c \
	| sort -nrk 1,2 \
	;
}

timeundo ()
{
	timew undo
}

###

main ()
{
	if [[ $(declare -F $invname) ]]
	then $invname "$@"
	else bomb "unimplemented command '$invname'"; fi
}

invname=${0##*/}
main "$@"
