---
tags: [skill-creator]
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

why does should_strip_auth in src/requests/sessions.py keep the Authorization header on http to https redirects? is it safe to remove that special case?
