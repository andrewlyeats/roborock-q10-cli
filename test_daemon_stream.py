#!/usr/bin/env python3
"""Offline regression test for the daemon stream path (added s22).

Exercises `Daemon._serve_stream` over a REAL socket pair with a bare Daemon
instance — no cloud. This is the lifecycle the old offline tests skipped, which
let two bugs ship:
  1. the head-close bug — `_send()` closed the writer right after the stream
     head, so `watch` got the head then EOF and exited with zero frames; and
  2. lazy watcher cleanup — a disconnected client was reaped only on the NEXT
     frame-write, so a dead watcher lingered under an idle robot.

Run: ./test_daemon_stream.py   (or via the conda interp; never bare python3)
"""
import asyncio
import json
import socket

import vac


async def main():
    s_srv, s_cli = socket.socketpair()
    r_srv, w_srv = await asyncio.open_connection(sock=s_srv)
    r_cli, w_cli = await asyncio.open_connection(sock=s_cli)

    d = vac.Daemon(None)
    task = asyncio.create_task(d._serve_stream({"rest": ["--raw"]}, r_srv, w_srv))

    # 1) the stream head arrives and is well-formed
    head = json.loads(await asyncio.wait_for(r_cli.readline(), 2))
    assert head.get("ok") and head.get("stream"), f"bad stream head: {head}"

    # 2) the connection STAYS OPEN after the head (the head-close bug closed it here)
    await asyncio.sleep(0.05)
    assert len(d.watchers) == 1, "stream closed right after head — head-close regression"

    # 3) a frame pushed onto the watcher queue is delivered to the client
    q = next(iter(d.watchers))
    await q.put({"time": "t", "dps": {"STATUS": 8}})
    frame = json.loads(await asyncio.wait_for(r_cli.readline(), 2))
    assert frame["dps"]["STATUS"] == 8, f"frame not delivered: {frame}"

    # 4) on client disconnect the watcher is reaped PROMPTLY (EOF reap, not next-frame)
    w_cli.close()
    for _ in range(40):                       # up to ~2s, but should be near-instant
        if not d.watchers:
            break
        await asyncio.sleep(0.05)
    assert len(d.watchers) == 0, "watcher not reaped on client EOF — lazy-cleanup regression"

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    w_srv.close()
    print("PASS: head stays open · frame delivered · watcher reaped on EOF")


if __name__ == "__main__":
    asyncio.run(main())
