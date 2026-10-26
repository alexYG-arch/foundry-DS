#!/bin/sh
cat >/dev/null
mkdir -p src outputs
printf "VALUE = 'fixture'\n" > src/reader.py
printf '{"fixture": true}\n' > outputs/summary.json
printf '{"type":"result","status":"ok"}\n'
