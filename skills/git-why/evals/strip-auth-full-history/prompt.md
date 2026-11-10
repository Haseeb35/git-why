---
tags: [skill-creator, hard]
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

in src/requests/sessions.py there's this should_strip_auth method with a weird special case that lets http -> https redirects keep the Authorization header. why is that there? I want to delete it to make things stricter, is that safe?
