# GitHub → Forgejo mirror sync

A public repo's trunk is GitHub. Its Forgejo copy is a read-only mirror that
this sync keeps level with GitHub main. Source: fleet
`docs/proposals/GIT-CI-STRATEGY-20261123.md`, section "Mirror mechanics".

What the sync does: after the repo's trunk CI passes on a push to main, it
fast-forwards the Forgejo mirror's main to that exact commit. It never runs for
pull requests, never force-pushes, and refuses to push if Forgejo has commits
GitHub lacks (the mirror must be reconciled first).

The logic lives here: `.github/workflows/sync-forgejo.yml` (reusable workflow)
and `scripts/forgejo_sync.py` (all fail-closed checks, tested in
`tests/test_forgejo_sync.py`). Each repo carries only a small caller, because
`workflow_run` events fire only in the repo that owns the CI.

## Wiring a repo

1. **Caller file** `.github/workflows/sync-forgejo.yml`:

   ```yaml
   name: Sync Forgejo mirror
   on:
     workflow_run:
       workflows: ["CI"]          # the trunk CI's workflow name
       types: [completed]
       branches: [main]           # the trunk
   permissions:
     contents: read
     actions: read
   concurrency:
     group: sync-forgejo-main
     cancel-in-progress: false
   jobs:
     sync:
       if: vars.FORGEJO_SYNC_ACTIVE == 'true' && github.event.workflow_run.conclusion == 'success'
       uses: KyaniteLabs/.github/.github/workflows/sync-forgejo.yml@main
       with:
         trunk: main
         trigger-workflow-id: 123456789   # gh api repos/OWNER/REPO/actions/workflows
         trigger-workflow-name: CI
         trigger-workflow-path: .github/workflows/ci.yml
         required-workflows: |
           123456789:.github/workflows/ci.yml
         forgejo-repository: OWNER/REPO   # the Forgejo mirror
         downstream-workflow: none        # mirrors run no Forgejo CI
         dry-run: true                    # false once the mirror is reconciled and a token is set
       secrets: inherit
   ```

2. **Environment** `forgejo-mirror` in the GitHub repo, deployment branches
   limited to the trunk. It holds the secret `MIRROR_FORGEJO_TOKEN` and the
   variable `MIRROR_FORGEJO_USERNAME`. Only the push job uses it; pull
   requests and forks never see it. Dry runs on a public Forgejo mirror need
   no token.

3. **Activation** repo variable `FORGEJO_SYNC_ACTIVE=true`. Unset means the
   caller skips. Set it only once Forgejo main is an ancestor of GitHub main,
   or every dry run fails at the fast-forward check.

4. **Forgejo side** (Platform, admin): Actions off on the mirror (a mirror
   runs no CI; Forgejo would otherwise fall back to `.github/workflows`), no
   push mirror back to GitHub, and main protected so only the sync identity
   can push.

## Token

The design's ruling: the token belongs to a Forgejo identity that can write
only the mirror repos. A dedicated mirror user is a new credential class, so
Simon decides it. Until then callers stay on `dry-run: true`.
