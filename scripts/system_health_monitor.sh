#!/usr/bin/env bash
# system_health_monitor.sh - check CPU, memory, disk and processes, alert on thresholds.
# Exit codes: 0 = healthy, 1 = at least one alert, 2 = usage error.
set -u

CPU_T="${CPU_THRESHOLD:-80}"
MEM_T="${MEM_THRESHOLD:-80}"
DISK_T="${DISK_THRESHOLD:-80}"
PROCS_T="${PROCS_THRESHOLD:-500}"
LOG_FILE="${HEALTH_LOG:-./logs/system_health.log}"
INTERVAL=0

usage() {
	cat <<USAGE
Usage: $0 [options]
  --cpu N        CPU usage % threshold (default $CPU_T, env CPU_THRESHOLD)
  --mem N        memory usage % threshold (default $MEM_T, env MEM_THRESHOLD)
  --disk N       disk usage % threshold per mount (default $DISK_T, env DISK_THRESHOLD)
  --procs N      process count threshold (default $PROCS_T, env PROCS_THRESHOLD)
  --log FILE     log file (default $LOG_FILE, env HEALTH_LOG)
  --once         run one check and exit (default)
  --interval N   run every N seconds until interrupted
  -h, --help     show this help
USAGE
}

while [ $# -gt 0 ]; do
	case "$1" in
		--cpu) CPU_T="${2:?}"; shift 2 ;;
		--mem) MEM_T="${2:?}"; shift 2 ;;
		--disk) DISK_T="${2:?}"; shift 2 ;;
		--procs) PROCS_T="${2:?}"; shift 2 ;;
		--log) LOG_FILE="${2:?}"; shift 2 ;;
		--once) INTERVAL=0; shift ;;
		--interval) INTERVAL="${2:?}"; shift 2 ;;
		-h|--help) usage; exit 0 ;;
		*) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
	esac
done

mkdir -p "$(dirname "$LOG_FILE")"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "$(ts) $*" | tee -a "$LOG_FILE"; }

# CPU usage in percent (integer). /proc/stat delta over one second, else top.
cpu_usage() {
	if [ -r /proc/stat ]; then
		local a b idle1 total1 idle2 total2 d_total d_idle
		read -r -a a < <(head -n1 /proc/stat)
		idle1=$((a[4] + a[5]))
		total1=0
		for v in "${a[@]:1:8}"; do total1=$((total1 + v)); done
		sleep 1
		read -r -a b < <(head -n1 /proc/stat)
		idle2=$((b[4] + b[5]))
		total2=0
		for v in "${b[@]:1:8}"; do total2=$((total2 + v)); done
		d_total=$((total2 - total1))
		d_idle=$((idle2 - idle1))
		if [ "$d_total" -le 0 ]; then echo 0; else echo $(((100 * (d_total - d_idle)) / d_total)); fi
	else
		local out
		out=$(top -l 1 -n 0 2>/dev/null | awk '/CPU usage/ {gsub("%","",$7); printf "%d", 100-$7}')
		if [ -z "$out" ]; then
			out=$(top -bn1 2>/dev/null | awk '/Cpu\(s\)/ {for(i=1;i<=NF;i++) if($i ~ /id,?$/) {printf "%d", 100-$(i-1)}}')
		fi
		echo "${out:-0}"
	fi
}

# Memory usage in percent.
mem_usage() {
	if [ -r /proc/meminfo ]; then
		awk '/^MemTotal:/ {t=$2} /^MemAvailable:/ {a=$2} END {if (t>0) printf "%d", (t-a)*100/t; else print 0}' /proc/meminfo
	elif command -v vm_stat >/dev/null 2>&1; then
		vm_stat | awk '/page size of/ {ps=$8} /Pages free/ {f=$3} /Pages inactive/ {i=$3} /Pages active/ {a=$3} /Pages wired/ {w=$4} /occupied by compressor/ {c=$5}
			END {gsub("\\.","",f); gsub("\\.","",i); gsub("\\.","",a); gsub("\\.","",w); gsub("\\.","",c);
			tot=f+i+a+w+c; if (tot>0) printf "%d", (a+w+c)*100/tot; else print 0}'
	else
		echo 0
	fi
}

check_once() {
	local alerts=0 cpu mem procs
	cpu=$(cpu_usage)
	mem=$(mem_usage)
	log "INFO  cpu=${cpu}% mem=${mem}%"
	if [ "$cpu" -ge "$CPU_T" ]; then log "ALERT cpu usage ${cpu}% >= threshold ${CPU_T}%"; alerts=$((alerts + 1)); fi
	if [ "$mem" -ge "$MEM_T" ]; then log "ALERT memory usage ${mem}% >= threshold ${MEM_T}%"; alerts=$((alerts + 1)); fi

	local line pct mount
	while read -r pct mount; do
		pct=${pct%\%}
		case "$pct" in ''|*[!0-9]*) continue ;; esac
		log "INFO  disk ${mount}=${pct}%"
		if [ "$pct" -ge "$DISK_T" ]; then log "ALERT disk usage on ${mount} ${pct}% >= threshold ${DISK_T}%"; alerts=$((alerts + 1)); fi
	done < <(df -P 2>/dev/null | awk 'NR>1 && $1 !~ /^(tmpfs|devfs|overlay|map)/ && $6 ~ /^\// && $6 !~ /^\/(System\/Volumes\/(VM|Preboot|Update|xarts|iSCPreboot|Hardware)|Library\/Developer|private\/var\/run|Volumes\/Recovery)/ {print $5, $6}')

	procs=$(ps -e 2>/dev/null | awk 'NR>1' | wc -l | tr -d ' ')
	log "INFO  processes=${procs}"
	if [ "$procs" -ge "$PROCS_T" ]; then log "ALERT process count ${procs} >= threshold ${PROCS_T}"; alerts=$((alerts + 1)); fi

	log "INFO  top 5 processes by CPU:"
	while read -r line; do log "INFO    ${line}"; done < <(ps -eo pid,pcpu,comm 2>/dev/null | awk 'NR>1' | sort -k2 -nr | head -n 5)

	return $((alerts > 0 ? 1 : 0))
}

if [ "$INTERVAL" -gt 0 ]; then
	rc=0
	trap 'exit $rc' INT TERM
	while true; do
		check_once || rc=1
		sleep "$INTERVAL"
	done
else
	check_once
fi
