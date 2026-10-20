# Wisecow on Kubernetes + DevOps scripts

Solution for the Accuknox DevOps assessment. The application is the
[Wisecow](https://github.com/nyrahul/wisecow) demo by nyrahul (a bash web server that serves a
random `fortune` through `cowsay` on port 4499); all credit for the app goes to the original
repository. This repo adds containerization, Kubernetes manifests with TLS, a CI/CD pipeline, and
four operations scripts (Problem Statement 2).

## Repository layout

```
.
├── wisecow.sh                      # the app (small fix: proper HTTP status line and headers)
├── Dockerfile / .dockerignore
├── k8s/
│   ├── namespace.yaml  deployment.yaml  service.yaml
│   ├── issuer.yaml  certificate.yaml   # cert-manager TLS
│   ├── ingress.yaml                    # nginx ingress, HTTPS only
│   └── kustomization.yaml              # `images:` entry that CI overrides
├── .github/workflows/ci-cd.yml
└── scripts/
    ├── system_health_monitor.sh  backup.sh
    ├── log_analyzer.py           app_health_checker.py
    ├── sample_logs/access.log
    └── tests/                          # python unittest suite
```

## Quick start

### Docker

```bash
docker build -t wisecow .
docker run --rm -p 4499:4499 wisecow
curl localhost:4499
```

The image is `debian:bookworm-slim` with `fortune-mod`, `fortunes-min`, `cowsay` and
`netcat-openbsd`, running as non-root uid 10001.

### Kubernetes (kind) with TLS

Prerequisites: docker, kind, kubectl.

```bash
cat > kind.yaml <<'EOF'
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    kubeadmConfigPatches:
      - |
        kind: InitConfiguration
        nodeRegistration:
          kubeletExtraArgs:
            node-labels: "ingress-ready=true"
    extraPortMappings:
      - {containerPort: 80, hostPort: 8080, protocol: TCP}
      - {containerPort: 443, hostPort: 8443, protocol: TCP}
EOF
kind create cluster --name wisecow --config kind.yaml

kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.11.2/deploy/static/provider/kind/deploy.yaml
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.15.3/cert-manager.yaml
kubectl -n ingress-nginx rollout status deploy/ingress-nginx-controller
kubectl -n cert-manager rollout status deploy/cert-manager-webhook

# build locally, load into kind, point the kustomization at it
docker build -t wisecow:local .
kind load docker-image wisecow:local --name wisecow
cd k8s && kustomize edit set image ghcr.io/OWNER/accuknox-devops-assessment=wisecow:local
kustomize build . | kubectl apply -f -
kubectl -n wisecow rollout status deploy/wisecow

curl -sk --resolve wisecow.local:8443:127.0.0.1 https://wisecow.local:8443/      # cow output
curl -si --resolve wisecow.local:8080:127.0.0.1 http://wisecow.local:8080/       # 308 redirect to https
```

(`git checkout k8s/kustomization.yaml` afterwards to undo the local image edit.)

## CI/CD (`.github/workflows/ci-cd.yml`)

Triggers: push to `main`, pull requests, manual `workflow_dispatch`.

| Job | What it does |
|---|---|
| `lint` | shellcheck on all `.sh`, hadolint on the Dockerfile, kubeconform on `k8s/` (cert-manager CRDs skipped), ruff on `scripts/` |
| `scripts-test` | `python -m unittest discover scripts/tests` |
| `build-push` | buildx build with GHA cache; pushes `ghcr.io/<owner>/<repo>:sha-<short>` and `:latest` on `main` (build only on pull requests) |
| `deploy` | main only. Starts a kind cluster, installs ingress-nginx and cert-manager (pinned), pulls the sha image and `kind load`s it (so package visibility does not matter), `kustomize edit set image`, applies, waits for rollout and the certificate, then smoke tests HTTPS (`--resolve wisecow.local:443:127.0.0.1`, must contain cow output) and the HTTP to HTTPS redirect |
| `deploy-cluster` | main only, optional. Runs only when the `KUBE_CONFIG` secret is set; applies the same kustomization to that cluster |

Repo settings needed:

- Actions enabled, workflow permissions allowed to write packages (the job requests `packages: write` itself).
- The GHCR package is created on first push. No visibility change is needed for CI; make it public if you want to `docker pull` it elsewhere.
- Optional: secret `KUBE_CONFIG` containing a base64 kubeconfig (`base64 -w0 ~/.kube/config`) for a real cluster. That cluster needs ingress-nginx, cert-manager and a pull path for the image (public package or an imagePullSecret).

