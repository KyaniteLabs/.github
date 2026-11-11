# Changelog

All notable changes to KyaniteLabs organization defaults and shared GitHub
community health files are documented here.

## Unreleased

- Made the Agent Law provisioner's report statuses, ruleset checks and repair
  lifecycle explicit state machines, and the parity checker's pass/warn/fail
  verdict a single derived status. Report formats are unchanged.
- Fixed: a pushed repair branch with no open PR was reported as
  `compliant-after-checkout` forever instead of getting a PR.
- Fixed: the parity checker ignored empty-bodied sections, did not report
  sections missing from both files, and checked nothing when run inside `.github`.
- Added the initial changelog for organization-level governance and shared
  repository metadata.
