#!/usr/bin/env bash

SRVPORT=4499
RSPFILE=response

rm -f "$RSPFILE"
mkfifo "$RSPFILE"

get_api() {
	read -r line
	echo "$line"
}

handleRequest() {
	# 1) Process the request
	get_api
	mod=$(fortune)

	cat <<EOF > "$RSPFILE"
HTTP/1.1 200 OK
Content-Type: text/html
Connection: close

<pre>$(cowsay "$mod")</pre>
EOF
}

prerequisites() {
	if ! command -v cowsay >/dev/null 2>&1 || ! command -v fortune >/dev/null 2>&1; then
		echo "Install prerequisites."
		exit 1
	fi
}

main() {
	prerequisites
	echo "Wisdom served on port=$SRVPORT..."

	while true; do
		cat "$RSPFILE" | nc -lN "$SRVPORT" | handleRequest
		sleep 0.01
	done
}

main
