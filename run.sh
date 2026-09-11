#!/usr/bin/env bash
# Starts and stops the backend and the UI.
#
#   bash run.sh start        backend + built UI, all on one port
#   bash run.sh start dev    backend + vite with hot reload
#   bash run.sh stop         stops both
#   bash run.sh status       what is running
#   bash run.sh restart      stop + start (accepts 'dev')
#   bash run.sh logs         follow both logs live
#
# Ports: BACK_PORT=8787 FRONT_PORT=5173 bash run.sh start
#
# Each service starts under setsid, in its own process group, and is stopped by
# killing that group by saved PID. Never by text pattern: a 'pkill -f' also
# matches the command that is running it, and kills itself.

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNDIR="$ROOT/.run"
BACK_PORT="${BACK_PORT:-8787}"
FRONT_PORT="${FRONT_PORT:-5173}"
MAX_WAIT=25              # how many 0.4s ticks to wait for a port to answer

mkdir -p "$RUNDIR"

# ------------------------------------------------------------------- helpers

port_open() {
    python3 - "$1" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket(); s.settimeout(0.4)
open_ = s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0
s.close()
sys.exit(0 if open_ else 1)
PY
}

pid_of() { [ -f "$RUNDIR/$1.pid" ] && cat "$RUNDIR/$1.pid" 2>/dev/null || true; }

# Finds one of our own processes by what it is actually running, not by a text
# pattern over the whole command line. Needed because if the pid file is lost —
# someone wipes .run, or the box reboots mid-flight — the service keeps holding
# the port and 'stop' would otherwise have no way to reach it.
find_stray() {
    python3 - "$1" "$2" <<'FINDPY' 2>/dev/null
import os, sys
kind, port = sys.argv[1], sys.argv[2]
needle = "server.py" if kind == "backend" else "vite"
me = os.getpid()
for pid in sorted(int(d) for d in os.listdir("/proc") if d.isdigit()):
    if pid == me:
        continue
    try:
        raw = open("/proc/%d/cmdline" % pid, "rb").read().decode("utf-8", "replace")
    except OSError:
        continue
    parts = [c for c in raw.split("\0") if c]
    if parts and any(needle in c for c in parts) and any(c == port for c in parts):
        print(pid)
        break
FINDPY
}

# No pid file but the port is held by one of ours: adopt it, so stop works.
reclaim() {
    local name="$1" port="$2" stray
    alive "$name" && return 0
    port_open "$port" || return 1
    stray="$(find_stray "$name" "$port")"
    if [ -n "$stray" ]; then
        echo "$stray" > "$RUNDIR/$name.pid"
        echo "   $name: adopted a stray process (pid $stray) with no pid file"
        return 0
    fi
    return 1
}

