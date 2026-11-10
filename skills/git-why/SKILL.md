---
name: git-why
description: Explains WHY a piece of code exists by digging through git history — blame, line history, pickaxe searches, commit messages, linked PRs/issues and co-changed files — and returns a cited verdict on whether it's safe to change or delete. Use this whenever the user asks "why is this here", "why was this added", "who wrote this and why", "what does this weird line do", "is it safe to remove this", "when did this change", "what broke X", or points at a strange magic number, workaround, commented-out block, odd config value, TODO/HACK, or suspicious condition and wants to understand its origin — even if they never mention git. Also use before refactoring or deleting legacy code the user doesn't understand.
---

# git-why — Code Archaeologist

Developers constantly hit code that looks wrong: a `sleep(37)`, a retry loop that skips the third attempt, a commented-out block nobody dares delete. Reading the code alone tells you *what* it does; the *why* lives in history — the commit that introduced it, the bug it fixed, the PR discussion, the revert that came after. Your job is to recover that story and turn it into a decision the user can act on.

The guiding principle: **every claim must point at evidence** (a commit hash, a PR, an issue, a line). A confident guess that turns out wrong is worse than "the history doesn't say", because the user may delete a load-bearing workaround on the strength of it.

## Workflow

### 1. Pin down the target

Figure out exactly what the user is asking about — a file + line range, a function, or a literal string (magic number, flag name, error message). If they pasted a snippet without a location, find it with a search (`git grep -n "<snippet>"`). If several places match, pick the one that fits their context or ask.

Check you're in a git repo (`git rev-parse --show-toplevel`). If not, say that history is needed and stop — don't invent a backstory from the code.

### 2. Collect evidence with the bundled script

Run `scripts/dig.py` (Python 3, read-only; it only calls git). It produces a markdown evidence dossier: current code, blame, every commit that changed the region, the commit that first introduced a string, commit bodies, PR/issue/ticket references, reverts, and files that tend to change alongside.

```bash
python <skill-dir>/scripts/dig.py path/to/file.py --lines 120,134
python <skill-dir>/scripts/dig.py path/to/file.py --function retry_upload
python <skill-dir>/scripts/dig.py path/to/file.py --lines 88 --pattern "timeout=37"
python <skill-dir>/scripts/dig.py --pattern "LEGACY_AUTH_FALLBACK"          # whole repo
```

Run it from inside the repo (or pass `--repo`). Combine `--lines` with `--pattern` when there's a distinctive literal — blame tells you who touched the line *last* (often a formatter or rename), while the pickaxe finds who *introduced* the value, which is usually the real answer. If you don't pass `--pattern`, the script automatically pickaxes on the region's most distinctive comment, since comments survive reformatting and usually arrive with the original change.

What the dossier already does for you, so you don't redo it by hand:
- Tags formatter, rename and typing sweeps as `likely noise` and keeps their PR numbers out of the follow-up list.
- For the origin commit, shows the **merge it landed through** (usually `Merge pull request #N`) and the **commits just before it** on that file. Earlier attempts and their messages often explain the final shape.
- Greps CHANGELOG/HISTORY/NEWS files for the function or pattern. Release notes often record the user-facing reason, or a CVE, that the commit message leaves out.

If the dossier warns about a shallow clone, tell the user the answer may be incomplete and suggest `git fetch --unshallow`.

### 3. Dig deeper where the dossier points

The dossier is a starting point. Follow the leads that matter:

