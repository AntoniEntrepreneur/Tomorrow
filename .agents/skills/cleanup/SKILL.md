---
name: cleanup
description: Delete branches, worktrees and stashes whose work is on main, and Sandcastle labels whose work is closed; report work that never landed.
disable-model-invocation: true
---

PRs here merge as **squash** commits, so `git branch --merged` and `git cherry` miss almost every landed branch. Judge each branch by the evidence below, always against `origin/main`.

## 1. Sync

```bash
git fetch --prune
git merge-base --is-ancestor main origin/main && git branch -f main origin/main
```

A `main` that has diverged from `origin/main` stays as it is; note it for the report. `main` and the checked-out branch are never candidates.

## 2. Give every branch a verdict

Cover every local branch, plus every `origin` branch with no local copy. Done when each has exactly one verdict.

A branch's **linked issue** comes from its name (`sandcastle/issue-526`, `prototype/444-intro-page`, `research-581`), falling back to `#NNN` in its commit messages.

Take the first row that fits:

| Branch | Verdict | Evidence |
|---|---|---|
| Checked out in a locked or dirty worktree | **in use** | `git worktree list`, `git -C <path> status --porcelain` |
| `sandcastle/*` with a session in `.sandcastle/cache/run-state.json`, or an open batch PR | **in use** | Sandcastle resumes it on its next run |
| `prototype/*` | **prototype** | step 5 |
| Its PR is merged, with no commits after the merge | **landed** | `gh pr list --head <branch> --state merged` |
| `sandcastle/issue-*` whose issue was closed by a merged PR | **landed** | `gh issue view <n> --json closedByPullRequestsReferences` |
| No PR, and its diff is already on `origin/main` | **landed** | diff check below |
| Anything else | **unlanded** | |

**Diff check:** the branch's diff is on `origin/main` when it reverse-applies cleanly to `origin/main`'s tree. Work in a scratch directory:

```bash
git diff $(git merge-base origin/main <branch>) <branch> > <scratch>/p.diff
git archive origin/main | tar -x -C <scratch>/tree
git -C <scratch>/tree apply -R --check <scratch>/p.diff
```

Once `main` moves past a branch, this check reports **unlanded** for work that did land. That is why Sandcastle issue branches are judged by their issue instead.

## 3. Give every Sandcastle label a verdict

Cover every `sandcastle:<id>` group label (`gh label list --limit 200 --search "sandcastle:"`). The bare `sandcastle` label admits solo issues and is never a candidate. Done when each group label has exactly one verdict.

Take the first row that fits:

| Label | Verdict | Evidence |
|---|---|---|
| An open issue carries it | **in use** | `gh issue list --label <label> --state open` |
| Group `<id>` has a session in `.sandcastle/cache/run-state.json`, or a `sandcastle/batch-<id>-*` branch exists | **in use** | Sandcastle resumes the group on its next run |
| Numeric `<id>` whose spec issue `#<id>` is open | **in use** | the spec may still gain tickets |
| Anything else | **stale** | its issues and spec are closed |

## 4. Show the plan, wait for "go"

One table for branches and one for labels: name, verdict, evidence, action.

- **landed**: delete the local branch, its `origin` branch, and its worktree.
- **in use**: skip.
- **unlanded**, linked issue open or none: keep.
- **unlanded**, linked issue closed: ask in step 6.
- **prototype**: keep, or ask in step 6 (step 5 decides).
- each `git stash list` entry: ask in step 6.
- **stale** label: delete it.

The user's "go" is the only trigger for any deletion.

## 5. Prototypes

Prototype branches are kept as references and are never merged. A prototype is a candidate only when its linked issue is closed and nothing still links to the branch:

- no open issue mentions it: `gh search issues --state open '"<branch>"'`, then confirm each hit's body or comments contain the exact branch name (search splits it into words)
- no file on `origin/main` mentions it: `git grep <branch> origin/main`
- no comment on its linked issue says it is kept

Every other prototype is kept without asking.

## 6. Ask about each remaining item

Ask one item at a time. Show its linked issue and that issue's state, its last commit message, its age, and whatever still links to it. Done when every item has an answer.

- **delete**: delete the local and `origin` branch and its worktree.
- **keep**: comment on the linked issue so later runs skip it: ``Keeping `<branch>` as a reference.``
- **drop** a stash: `git stash drop`, working from the highest index down so the indexes you showed stay valid.

## 7. Delete, hand over, and report

Run everything except the local branch deletes yourself:

```bash
git worktree remove <path>
git push origin --delete <branch>   # when it exists on origin
git stash drop stash@{<n>}          # highest index first
git worktree prune
gh issue list --label <label> --state all --json number -q '.[].number'
gh label delete <label> --yes
```

Deleting a label also strips it from the closed issues that carried it, so list those issues before each `gh label delete`.


Use plain `git worktree remove`. If it refuses, the worktree is dirty: reclassify the branch as **in use** and leave it.

Local branches are the user's to delete: squash-merged branches need `git branch -D`, which `.claude/hooks/block-dangerous-git.sh` blocks for agents. End the report with one line the user pastes into the prompt, naming every branch approved for deletion:

```
! git branch -D <branch> <branch> …
```

Report:

- **Deleted:** each branch with its tip SHA (`git branch <name> <sha>` restores it), marking the local copies the paste line still has to delete; each label with its color, description, and the issues that carried it.
- **Kept:** each branch with its reason.
- **In use:** each branch and label with what is using it.
- **Unlanded:** each branch with its linked issue.
- **`main`:** fast-forwarded, already current, or diverged.
