---
name: studi0
description: Start studi0, the local viewer of a s0ma project's graph, and show it beside the chat or as a link. Use when someone says "show me studi0", or another s0ma skill says to show it.
---

# Start studi0 and show it

studi0 is s0ma's local viewer. It shows one s0ma project its own component
graph, every part and how they connect, read from the project's build. It
serves one page on this machine only, never runs the project, and repaints as
new builds land. While it runs it writes one small file into the project,
`.s0ma/studi0/active.json`, which says a viewer is here, and nothing else.

## 1. Is one already running for this project?

The project folder is the one with the project's `pyproject.toml`. Look for
`.s0ma/studi0/active.json` in it. studi0 writes that file once it is serving,
with the port it serves on and its process id, such as
`{"pid": 4242, "port": 5710}`, and takes it away when it stops cleanly.

A studi0 that was stopped abruptly can leave the file behind, so the file alone
proves nothing. If it is there, check that its port answers:

```bash
curl -s -o /dev/null -w '%{http_code}' http://localhost:5710/
```

with the file's port in place of 5710. A `200` means one is running: use it,
at `http://studi0.localhost:<port>/` with that port, and do not start another.
No file, or no answer, means none is running: start one.

## 2. Start it

From the project folder, as a background command, so it keeps serving while
the conversation goes on:

```bash
s0ma studi0 --no-open .
```

`--no-open` stops it opening a browser of its own: you show it yourself, in
step 3. When it starts serving, its first line names the project and the
address, and a second line gives the same address by number:

```text
studi0 serving tip-calculator at http://studi0.localhost:5710/
```

Read the address from that first line. 5710 is its own port. When another
program has that port, studi0 takes one the system assigns, says so on a third
line, and the address it prints carries the real port. Always use the address
it printed, never one you worked out.

If it prints nothing within a few seconds, or stops, read what it printed and
say so plainly. If the page says "Nothing is built yet.", build the project
first, and it repaints as soon as the build lands.

## 3. Show it

- If this session has a tool that opens a web page in a pane or preview beside
  the chat (the Claude Desktop app does), open studi0's address with that tool,
  and say it is open beside the chat.
- If it has no such tool, as in the terminal, give the address as a link.

Never open anything but studi0's own local address this way: not a page it
links to, and not any other address.

## 4. Stopping it

studi0 serves until it is stopped. When the person asks you to close it, stop
the background command you started. One started in a terminal of their own
stops with Ctrl+C. A file it leaves behind does no harm; the next studi0 to
start writes a fresh one.

## What to say about it

It shows this project's own graph, its parts and how they connect, from this
machine, and it repaints as builds land. Say nothing else about it.
