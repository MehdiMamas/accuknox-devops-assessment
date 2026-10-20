#!/usr/bin/env bash
# backup.sh - archive a directory and ship it to a remote server (rsync/ssh), S3, rclone or a local dir.
# Exit codes: 0 success, 1 backup/transfer failure, 2 usage error.
set -u

SRC=""
TYPE=""
DEST=""
KEEP=7
DRY=0
REPORT_LOG="${BACKUP_REPORT_LOG:-./logs/backup_report.log}"
WORK_DIR="${TMPDIR:-/tmp}"

usage() {
	cat <<USAGE
Usage: $0 --source DIR --type rsync|s3|rclone|local --dest TARGET [options]
  --source DIR    directory to back up
  --type T        rsync (user@host:/path via ssh), s3 (s3://bucket/prefix, needs aws cli),
                  rclone (remote:path), local (a directory; handy for testing)
  --dest TARGET   destination for the chosen type
  --keep N        keep the newest N archives at the destination (default $KEEP)
  --report FILE   report log (default $REPORT_LOG)
  --dry-run       show what would happen, change nothing
  -h, --help      show this help
USAGE
}

while [ $# -gt 0 ]; do
	case "$1" in
		--source) SRC="${2:?}"; shift 2 ;;
		--type) TYPE="${2:?}"; shift 2 ;;
		--dest) DEST="${2:?}"; shift 2 ;;
		--keep) KEEP="${2:?}"; shift 2 ;;
		--report) REPORT_LOG="${2:?}"; shift 2 ;;
		--dry-run) DRY=1; shift ;;
		-h|--help) usage; exit 0 ;;
		*) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
	esac
done

if [ -z "$SRC" ] || [ -z "$TYPE" ] || [ -z "$DEST" ]; then usage >&2; exit 2; fi
if [ ! -d "$SRC" ]; then echo "source is not a directory: $SRC" >&2; exit 2; fi
case "$TYPE" in rsync|s3|rclone|local) ;; *) echo "unknown type: $TYPE" >&2; exit 2 ;; esac
case "$KEEP" in ''|*[!0-9]*) echo "--keep must be a number" >&2; exit 2 ;; esac
[ "$KEEP" -ge 1 ] || { echo "--keep must be >= 1" >&2; exit 2; }

NAME="$(basename "$(cd "$SRC" && pwd)")"
STAMP="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="${NAME}-${STAMP}.tar.gz"
CHECKSUM="${ARCHIVE}.sha256"
START=$(date +%s)
TMP="$(mktemp -d "${WORK_DIR%/}/backup.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$(dirname "$REPORT_LOG")"

report() {
	local status="$1" size="${2:-0}" msg="${3:-}" dur
	dur=$(($(date +%s) - START))
	local line
	line="$(date '+%Y-%m-%d %H:%M:%S') status=${status} source=${SRC} destination=${TYPE}:${DEST} archive=${ARCHIVE} size_bytes=${size} duration_s=${dur} dry_run=${DRY} ${msg}"
	echo "$line"
	echo "$line" >> "$REPORT_LOG"
}

fail() { report FAILURE "${2:-0}" "error=\"$1\""; exit 1; }

run() {
	if [ "$DRY" -eq 1 ]; then echo "[dry-run] $*"; return 0; fi
	"$@"
}

sha() {
	if command -v sha256sum >/dev/null 2>&1; then (cd "$1" && sha256sum "$2" > "$2.sha256")
	else (cd "$1" && shasum -a 256 "$2" > "$2.sha256"); fi
}

if [ "$DRY" -eq 1 ]; then
	echo "[dry-run] would create ${ARCHIVE} from ${SRC} and ${CHECKSUM}"
else
	tar -czf "$TMP/$ARCHIVE" -C "$(dirname "$(cd "$SRC" && pwd)")" "$NAME" || fail "tar failed"
	sha "$TMP" "$ARCHIVE" || fail "checksum failed"
fi
SIZE=0
[ -f "$TMP/$ARCHIVE" ] && SIZE=$(wc -c < "$TMP/$ARCHIVE" | tr -d ' ')

case "$TYPE" in
	local)
		run mkdir -p "$DEST" || fail "cannot create $DEST"
		run cp "$TMP/$ARCHIVE" "$TMP/$CHECKSUM" "$DEST/" || fail "copy failed" "$SIZE"
		if [ "$DRY" -eq 0 ]; then
			# shellcheck disable=SC2012
			ls -1t "$DEST/${NAME}-"*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
				rm -f "$old" "$old.sha256"
			done
		else
			echo "[dry-run] would prune to newest $KEEP archives in $DEST"
		fi
		;;
	rsync)
		command -v rsync >/dev/null 2>&1 || [ "$DRY" -eq 1 ] || fail "rsync not installed"
		HOSTPART="${DEST%%:*}"; PATHPART="${DEST#*:}"
		run rsync -e "ssh -o BatchMode=yes" -a "$TMP/$ARCHIVE" "$TMP/$CHECKSUM" "$DEST/" || fail "rsync failed" "$SIZE"
		if [ "$DRY" -eq 0 ]; then
			# shellcheck disable=SC2029
			ssh -o BatchMode=yes "$HOSTPART" "cd '$PATHPART' && ls -1t ${NAME}-*.tar.gz | tail -n +$((KEEP + 1)) | while read -r f; do rm -f \"\$f\" \"\$f.sha256\"; done" || fail "remote retention failed" "$SIZE"
		else
			echo "[dry-run] would prune to newest $KEEP archives on $HOSTPART:$PATHPART"
		fi
		;;
	s3)
		command -v aws >/dev/null 2>&1 || [ "$DRY" -eq 1 ] || fail "aws cli not installed"
		run aws s3 cp "$TMP/$ARCHIVE" "${DEST%/}/$ARCHIVE" || fail "s3 upload failed" "$SIZE"
		run aws s3 cp "$TMP/$CHECKSUM" "${DEST%/}/$CHECKSUM" || fail "s3 upload failed" "$SIZE"
		if [ "$DRY" -eq 0 ]; then
			aws s3 ls "${DEST%/}/" | awk '{print $4}' | grep -E "^${NAME}-.*\.tar\.gz$" | sort -r | tail -n +$((KEEP + 1)) | while read -r old; do
				aws s3 rm "${DEST%/}/$old" >/dev/null; aws s3 rm "${DEST%/}/$old.sha256" >/dev/null
			done
		else
			echo "[dry-run] would prune to newest $KEEP archives in $DEST"
		fi
		;;
	rclone)
		command -v rclone >/dev/null 2>&1 || [ "$DRY" -eq 1 ] || fail "rclone not installed"
		run rclone copy "$TMP/$ARCHIVE" "$DEST" || fail "rclone failed" "$SIZE"
		run rclone copy "$TMP/$CHECKSUM" "$DEST" || fail "rclone failed" "$SIZE"
		if [ "$DRY" -eq 0 ]; then
			rclone lsf "$DEST" | grep -E "^${NAME}-.*\.tar\.gz$" | sort -r | tail -n +$((KEEP + 1)) | while read -r old; do
				rclone deletefile "$DEST/$old"; rclone deletefile "$DEST/$old.sha256"
			done
		else
			echo "[dry-run] would prune to newest $KEEP archives in $DEST"
		fi
		;;
esac

report SUCCESS "$SIZE"
exit 0
