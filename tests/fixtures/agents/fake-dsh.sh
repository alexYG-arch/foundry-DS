#!/bin/sh
# Test double for dsh headless; never calls a model.
if [ "$1" = "--version" ]; then
  echo "fake-dsh 0.1"
  exit 0
fi
input=$(cat)
printf '{"type":"session","sessionId":"session-fake","cwd":"%s"}\n' "$PWD"
printf '{"type":"status","phase":"turn_start","turn":1}\n'
if [ -z "$DEEPSEEK_API_KEY" ]; then
  printf '%s\n' '{"type":"status","phase":"turn_end","turn":1,"reason":{"kind":"error","error":{"code":"MISSING_CREDENTIAL","message":"missing"}}}'
  printf '%s\n' '{"type":"final","text":""}'
  exit 1
fi
printf '%s\n' '{"type":"status","phase":"turn_end","turn":1,"reason":{"kind":"ok"}}'
printf '%s\n' '{"type":"final","text":"DONE"}'
exit 0
