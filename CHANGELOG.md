# Changelog

All notable changes to KyaniteLabs organization defaults and shared GitHub
community health files are documented here.

## Unreleased

- CI cost: the reusable `ci-profile` workflow now restores package-manager download
  caches (saved by branch pushes only), bounds both jobs with timeouts, and no longer
  fails on an image without node. The Blacksmith probe lists the repository through
  the API instead of cloning it. The Agent Law provisioner audit runs weekly instead
  of daily. Action bumps arrive as one grouped weekly Dependabot PR. The
  `verify-test` echo template is removed.
- Added Layer 6 structure signals to CI evidence: duplicated-line share,
  files over 800 significant lines, and Python functions over cyclomatic
  complexity 25. Pull requests print the change against main and flag a rise
  as an advisory regression. Measured with the standard library only.
- Added the initial changelog for organization-level governance and shared
  repository metadata.