## TLS design

cert-manager issues the certificate into secret `wisecow-tls`, which the Ingress references; the
ingress annotation `force-ssl-redirect: "true"` sends all HTTP to HTTPS.

- Local/kind: `ClusterIssuer/selfsigned` signs a certificate for `wisecow.local`. Clients use `curl -k` (or trust the cert).
- Real domain: `k8s/issuer.yaml` also defines `letsencrypt-prod` (ACME HTTP-01 via the nginx ingress). Set your e-mail, replace `wisecow.local` with your domain in `certificate.yaml` and `ingress.yaml`, and set `issuerRef.name: letsencrypt-prod`. The cluster must be reachable on port 80/443 from the internet.

## Problem Statement 2 scripts

All live in `scripts/`. Run the tests with `python3 -m unittest discover scripts/tests`
(Linux-only checks are skipped on macOS).

### system_health_monitor.sh

CPU (delta of `/proc/stat`, falls back to `top`), memory (`/proc/meminfo`), disk per mount,
process count and top 5 processes by CPU. Alerts go to the console and to the log file, with
timestamps. Exit code 1 if any alert fired.

```bash
./scripts/system_health_monitor.sh --once                       # defaults: 80/80/80, 500 processes
./scripts/system_health_monitor.sh --interval 60 --cpu 90 --disk 85 --log /var/log/health.log
CPU_THRESHOLD=50 MEM_THRESHOLD=70 ./scripts/system_health_monitor.sh --once
```

```
2026-10-19 20:05:26 INFO  cpu=100% mem=83%
2026-10-19 20:05:26 ALERT cpu usage 100% >= threshold 0%
2026-10-19 20:05:26 INFO  disk /=22%
2026-10-19 20:05:26 INFO  processes=1155
```

### backup.sh

Creates `<dir>-<timestamp>.tar.gz` plus a `.sha256`, uploads it, prunes to the newest N
(`--keep`, default 7) and prints and appends a report line (status, size, duration,
destination). Types: `rsync` (over ssh), `s3` (aws cli), `rclone`, `local` (for testing).
`--dry-run` shows the steps without changing anything. Exit 0 success, 1 failure, 2 usage.

```bash
./scripts/backup.sh --source ./data --type rsync --dest backup@host:/srv/backups --keep 14
./scripts/backup.sh --source ./data --type s3 --dest s3://my-bucket/backups
./scripts/backup.sh --source ./data --type rclone --dest gdrive:backups
./scripts/backup.sh --source ./data --type local --dest /mnt/backups --dry-run
```

```
2026-10-19 20:05:26 status=SUCCESS source=/tmp/bsrc destination=local:/tmp/bdst archive=bsrc-20261019-200526.tar.gz size_bytes=147 duration_s=0 dry_run=0
```

### log_analyzer.py

Parses Apache/Nginx combined logs (file, `.gz`, or stdin): total requests, unique IPs, status
breakdown, 404 count and top 404 paths, top pages, top IPs, requests per hour, bytes served and
malformed line count. Standard library only.

```bash
python3 scripts/log_analyzer.py scripts/sample_logs/access.log --top 5
zcat access.log.gz | python3 scripts/log_analyzer.py --json
```

```
Total requests : 196
Malformed lines: 3
Unique IPs     : 11
Bytes served   : 3553075

Status codes:
  200  151
  302  13
  404  21
  500  11
```

### app_health_checker.py

Checks one or more URLs. A response code in the expected set (`--expected`, default `200-399`)
is UP; any other code, a timeout or a connection error is DOWN. Prints response time. With
`--interval N` it keeps checking and prints an uptime percentage on exit (Ctrl-C, or `--count`).
Exit 0 only if everything is up.

```bash
python3 scripts/app_health_checker.py https://example.com http://localhost:4499
python3 scripts/app_health_checker.py https://example.com --interval 30 --json
python3 scripts/app_health_checker.py http://localhost/health --expected 200,204 --timeout 3
```

```
20:16:28 DOWN http://127.0.0.1:1 code=None time=1.1ms (connection error: [Errno 61] Connection refused)
```

## What was verified locally

Docker build and run (cow output on `localhost:4499`, uid 10001), a full kind + ingress-nginx +
cert-manager deployment with the HTTPS curl and HTTP redirect, shellcheck on all shell files,
and the unit tests on macOS and in a Linux container.
