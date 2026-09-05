#!/usr/bin/python3 -I
"""Put stdin on the Wayland clipboard (or primary selection) and return at once.

usage: omapop-clipboard.py [--primary] [--type MIME]   (content on stdin, <= 8 MiB)

wl-copy keeps a background process alive to serve the selection. Launched
straight from the shell that child would keep the shell's pipes open, so this
helper reads a bounded payload, starts wl-copy in its own session with its
stdio pointed at /dev/null, hands the payload over and exits.
"""
import os
import subprocess
import sys

WL_COPY = "/usr/bin/wl-copy"
MAX_BYTES = 8 * 1024 * 1024


def main(argv):
    primary = "--primary" in argv
    mime = "text/plain;charset=utf-8"
    if "--type" in argv:
        i = argv.index("--type")
        if i + 1 < len(argv) and len(argv[i + 1]) <= 128:
            mime = argv[i + 1]
    data = sys.stdin.buffer.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        sys.stderr.write("payload too large\n")
        return 65
    cmd = [WL_COPY, "--type", mime]
    if primary:
        cmd.insert(1, "--primary")
    if not data:
        cmd.append("--clear")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if data else subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True, close_fds=True)
    if data:
        try:
            proc.stdin.write(data)
            proc.stdin.close()
        except BrokenPipeError:
            return 1
    try:
        return proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        # wl-copy normally forks and exits immediately; a hang here is unusual.
        proc.kill()
        return 124


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception:  # noqa: BLE001
        sys.exit(1)
