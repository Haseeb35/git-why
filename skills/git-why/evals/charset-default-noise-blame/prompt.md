---
tags: [skill-creator, hard]
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

in src/requests/utils.py get_encoding_from_headers returns ISO-8859-1 for any text/* response without a charset. that's why our html pages decode as mojibake. everything is utf-8 these days, why on earth is it latin-1, and can i just change it to utf-8?
