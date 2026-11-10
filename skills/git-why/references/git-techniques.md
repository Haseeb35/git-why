# Git archaeology techniques

Extra techniques for when the main workflow in SKILL.md doesn't find the origin. All commands are read-only.

## Contents
1. Finding when a string or pattern appeared
2. Tracing through renames and moves
3. Seeing past refactors and formatting commits
4. Finding deleted code
5. "When did this behaviour change?" (bisect)
6. Merge commits and PR context
7. Who knows this area?

---

## 1. Finding when a string or pattern appeared

- `git log -S "exact string" --reverse --format='%h %ad %an %s' --date=short` — commits where the *count* of that string changed. The first result is usually the introduction.
- `git log -G "regex" --reverse ...` — commits whose diff has a line matching the regex. It's slower but catches edits that keep the count the same, such as changing `timeout=30` to `timeout=37`. Use `-G "timeout\s*=\s*\d+"`.
- Add `-- path/` to limit to a directory. Add `--all` to include other branches.
- `git log -S "x" --pickaxe-all` shows every file in matching commits, which is useful for seeing what changed alongside.

## 2. Tracing through renames and moves

- `git log --follow --format='%h %ad %s' --date=short -- path/to/file` follows a single file across renames.
- `git log --follow --diff-filter=R --name-status -- path` shows only the rename events and the old names.
- Once you know the old path, run blame and pickaxe against the old path at an older commit: `git blame <sha> -- old/path.py`.
- `git blame -C -C -C` detects lines copied from *any* file in any commit. It's expensive, so use it on small ranges.

## 3. Seeing past refactors and formatting commits

- `git blame -w` ignores whitespace, and `-M` / `-C` detect moved or copied lines.
- If the repo has `.git-blame-ignore-revs`, use it: `git blame --ignore-revs-file .git-blame-ignore-revs ...`.
- To skip a specific noisy commit manually: `git blame --ignore-rev <sha> -L a,b -- file`.
- To re-blame from before a commit: `git blame -L a,b <sha>^ -- file`. Line numbers may shift, so search for the content first with `git show <sha>^:file | grep -n "snippet"`.

## 4. Finding deleted code

- "This used to exist — where did it go?": `git log -S "functionName" --format='%h %ad %s' --date=short` and look at the most recent hit, which is the removal.
- `git log --diff-filter=D --name-only --format='%h %s' -- '**/name*'` finds deleted files.
- View the old content with `git show <sha>^:path/to/deleted_file`.

## 5. "When did this behaviour change?" (bisect)

When there's no string to search for, only a behaviour ("this used to return 200"), `git bisect` finds the commit. It **checks out commits**, which changes the working tree. Only suggest it, or run it only with the user's explicit OK, and only when the working tree is clean. A safe pattern is to bisect in a separate worktree:

```bash
git worktree add ../bisect-tmp HEAD
cd ../bisect-tmp && git bisect start <bad> <good> && git bisect run <test-command>
git bisect reset && cd - && git worktree remove ../bisect-tmp
```

## 6. Merge commits and PR context

- `git log --merges --ancestry-path <sha>..HEAD --format='%h %s' | tail -1` finds the merge that brought a commit into the current branch. Its subject often contains the PR number ("Merge pull request #412 from ...").
- Squash-merged repos usually have `(#123)` at the end of the commit subject.
- With GitHub CLI:
  - `gh pr list --search <sha> --state merged` finds the PR that contains a commit.
  - `gh pr view <n> --comments` shows the description and review discussion.
  - `gh api repos/{owner}/{repo}/commits/<sha>/pulls` does the same lookup through the API.

## 7. Who knows this area?

- `git shortlog -sn -- path/` lists authors ranked by commit count for a path.
- `git shortlog -sn --since="1 year ago" -- path/` shows who has been active there recently.
- Suggest the user ask the top recent author. Don't contact anyone yourself.
