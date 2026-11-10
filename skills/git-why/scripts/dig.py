#!/usr/bin/env python3
"""
dig.py - collect git history evidence for a piece of code.

Gathers blame, line-history, pickaxe (string introduction) results, commit
messages, issue/PR references and co-changed files into one markdown
"evidence dossier" that Claude can reason over.

Usage:
  python dig.py FILE --lines 40,55            # who/why for a line range
  python dig.py FILE --lines 40               # a single line
  python dig.py FILE --function parse_config  # a function (git's funcname matching)
  python dig.py --pattern "MAX_RETRIES = 7"   # when did this string appear/disappear (whole repo)
  python dig.py FILE --pattern "timeout=37"   # same, limited to one file

Options:
  --repo PATH         repository root or any path inside it (default: cwd)
  --max-commits N     cap on commits shown in detail (default: 12)

Only reads from git. Never modifies the repository.
"""

import argparse
import os
import re
import subprocess
import sys
from collections import Counter, OrderedDict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SEP = "\x1f"  # field separator unlikely to appear in commit text
REC = "\x1e"  # record separator

REF_PATTERNS = [
    ("PR/issue", re.compile(r"(?<![\w/])#(\d{1,6})\b")),
    ("PR/issue", re.compile(r"\bGH-(\d{1,6})\b")),
    ("ticket", re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d{1,6})\b")),
    ("link", re.compile(r"https?://[^\s)>\]]+")),
]
TRAILER_RE = re.compile(r"^(Co-authored-by|Reviewed-by|Signed-off-by|Fixes|Closes|Resolves|Refs?|See-also)\s*:\s*(.+)$",
                        re.IGNORECASE | re.MULTILINE)
REVERT_RE = re.compile(r'^Revert "|This reverts commit ([0-9a-f]{7,40})', re.MULTILINE)
EMAIL_RE = re.compile(r"\s*<[^>]+@[^>]+>")


