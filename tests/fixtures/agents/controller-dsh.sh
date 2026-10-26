#!/bin/sh
if [ "$1" = "--version" ]; then
  echo "fake-dsh 0.1"
  exit 0
fi
input=$(cat)
printf 'proof.txt' > proof.txt
printf '{"type":"session","sessionId":"session-controller","cwd":"%s"}\n' "$PWD"
printf '%s\n' '{"type":"status","phase":"turn_start","turn":1}'
printf '%s\n' '{"type":"status","phase":"turn_end","turn":1,"reason":{"kind":"ok"}}'
printf '%s\n' '{"type":"final","text":"CONTROLLER_DONE"}'
exit 0
