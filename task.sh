#!/usr/bin/env bash
#
# task.sh
#   taskwtools shell wrappers
#
# scott@smemsh.net
# https://github.com/smemsh/.task/
# https://spdx.org/licenses/GPL-2.0
#

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
		echo "current task $name not engaged, aborting" >&2
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
	then echo "must supply one or more patterns" >&2; false; return; fi

	if ((outuuid && outjson))
	then echo "uuid/json outputs mutually exclusive" >&2; false; return; fi

	if ((outuuid || outjson)) && [[ $report == "all" ]]
	then echo "all report excludes json/uuid format" >&2; false; return; fi

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

### timewarrior

timefill ()
{
	(($# == 0)) && set -- @1
	(($# == 1)) || { echo "bad argn" >&2; false; return; }
	[[ $1 =~ ^@[[:digit:]]+$ ]] || { echo "malformed" >&2; false; return; }
	timew move $1 $(timew get dom.tracked.${1#@}.start) :fill
}

timeredo ()
{
	local n i ival
	local -a ivals olds

	while [[ $1 =~ ^@ ]]; do ivals+=($1); shift; done
	n=${#ivals[@]}
	if ((n == 0 || $# == 0)); then
		echo "$FUNCNAME: overwrite tags for given intervals" >&2
		echo " usage: $FUNCNAME [@interval]... [tag]..." >&2
		false
		return
	fi

	for ((i = 0; i < n; i++)); do
		ival=${ivals[i]#@}
		if (($(timew get dom.tracked.$ival.tag.count))); then
			olds=($(
				timew get dom.tracked.$ival.json |
				jq -r '.tags[]'
			))
			if ! timew untag @$ival "${olds[@]}"
			then echo "untag failed" >&2; false; return; fi
		fi
		if ! timew tag @$ival "$@"
		then echo "tag failed" >&2; false; return; fi
	done
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
	| awk 'BEGIN {r = 1} NF == 1 {print $1; r = 0} END {exit r}' \
	|| echo 0:00:00
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
	(2) week=2022-W$1;;
	(4) week=20${1:0:2}-W${1:2:2};;
	(6) week=${1:0:4}-W${1:4:2};;
	(*) echo "$FUNCNAME: bad usage" >&2; false; return;;
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

###

main ()
{
	if [[ $(declare -F $invname) ]]
	then $invname "$@"
	else echo "unimplemented command '$invname'" >&2; fi
}

invname=${0##*/}
cmdpath=${BASH_SOURCE%/*}
main "$@"
