# KyaniteLabs `.github`

Shared org config and workflow templates for Kyanite Labs (GitHub + Forgejo).

## Workflows

| File | Purpose |
| --- | --- |
| `ci-node.yml` | Node CI (build + test) |
| `ci-python.yml` | Python CI (install + pytest) |
| `ci-docker.yml` | Docker build (self-hosted) |

## Runner labels

| Label | Where it runs |
| --- | --- |
| `docker` | `node:22` containers |
| `self-hosted` | NUCBox host |

Org profile copy for GitHub lives in [`profile/README.md`](profile/README.md).
