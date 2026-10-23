---
name: implement-spec
description: "Implement a spec's tickets in code on one integration branch, ending in one PR. Use when the user wants a whole spec or ticket group built, or the result of /to-spec and /to-tickets implemented."
---

You have been provided a spec. This spec should have tickets associated with it, describing how to implement the spec.

The issue tracker should have been provided to you. If not, tell the user to run `/setup-matt-pocock-skills`.

The goal is the entire spec implemented on a single **integration branch**, with every ticket resolved the way the issue tracker closes work.

The tickets are not a list of steps. They are a **task graph** with blocking relationships between them. This means there is always a **frontier** of tickets which are ready to be grabbed.

Communication to and from subagents should be sparse. Communicate primarily through **context pointers**: to the spec, tickets, research notes, and previous commits. Don't duplicate information already available via pointers.

**Implementer subagents** should be run in the background where possible for maximum concurrency.

## Worktree and Environment Discipline

- **Standardized Worktree Paths**: All worktrees must be placed in a standardized directory within or beside the repository: `.worktrees/<branch-name>` (e.g. `.worktrees/agent-159-developer-guardrails`, `.worktrees/agent-164-worktree-discipline`). Ensure `.worktrees/` is included in `.gitignore`.
- **Coordinator Worktree Isolation**: Coordinator agents must never modify the repository root checkout directly. Instead, create and operate within a dedicated integration worktree (e.g. `.worktrees/<integration-branch>`), keeping the developer's main working tree clean and undisturbed.
- **Execution Runner Wrappers**: Implementer and runner subagents must always invoke Python tooling and tests via project-managed wrappers (`uv run pytest`, `uv run python`) rather than bare system interpreters (`pytest`, `python3`).
- **Mandatory Worktree Cleanup**: To prevent branch locking and dangling references, every worktree must be explicitly cleaned up after its branch is merged or work completes:
  ```bash
  git worktree remove --force .worktrees/<branch-name>
  git worktree prune
  ```

## Steps

1. Read the spec and tickets to understand the task graph.

2. (optional) Use an **exploration subagent** to conduct any exploration required by the tickets - relevant codebase files or external documentation. Ensure the exploration subagent can save files - it should save its markdown notes in a directory outside the repo, accessible by all future subagents. This lets **implementer subagents** focus on implementation rather than exploration.

3. Create the integration branch and set up a dedicated integration worktree under `.worktrees/<integration-branch>`. The coordinator agent must operate strictly within this integration worktree, preventing any direct modification to the repository root checkout. If the issue tracker closes work through PRs, or the user asks for one, open a draft PR after the first merge in step 5 (a branch with no commits ahead of main can't open one). Step 8 writes its body and closing lines.

4. Use **implementer subagents** to implement each ticket, each in its own dedicated worktree on its own branch located at `.worktrees/<branch-name>`. Each implementer subagent:
   - confirms its worktree is based on the integration branch before starting, and resets onto it if not;
   - mandates invocation of all test and Python commands via project-managed wrappers (`uv run pytest`, `uv run python`) rather than bare system interpreters;
   - calls the Skill tool with `tdd` to build the ticket;
   - merges the integration branch tip into its own branch before reporting done;
   - when the ticket can't be finished, comments on the ticket with what was done and what blocks it, and reports it **unfinished**. Tickets it blocks stay off the frontier.

5. Once an **implementer subagent** completes, merge its work to the integration branch with a **merger subagent**. The merger runs `make test` and `make lint` (or `uv run pytest`) after each merge and fixes what fails in a follow-up commit. A failure there usually means two tickets built in parallel broke each other: fix the combination, keeping both sides' work. Immediately after merging, clean up the subagent's worktree using `git worktree remove --force .worktrees/<branch-name>` and `git worktree prune` to unlock the branch.

6. If this changes the **frontier** of available tickets, kick off more **implementer subagents** to work on the new tickets. This allows for maximum concurrency.

7. Once the frontier is empty and every ticket is merged or **unfinished**, call the Skill tool with `code-review` on the integration branch. Fix all issues raised by the code review in a single **implementer subagent**.

8. If a draft PR exists, call the Skill tool with `pr` to write its body: `main` is the before, the integration branch is the after. Below the body, add a `Closes #<n>` line for each finished ticket, and for the spec only when every ticket finished, then a list of **unfinished** tickets with the reason for each. Put the body on the PR and mark it ready for review. Otherwise, resolve each finished ticket the way the issue tracker closes work, and report the integration branch and the **unfinished** tickets.

9. Clean up all remaining worktrees (including implementer subagent worktrees and the coordinator integration worktree) with `git worktree remove --force .worktrees/<branch-name>` followed by `git worktree prune` to ensure no branches remain locked.
