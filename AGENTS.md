# AGENTS.md

## What it is
Solution to a DevOps assessment: the Wisecow demo app (a bash web server that serves a `fortune` through `cowsay` on port 4499, from nyrahul/wisecow) containerized, deployed to Kubernetes with TLS through a CI/CD pipeline, plus four ops scripts. See `README.md` for the full walkthrough.

## Commands
- Run locally: `docker build -t wisecow .` then `docker run --rm -p 4499:4499 wisecow`, `curl localhost:4499`.
- Kubernetes: manifests in `k8s/` (kustomize); the README shows a kind cluster with ingress-nginx and cert-manager.
- Script tests: `python -m unittest discover scripts/tests -v`.
- Lint (same as CI): `shellcheck wisecow.sh scripts/*.sh`, hadolint on `Dockerfile` (config `.hadolint.yaml`), `kubeconform -strict -summary -ignore-missing-schemas k8s/`, `ruff check scripts/`.

## Where things live
- `wisecow.sh`: the app. `Dockerfile`, `.dockerignore`: image (non-root).
- `k8s/`: namespace, deployment, service, cert-manager issuer and certificate, ingress, `kustomization.yaml` (its `images:` entry is overridden by CI).
- `scripts/`: `system_health_monitor.sh`, `backup.sh`, `log_analyzer.py`, `app_health_checker.py`, `sample_logs/`, `tests/`.
- `.github/workflows/ci-cd.yml`: jobs `lint`, `scripts-test`, `build-push` (image to GHCR, not pushed on PRs), `deploy` (kind smoke test, main only), `deploy-cluster` (main only, runs only when the `KUBE_CONFIG` secret exists).

## Conventions
- CI runs on PRs and pushes to `main`; keep lint and tests green. Python 3.12 in CI.

## Gotchas
- DL3008 is ignored in hadolint on purpose (Debian security updates replace pinned package versions); the base image tag is pinned instead.