- **Look through noise commits.** If blame lands on a formatting, rename, lint, or "move files" commit, it's not the origin. Re-blame from its parent: `git blame -w -C -C -L <range> <sha>^ -- <old-path>`. The script already ignores whitespace and detects moves, but large refactors still hide origins.
- **Formatters change the literal, too.** A formatter like black rewrites `'ISO-8859-1'` as `"ISO-8859-1"`, so pickaxe on the exact current text finds only the formatting commit. Search on the bare value without quotes (`-S "ISO-8859-1"`) or with a regex that allows either quote (`-G "['\"]ISO-8859-1['\"]"`).
- **Read the diff of the introducing commit** (`git show <sha> -- <file>`) — the surrounding changes often reveal intent (a test added alongside, a config bumped at the same time).
- **Follow references.** For `#123` style refs, if `gh` is available and the remote is GitHub, run `gh pr view 123 --comments` (or `gh issue view 123 --comments`). **Also read the inline review comments**: `gh api repos/{owner}/{repo}/pulls/123/comments`. `gh pr view` leaves them out, and the real design debate ("should we keep the header on upgrade?") is often only there. If `gh` isn't available or the repo isn't on GitHub, list the refs for the user to open.
- **Find the PR for a bare commit.** If the dossier shows no merge (for example a rebase workflow, or a commit pushed straight to main), try `gh pr list --search <sha> --state merged`.
- **Search for the commit hash itself.** Maintainers often explain a terse commit in a comment elsewhere ("This should be resolved with 09fd857"). Run `gh search issues <sha7> --repo <owner>/<repo>` and `gh search prs <sha7> --repo <owner>/<repo>`, where `<sha7>` is **exactly the first 7 characters** (`git rev-parse --short=7 <sha>`). GitHub search matches whole words, so an 8-character or full hash won't find a comment that pasted 7 characters, and that's the length people usually paste. If nothing turns up, try the full 40-character hash too. This matters most for reverts, whose message rarely says why.
- **Check whether the idea was tried before.** When the user plans to add or change something, pickaxe for the obvious names of their idea (`git log -S "trusted_domain"`, `-S "allow_redirect_auth"`), and look for reverts on the same file. A feature that was merged and then reverted is the most important thing you can tell them.
- **Check tests.** `git log --format='%h %s' -S "<name>" -- '*test*'` or grep tests for the symbol — a regression test named after a bug is strong evidence the code is load-bearing.
- **Show what would break.** When the user wants to delete or change the code, run the tests that cover it (`pytest -k <name>`, `go test -run <name>`, and so on). If you want to show the effect of the change, apply it in a throwaway copy, never in the user's tree. "This test fails" is stronger evidence than "this test exists".
- **Check for reverts and churn.** A value that was changed, reverted, and changed back means someone learned the hard way. Say so.

Stop digging once you can answer confidently or once the trail goes cold — don't run dozens of commands for a simple question.

### 4. Deliver the verdict

Use this structure (keep it tight — most answers fit on one screen):

```markdown
## 🏺 Why this code exists

**Short answer:** <one or two sentences — the actual reason, in plain words>

**Origin:** `<short-sha>` by <author>, <date> — "<commit subject>"
<one line on what that commit was doing>

**Timeline**
- <date> `<sha>` — <what happened and why it matters>
- <date> `<sha>` — ...
(only commits that change the story; skip noise)

**Evidence**
- <quote or paraphrase from commit message / PR / issue, with its ref>
- <test that covers it, related files that change together, etc.>

**Safe to change?** ✅ Likely safe / ⚠️ Proceed with care / 🛑 Load-bearing
<why, and what to check or test before touching it>

**Confidence:** High / Medium / Low — <what the confidence rests on, and what's missing>
```

(Drop the emoji if the user's environment or style avoids them; the structure is what matters.)

Guidance on the verdict:

- **Load-bearing (🛑)** when there's a linked bug, a regression test, a revert after an earlier removal attempt, or a comment/PR describing a production incident.
- **Proceed with care (⚠️)** when the reason is plausible but undocumented, or when the code touches external systems (APIs, payment, auth, data migrations) where breakage shows up late.
- **Likely safe (✅)** when the history shows it's dead (the caller was removed, the feature flag was retired, the bug it worked around was fixed upstream and the dependency bumped).
- Separate **what the history says** from **your inference**. Phrases like "the commit message says…" vs "this suggests…" let the user calibrate.
- If history genuinely doesn't explain it (message is "fix", "wip", no refs, author long gone), say so plainly, give your best inference from the diff and surrounding code labelled as inference, and suggest who to ask (most frequent author of that area: `git shortlog -sn -- <file>`).

## Privacy and safety

- Use author *names* from git, not email addresses — the dossier strips emails for this reason; don't re-add them.
- Everything here is read-only. Never run commands that rewrite history, check out other branches, or modify the working tree while investigating. If you need to view an old version, use `git show <sha>:<path>`.

## Reference

For more techniques (searching by regex with `-G`, tracing across file renames, `git bisect` for "when did this behaviour change", finding deleted code, reading merge commits), see `references/git-techniques.md`. Read it when the standard workflow above doesn't find the origin.
