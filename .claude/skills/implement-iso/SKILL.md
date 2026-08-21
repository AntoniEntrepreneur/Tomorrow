---
name: implement-iso
description: "Implement a piece of work in an isolated worktree/branch, then push and open a PR. Use when the user wants to run /implement without conflicting with other parallel implementations."
disable-model-invocation: true
---

Given an issue/ticket reference (e.g. "#29"), run an isolated implementation end-to-end:

1. Call `EnterWorktree` with `name: implement<N>` where `<N>` is the issue number (e.g. `implement29`). This creates a fresh branch of the same name off the default branch and switches the session into it.
2. Implement the work described by the user in the spec or tickets:
   - Use /tdd where possible, at pre-agreed seams.
   - Run typechecking regularly, single test files regularly, and the full test suite once at the end.
   - Once done, use /code-review to review the work.
   - Commit your work to the branch.
3. Push the branch to the remote: `git push -u origin implement<N>`.
4. Open a pull request: `gh pr create --title "..." --body "..."` targeting the repo's default branch.
5. Call `ExitWorktree` with `action: "remove"` to delete the worktree directory.

If any step fails (failing tests, uncommitted changes, push/PR errors), stop and surface the issue instead of forcing cleanup — do not discard work.
