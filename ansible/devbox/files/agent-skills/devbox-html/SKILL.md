---
name: devbox-html
description: Publish simple HTML artifacts, reports, live notes, static files, or small web apps from the devbox so they can be opened from a Mac at http://devbox/relative-path. Use when a user asks to create an HTML page, dashboard, visual report, static artifact, or browser-viewable output on the devbox.
---

# Devbox HTML

Use `~/public_html` as the public web root for lightweight browser artifacts on the devbox.

## Workflow

1. Pick a stable relative path, for example `reports/status.html` or `ideas/demo/index.html`.
2. Run `devbox-html path <relative-path>` to get the full file path and create parent directories.
3. Write the HTML file and any local assets under the same `~/public_html` tree.
4. Run `devbox-html url <relative-path>` and report that URL to the user.
5. If the user wants it opened on the Mac, run `devbox-html open <relative-path>`.

Example:

```bash
out="$(devbox-html path reports/status.html)"
cat >"$out" <<'HTML'
<!doctype html>
<meta charset="utf-8">
<title>Status</title>
<h1>Status</h1>
<p>Hello from the devbox.</p>
HTML
devbox-html url reports/status.html
```

## Rules

- URLs are direct paths: `~/public_html/reports/status.html` maps to `http://devbox/reports/status.html`.
- `/usage.html` is reserved for the Claude and Codex usage dashboard.
- Use self-contained HTML when practical. If assets are needed, place them next to the HTML file or in a subdirectory under `~/public_html`.
- Do not put secrets, auth tokens, private logs, credentials, kubeconfigs, SSH keys, or sensitive transcript content under `~/public_html`.
- If `http://devbox/...` is not reachable, still create the file and share the URL. The VM may need its next normal restart before LAN port 80 is active.
