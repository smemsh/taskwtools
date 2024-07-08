#!/usr/bin/env bash
#
# task.sh
#   taskwtools shell wrappers
#
# scott@smemsh.net
# https://github.com/smemsh/.task/
# https://spdx.org/licenses/GPL-2.0
#

bomb () { echo "${FUNCNAME[1]}: ${*}, aborting" >&2; false; exit; }

# work around always defaulting to 80 columns when piping
# note: ${COLUMNS:-80} not needed, blank value is default (which is 80)
# todo: implement env var expansion in taskwarrior
# also: #991
# note: called from other functions, hence we cache results
#
task ()
{
	local savedpath=$PATH
	local newpath arg i
	declare -g realexe argsdone

	if ! [[ $realexe ]]
	then PATH=$(
		IFS=:
		newpath=($PATH)
		for ((i = 0; i < ${#newpath[@]}; i++))
		do if [[ ${newpath[i]} == "$cmdpath" ]]
		then unset 'newpath[i]'; break; fi; done
		printf "${newpath[*]}"
	)
		realexe=$(type -P $FUNCNAME)
		PATH=$savedpath
	fi

	if ! [[ $argsdone ]]
	then
		for arg; do if [[ $arg == '--' ]]; then break
		elif [[ $arg == '--version' ]]
		then $realexe --version; return; fi; done
		let argsdone++
	fi

	$realexe rc.defaultwidth=$COLUMNS "$@"
}

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

# look in more fields that have text via taskget, and also in notes
taskgrepu () { taskgrep -u "$@"; }
taskgrepx () { taskgrep -x "$@"; }
taskgrepp () { taskgrep -a "$@"; }
taskgrep  ()
{
	local pattern nofiles outuuid outjson
	local report=next
	local filter=cat

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

	((outuuid)) && filter="jq -r '.[].uuid'"
	((outjson)) && filter="jq -r ."
	task $(taskids -za -- "$@" ${noteuuids[@]}) $report \
	| eval "$filter"
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
#
taskdeps ()
{
	local t=${1:?}; shift
	task depends:$(task $t _uuid) "$@"
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

	task $taskuuid done         || bomb "could not 'done' task $taskuuid"
	timedo :fill                || bomb "failed timedo after task completion"
}

# taskl
#   run 'task' with rest of args on the unique task that looks up from $1
#
# desc
#   - run 'task <uuid>' with uuid obtained from 'taskuuid' lookup on $1
#   - uuid is guaranteed to be unique match for the lookup arg (via 'taskone')
#   - uses dummy id if multiple or no matches, so 'task' will fail
#
taskl ()
{
	task $(taskone -nz ${1:?}) "${@:2}"
}

taskundo ()
{
	task undo
}

### timewarrior

timefill ()
{
	(($# == 0)) && set -- @1
	(($# == 1)) || { bomb "bad argn"; }
	[[ $1 =~ ^@[[:digit:]]+$ ]] || { bomb "malformed"; }
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

timeredo ()
{
	local n i ival
	local -a ivals olds

	while [[ $1 =~ ^@ ]]; do ivals+=($1); shift; done
	n=${#ivals[@]}
	if ((n == 0 || $# == 0)); then
		echo "$FUNCNAME: overwrite tags for given intervals" >&2
		bomb " usage: $FUNCNAME [@interval]... [tag]..."
	fi

	for ((i = 0; i < n; i++)); do
		ival=${ivals[i]#@}
		if (($(timew get dom.tracked.$ival.tag.count))); then
			olds=($(
				timew get dom.tracked.$ival.json |
				jq -r '.tags[]'
			))
			if ! timew untag @$ival "${olds[@]}"
			then bomb "untag failed"; fi
		fi
		if ! timew tag @$ival "$@"
		then bomb "tag failed"; fi
	done
}

timetmp ()
{
	local uuid=`uuid`
	local uuidpfx=${uuid%%-*}
	timew start time/tmp$uuidpfx
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
	| awk '
	BEGIN {r = 1}
	NF == 1 && $1 ~ /^[[:digit:]:]+$/ {
		print $1
		r = 0
	}
	END {exit r}
	' || echo 0:00:00
}

timecur ()
{
	task calc \
		$(timew export @1 | jq -r '.[].start') - \
		$(timewfmt $(now))
}

timesince ()
{
	local duration=${1:?}
	local start="$(task calc "${2:-"(now - $duration)"}")"
	local end="$(task calc "$start" + "$duration")"
	echo "$start" - "$end"
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
cmdpath=${BASH_SOURCE%/*}
main "$@"