alive() {
    local pid; pid="$(pid_of "$1")"
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

wait_for_port() {
    local port="$1" name="$2" i=0
    while [ "$i" -lt "$MAX_WAIT" ]; do
        port_open "$port" && return 0
        i=$((i + 1))
        sleep 0.4
    done
    echo "   ! $name never answered on port $port. See: $RUNDIR/$name.log"
    return 1
}

spawn() {
    local name="$1"; shift
    local logfile="$RUNDIR/$name.log"
    if alive "$name"; then
        echo "   $name was already running (pid $(pid_of "$name"))"
        return 0
    fi
    : > "$logfile"
    # setsid: own process group, so stopping it also takes down children (npm -> vite).
    setsid nohup "$@" >> "$logfile" 2>&1 &
    echo $! > "$RUNDIR/$name.pid"
    return 0
}

halt() {
    local name="$1" pid
    pid="$(pid_of "$name")"
    if [ -z "$pid" ]; then
        echo "   $name: was not running"
        return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "   $name: pid $pid is gone, cleaning up the file"
        rm -f "$RUNDIR/$name.pid"
        return 0
    fi
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
    local i=0
    while [ "$i" -lt 20 ] && kill -0 "$pid" 2>/dev/null; do
        i=$((i + 1)); sleep 0.2
    done
    if kill -0 "$pid" 2>/dev/null; then
        echo "   $name didn't stop nicely; forcing it"
        kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null
    fi
    rm -f "$RUNDIR/$name.pid"
    echo "   $name stopped (pid $pid)"
}

# ------------------------------------------------------------------ commands

cmd_start() {
    local mode="${1:-prod}"

    command -v python3 >/dev/null || { echo "Can't find python3."; exit 1; }

    if [ "$mode" != "dev" ]; then
        if [ ! -f "$ROOT/ui/dist/index.html" ]; then
            echo "The UI isn't built. Building it now (only happens once)..."
            command -v npm >/dev/null || { echo "Can't find npm: install Node 18+."; exit 1; }
            ( cd "$ROOT/ui" && npm install --silent && npm run build ) || {
                echo "The UI build failed."; exit 1; }
        fi
    fi

    if ! alive backend && port_open "$BACK_PORT"; then
        if reclaim backend "$BACK_PORT"; then
            echo "   backend was already up"
        else
            echo "! Port $BACK_PORT is taken by something that isn't ours."
            echo "  Use another:  BACK_PORT=8888 bash run.sh start"
            exit 1
        fi
    fi

    echo "Starting..."
    spawn backend python3 "$ROOT/server.py" --port "$BACK_PORT"
    wait_for_port "$BACK_PORT" backend || exit 1
    echo "   backend   pid $(pid_of backend)  http://127.0.0.1:$BACK_PORT"

    if [ "$mode" = "dev" ]; then
        command -v npm >/dev/null || { echo "Can't find npm: install Node 18+."; exit 1; }
        [ -d "$ROOT/ui/node_modules" ] || ( cd "$ROOT/ui" && npm install --silent )
        if ! alive front && port_open "$FRONT_PORT"; then
            echo "! Port $FRONT_PORT is already taken."
            exit 1
        fi
        spawn front npm --prefix "$ROOT/ui" run dev -- \
            --port "$FRONT_PORT" --strictPort
        wait_for_port "$FRONT_PORT" front || exit 1
        echo "   front     pid $(pid_of front)  http://127.0.0.1:$FRONT_PORT  (hot reload)"
        echo
        echo "Open:  http://127.0.0.1:$FRONT_PORT"
        echo "(vite proxies /api to the backend; edit ui/src and it reloads)"
    else
        echo
        echo "Open:  http://127.0.0.1:$BACK_PORT"
    fi
    echo "Stop:  bash run.sh stop"
}

cmd_stop() {
    echo "Stopping..."
    reclaim front "$FRONT_PORT" >/dev/null 2>&1 || true
    reclaim backend "$BACK_PORT" >/dev/null 2>&1 || true
    halt front
    halt backend
}

cmd_status() {
    local any=0
    for s in backend front; do
        local port; [ "$s" = "backend" ] && port="$BACK_PORT" || port="$FRONT_PORT"
        reclaim "$s" "$port" >/dev/null 2>&1 || true
        if alive "$s"; then
            any=1
            if port_open "$port"; then
                echo "  $s: running (pid $(pid_of "$s")), answering on $port"
            else
                echo "  $s: process alive (pid $(pid_of "$s")) but port $port is NOT answering"
                echo "      check $RUNDIR/$s.log"
            fi
        else
            echo "  $s: stopped"
        fi
    done
    [ "$any" = "1" ] || echo "  (nothing running: bash run.sh start)"
}

cmd_logs() {
    local files=()
    for s in backend front; do
        [ -f "$RUNDIR/$s.log" ] && files+=("$RUNDIR/$s.log")
    done
    if [ "${#files[@]}" -eq 0 ]; then
        echo "No logs yet."
        exit 0
    fi
    echo "Ctrl+C to quit."
    tail -n 40 -f "${files[@]}"
}

case "${1:-start}" in
    start)   cmd_start "${2:-prod}" ;;
    stop)    cmd_stop ;;
    status)  cmd_status ;;
    restart) cmd_stop; echo; cmd_start "${2:-prod}" ;;
    logs)    cmd_logs ;;
    *)
        echo "Usage: bash run.sh {start [dev] | stop | status | restart [dev] | logs}"
        exit 1 ;;
esac