def git(args, repo, check=True):
    proc = subprocess.run(["git", "-C", repo] + args, capture_output=True,
                          encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout


def repo_root(path):
    try:
        return git(["rev-parse", "--show-toplevel"], path).strip()
    except RuntimeError:
        sys.exit(f"error: {os.path.abspath(path)} is not inside a git repository.")


def is_shallow(repo):
    return git(["rev-parse", "--is-shallow-repository"], repo, check=False).strip() == "true"


def rel_to_root(root, file_arg):
    absolute = os.path.abspath(file_arg)
    rel = os.path.relpath(absolute, root)
    return rel.replace(os.sep, "/")


# ---------------------------------------------------------------- collectors

def blame_range(repo, path, start, end):
    """Return (Counter of commit -> line count, dict commit -> summary, list of current lines)."""
    out = git(["blame", "-w", "-M", "-C", "-C", "--line-porcelain", "-L", f"{start},{end}", "--", path], repo)
    counts, summaries, lines = Counter(), {}, []
    current = None
    for raw in out.splitlines():
        if re.match(r"^[0-9a-f]{40} ", raw):
            current = raw.split()[0]
            counts[current] += 1
        elif raw.startswith("summary ") and current:
            summaries[current] = raw[len("summary "):]
        elif raw.startswith("\t"):
            lines.append(raw[1:])
    return counts, summaries, lines


def line_history(repo, path, spec):
    """Commits that touched a line range or function, newest first (git log -L)."""
    out = git(["log", f"-L{spec}:{path}", "-s", "--format=%H"], repo, check=False)
    seen = OrderedDict()
    for line in out.splitlines():
        line = line.strip()
        if re.fullmatch(r"[0-9a-f]{40}", line):
            seen[line] = True
    return list(seen)


def pickaxe(repo, pattern, path=None):
    """Commits where the number of occurrences of `pattern` changed, oldest first."""
    # note: --follow is incompatible with --reverse, so reverse in Python instead
    args = ["log", "-S", pattern, "--format=%H"]
    if path:
        args += ["--follow", "--", path]
    out = git(args, repo, check=False)
    hits = [l.strip() for l in out.splitlines() if re.fullmatch(r"[0-9a-f]{40}", l.strip())]
    return hits[::-1]


def file_origin(repo, path):
    out = git(["log", "--follow", "--diff-filter=A", "--format=%H", "--", path], repo, check=False)
    hashes = [l for l in out.split() if l]
    return hashes[-1] if hashes else None


def find_function(abs_path, name):
    """Best-effort (start, end) line range of a function/method/class definition.

    Works for indentation-based and brace-based languages: the block ends just
    before the next non-blank line indented at or below the definition (a
    closing brace at that indent is included).
    """
    try:
        with open(abs_path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None
    n = re.escape(name)
    def_rx = re.compile(
        rf"^(\s*)(?:export\s+|public\s+|private\s+|protected\s+|static\s+|async\s+|pub\s+|def\s+|fn\s+|func\s+|function\s+|class\s+|sub\s+)*"
        rf"(?:def|fn|func|function|class|sub|interface|struct)\s+(?:\([^)]*\)\s*)?{n}\b"
        rf"|^(\s*)(?:export\s+)?(?:const|let|var)\s+{n}\s*=\s*(?:async\s*)?(?:function|\()"
        rf"|^(\s*)(?:[\w<>\[\],]+\s+)+{n}\s*\([^;]*$"  # C/Java/C# style signature
    )
    for i, line in enumerate(lines):
        m = def_rx.match(line)
        if not m:
            continue
        indent = len(next(g for g in m.groups() if g is not None) or "")
        end = i
        for j in range(i + 1, len(lines)):
            text = lines[j]
            if not text.strip():
                continue
            cur = len(text) - len(text.lstrip())
            if cur <= indent:
                if text.strip()[:1] in "})]" or text.strip().startswith("end"):
                    end = j
                break
            end = j
        return i + 1, end + 1
    return None


NOISE_RE = re.compile(
    r"\b(format(ting)?|reformat|black|prettier|isort|ruff|lint(ing)?|style|whitespace|"
    r"rename[sd]?|move[sd]?|typ(es|ing|e hints|e annotations)|inline types|codemod|"
    r"bump|upgrade deps|license header|copyright)\b", re.IGNORECASE)
COMMENT_RE = re.compile(r"^\s*(#|//|/\*|\*|--|;|<!--)\s?(.*)$")


def extract_refs(text):
    refs = []
    for kind, rx in REF_PATTERNS:
        for m in rx.finditer(text):
            val = m.group(0)
            # skip things that look like tickets but are standards (UTF-8, ISO-8601, SHA-256 ...)
            if kind == "ticket" and re.match(r"^(UTF|ISO|SHA|RFC|MD|AES|HTTP|TLS|X)-", val):
                continue
            if val not in refs:
                refs.append(val)
    return refs


def landing_merge(repo, sha):
    """The mainline merge commit that brought `sha` into HEAD (usually the PR merge), if any."""
    # Only a merge whose *side* branch brought the commit in counts: the commit
    # must be reachable from the merge but not from its first parent. Otherwise
    # a commit pushed straight to main would be credited to whatever unrelated
    # PR happened to be merged next.
    candidates = git(["rev-list", "--merges", "--ancestry-path", "--reverse", f"{sha}..HEAD"],
                     repo, check=False).split()
    m = None
    for cand in candidates[:200]:
        on_first_parent = subprocess.run(
            ["git", "-C", repo, "merge-base", "--is-ancestor", sha, f"{cand}^1"],
            capture_output=True).returncode == 0
        if not on_first_parent:
            m = cand
            break
        # once the commit is on the mainline of an earlier merge, later merges can't have introduced it
        break
    if not m:
        return None
    fmt = SEP.join(["%h", "%ad", "%s", "%b"])
    short, date, subject, body = git(["show", "-s", "--date=short", f"--format={fmt}", m], repo).split(SEP, 3)
    return {"short": short, "date": date, "subject": subject.strip(), "refs": extract_refs(subject + "\n" + body)}


def predecessors(repo, sha, files, current_path, n=3):
    """Earlier commits to the same file before `sha` — earlier attempts often explain the final version."""
    base = current_path.rsplit("/", 1)[-1]
    old = next((f.split("\t")[-1] for f in files if f.split("\t")[-1].rsplit("/", 1)[-1] == base), None)
    if not old:
        return []
    fmt = SEP.join(["%h", "%ad", "%an", "%s"])
    out = git(["log", f"-{n}", "--date=short", f"--format={fmt}", f"{sha}^", "--", old], repo, check=False)
    rows = []
    for line in out.splitlines():
        parts = line.split(SEP)
        if len(parts) == 4:
            rows.append(parts)
    return rows


def distinctive_comment(lines):
    """Longest comment line in the region — a great pickaxe target because comments rarely get reformatted."""
    best = ""
    for l in lines:
        m = COMMENT_RE.match(l)
        if m:
            txt = m.group(2).strip().rstrip("*/").strip()
            if len(txt) > len(best) and len(txt) >= 20:
                best = txt
    return best[:80] or None


def commit_details(repo, sha):
    fmt = SEP.join(["%H", "%h", "%ad", "%an", "%P", "%s", "%b"]) + REC
    out = git(["show", "-s", "--date=short", f"--format={fmt}", sha], repo)
    h, short, date, author, parents, subject, body = out.rstrip(REC + "\n").split(SEP, 6)
    files = git(["show", "--format=", "--name-status", "-M", sha], repo, check=False).strip().splitlines()
    text = subject + "\n" + body
    refs = extract_refs(text)
    trailers = [f"{k}: {EMAIL_RE.sub('', v).strip()}" for k, v in TRAILER_RE.findall(body)]
    revert = REVERT_RE.search(text)
    return {
        "sha": h, "short": short, "date": date, "author": author,
        "merge": len(parents.split()) > 1, "subject": subject.strip(),
        "body": EMAIL_RE.sub("", body).strip(), "files": files, "refs": refs,
        "trailers": trailers, "revert": bool(revert),
        # big sweeping commits (formatters, renames, typing passes) rarely explain *why*
        "noise": bool(NOISE_RE.search(subject)) or len(files) > 25,
    }


# ---------------------------------------------------------------- rendering

def render_commit(c, label=None, max_body=1200, max_files=12):
    out = []
    tag = f" — **{label}**" if label else ""
    flags = []
    if c["merge"]:
        flags.append("merge")
    if c["revert"]:
        flags.append("revert")
    if c.get("noise"):
        flags.append("likely noise: formatting/rename/sweep")
    flag_txt = f" `[{', '.join(flags)}]`" if flags else ""
    out.append(f"### `{c['short']}` {c['date']} · {c['author']}{tag}{flag_txt}")
    out.append(f"**{c['subject']}**")
    if c["body"]:
        body = c["body"]
        if len(body) > max_body:
            body = body[:max_body].rstrip() + " …[truncated]"
        out.append("")
        out.append("> " + body.replace("\n", "\n> "))
    if c["refs"]:
        out.append(f"\nReferences: {', '.join(c['refs'])}")
    if c["trailers"]:
        out.append(f"Trailers: {'; '.join(c['trailers'])}")
    if c["files"]:
        shown = c["files"][:max_files]
        more = len(c["files"]) - len(shown)
        out.append("\nFiles changed: " + ", ".join(f"`{f.replace(chr(9), ' ')}`" for f in shown)
                   + (f" … +{more} more" if more > 0 else ""))
    out.append("")
    return "\n".join(out)


def co_change(details, target):
    # skip the target itself, including its older paths from before renames
    base = target.rsplit("/", 1)[-1]
    counter = Counter()
    for c in details:
        for f in c["files"]:
            name = f.split("\t")[-1]
            if name.rsplit("/", 1)[-1] != base:
                counter[name] += 1
    return [(n, k) for n, k in counter.most_common(8) if k >= 2]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?", help="file to investigate (relative to cwd or repo)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--lines", help="START[,END] line range")
    g.add_argument("--function", help="function name (uses git log -L :name:file)")
    ap.add_argument("--pattern", help="string to trace with git's pickaxe (-S)")
    ap.add_argument("--repo", default=".", help="path inside the repository")
    ap.add_argument("--max-commits", type=int, default=12)
    a = ap.parse_args()

    if not a.file and not a.pattern:
        ap.error("give a FILE (with --lines/--function) and/or --pattern")

    root = repo_root(a.repo)
    path = None
    if a.file:
        candidate = a.file if os.path.isabs(a.file) else os.path.join(os.path.abspath(a.repo), a.file)
        if not os.path.exists(candidate):
            candidate = os.path.join(root, a.file)
        path = rel_to_root(root, candidate)
        if not os.path.exists(os.path.join(root, path)):
            sys.exit(f"error: {a.file} not found in {root}")

    print(f"# Evidence dossier\n")
    print(f"- Repository: `{os.path.basename(root)}`")
    target_desc = path or "(whole repository)"
    if a.lines:
        target_desc += f" lines {a.lines}"
    if a.function:
        target_desc += f" function `{a.function}`"
    if a.pattern:
        target_desc += f" pattern `{a.pattern}`"
    print(f"- Target: {target_desc}")
    head = git(["log", "-1", "--format=%h %ad", "--date=short"], root, check=False).strip()
    print(f"- HEAD: {head}")
    if is_shallow(root):
        print("- ⚠️ **Shallow clone**: history is truncated; oldest commits may be missing. "
              "Run `git fetch --unshallow` for full answers.")
    print()

    ordered, labels = [], {}

    def add(sha, label=None):
        if sha not in labels:
            ordered.append(sha)
            labels[sha] = []
        if label and label not in labels[sha]:
            labels[sha].append(label)

    # --- blame / line history
    if path and a.function:
        # Resolve the function to a concrete line range ourselves: git's own
        # funcname matching only works for languages the repo configures in
        # .gitattributes, which most repos don't.
        rng = find_function(os.path.join(root, path), a.function)
        if rng:
            a.lines = f"{rng[0]},{rng[1]}"
            print(f"_Function `{a.function}` found at lines {rng[0]}–{rng[1]}._\n")
        else:
            print(f"_Could not find a definition of `{a.function}` in {path}; try --lines instead._\n")
            a.function = None

    if path and a.lines:
        if a.lines:
            parts = a.lines.split(",")
            start = int(parts[0])
            end = int(parts[1]) if len(parts) > 1 else start
            spec = f"{start},{end}"
            try:
                counts, summaries, lines = blame_range(root, path, start, end)
            except RuntimeError as e:
                sys.exit(f"error running blame: {e}")
            print("## Current code\n")
            print("```")
            for i, l in enumerate(lines, start):
                print(f"{i:>5}  {l}")
            print("```\n")
            print("## Blame (who last touched these lines; whitespace & moves ignored)\n")
            for sha, n in counts.most_common():
                print(f"- `{sha[:8]}` — {n} line(s) — {summaries.get(sha, '')}")
                add(sha, "last touched")
            print()
            if not a.pattern:
                auto = distinctive_comment(lines)
                if auto:
                    a.pattern = auto
                    print(f"_Auto-pickaxe on the region's most distinctive comment: `{auto}`_\n")
        hist = line_history(root, path, spec)
        if hist:
            print(f"## Line history ({len(hist)} commit(s) changed this region, newest first)\n")
            print(", ".join(f"`{h[:8]}`" for h in hist))
            print()
            for h in hist:
                add(h)
            add(hist[-1], "introduced region")

    # --- pickaxe
    if a.pattern:
        hits = pickaxe(root, a.pattern, path)
        if hits:
            print(f"## Pickaxe: commits that added/removed `{a.pattern}` (oldest first)\n")
            print(", ".join(f"`{h[:8]}`" for h in hits))
            print()
            add(hits[0], "first introduced pattern")
            if len(hits) > 1:
                add(hits[-1], "latest add/remove of pattern")
            for h in hits[1:-1]:
                add(h)
        else:
            print(f"## Pickaxe\n\nNo commit ever added or removed `{a.pattern}` "
                  f"(it may be uncommitted, or spelled differently in history).\n")

    if path:
        origin = file_origin(root, path)
        if origin:
            add(origin, "file created")

    if not ordered:
        print("No commits found for this target.")
        return

    # keep labelled commits, then fill with the rest up to the cap
    labelled = [s for s in ordered if labels[s]]
    rest = [s for s in ordered if not labels[s]]
    chosen = labelled + rest[: max(0, a.max_commits - len(labelled))]
    skipped = len(ordered) - len(chosen)

    details = [commit_details(root, s) for s in chosen]
    details.sort(key=lambda c: c["date"])

    origin_labels = {"introduced region", "first introduced pattern"}
    print("## Commit details (chronological)\n")
    for c in details:
        lab = labels.get(c["sha"], [])
        print(render_commit(c, ", ".join(lab) or None))
        if c["noise"]:
            continue
        # for origin commits, find the PR merge and earlier attempts: commit
        # messages are often terse, while the PR and its predecessors hold the why
        if origin_labels & set(lab) or (c is details[0] and not c["noise"]):
            lm = landing_merge(root, c["sha"])
            if lm:
                refs = f" — refs: {', '.join(lm['refs'])}" if lm["refs"] else ""
                print(f"↳ Landed via merge `{lm['short']}` {lm['date']}: {lm['subject']}{refs}")
                for r in lm["refs"]:
                    if r not in c["refs"]:
                        c["refs"].append(r)
            if path:
                pre = predecessors(root, c["sha"], c["files"], path)
                if pre:
                    print("↳ Earlier commits to this file just before it (earlier attempts often explain the final version):")
                    for short, date, author, subj in pre:
                        r = extract_refs(subj)
                        print(f"  - `{short}` {date} · {author} — {subj}")
                        for x in r:
                            if x not in c["refs"]:
                                c["refs"].append(x)
            print()
    if skipped:
        print(f"_{skipped} more commit(s) omitted; raise --max-commits to see them._\n")

    if path:
        cc = co_change(details, path)
        if cc:
            print("## Files that changed together with this code\n")
            for n, k in cc:
                print(f"- `{n}` ({k} commits)")
            print()

    all_refs, noise_refs = [], []
    for c in details:
        bucket = noise_refs if c["noise"] else all_refs
        for r in c["refs"]:
            if r not in all_refs and r not in bucket:
                bucket.append(r)
    noise_refs = [r for r in noise_refs if r not in all_refs]
    if all_refs:
        print("## References to follow up\n")
        print("The discussion behind the change usually lives here. For GitHub PRs read BOTH "
              "`gh pr view N --comments` and the inline review comments "
              "(`gh api repos/{owner}/{repo}/pulls/N/comments`):\n")
        for r in all_refs:
            print(f"- {r}")
        print()
    if noise_refs:
        print(f"_Refs from formatting/sweep commits (probably not the why): {', '.join(noise_refs)}_\n")

    # changelogs often record the user-facing reason (and CVEs) that commits omit
    if a.function or a.pattern:
        term = a.function or a.pattern
        hits = git(["grep", "-n", "-i", "-F", term, "--", "*CHANGELOG*", "*HISTORY*", "*NEWS*", "*RELEASE*"],
                   root, check=False).strip().splitlines()[:6]
        if hits:
            print("## Changelog mentions\n")
            for h in hits:
                print(f"- `{h[:200]}`")
            print()


if __name__ == "__main__":
    main()
