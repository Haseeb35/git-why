---
tags: [skill-creator, hard]
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

our api.example.com redirects downloads to files.example.com and requests strips the Authorization header so we get 401s. i'm thinking of opening a PR on requests to add a trusted_domains option to Session so auth survives redirects between our own domains. has anyone tried this before? anything in the history i should know first?
