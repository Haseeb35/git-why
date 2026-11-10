---
tags: [skill-creator]
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

ITER_CHUNK_SIZE is 512 in src/requests/models.py which seems tiny for streaming. why is it so small? i want to bump it to 8192 for speed, any reason not to?
