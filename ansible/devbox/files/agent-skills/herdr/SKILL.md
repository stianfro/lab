---
name: herdr
description: Control Herdr from inside a Herdr pane. Use when HERDR_ENV=1 to inspect panes, split panes, run commands, start agents, read output, and wait for agent state.
---

# Herdr

Use this skill only when `HERDR_ENV=1`. If that variable is not set, say you are not running inside Herdr and do not try to control panes.

Herdr is a terminal multiplexer with workspaces, tabs, panes, and agent state. Use the `herdr` CLI to talk to the local Herdr socket from inside a Herdr pane.

## Safety

- Read current ids before acting. Workspace, tab, and pane ids can change after panes close.
- Prefer `--no-focus` when creating helper panes so you do not steal the user's focus.
- Use `pane read` to inspect current output. Use `wait output` or `wait agent-status` when waiting for future output or agent state.

## Discovery

```bash
herdr workspace list
herdr tab list --workspace 1
herdr pane list
herdr agent list
```

## Panes

Read a pane:

```bash
herdr pane read 1-1 --source recent --lines 80
```

Split without changing focus, then run a command:

```bash
pane_id="$(herdr pane split 1-1 --direction right --no-focus | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["pane"]["pane_id"])')"
herdr pane run "$pane_id" "just test"
```

Send text and keys:

```bash
herdr pane send-text 1-1 "hello"
herdr pane send-keys 1-1 Enter
```

Close a pane:

```bash
herdr pane close 1-3
```

## Agents

Start an agent in a sibling pane:

```bash
herdr agent start reviewer --cwd "$PWD" --split right --no-focus -- claude --model sonnet
```

Wait for an agent to finish or ask for input:

```bash
herdr wait agent-status 1-2 --status done --timeout 120000
herdr wait agent-status 1-2 --status blocked --timeout 120000
```

Read an agent by target:

```bash
herdr agent read reviewer --source recent --lines 100
```

## Workspaces and tabs

Create a workspace:

```bash
herdr workspace create --cwd /path/to/repo --label "repo task" --no-focus
```

Create a tab:

```bash
herdr tab create --workspace 1 --label "agents"
```

Focus when the user asked you to switch context:

```bash
herdr workspace focus 2
herdr tab focus 1:2
```
