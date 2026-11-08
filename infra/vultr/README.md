# Vultr infrastructure

The live demo runs on a single Cloud Compute VM, deployed with [`deploy.sh`](deploy.sh)
(Caddy for HTTPS, Supabase, Docker Compose; only 80/443 public). The Terraform below is the
larger multi-VM layout for production.

Terraform in `terraform/` creates the fixed part of Zentry on Vultr (Singapore):

| Resource | Purpose |
| --- | --- |
| VPC `10.20.0.0/24` | private network between the VMs |
| `zentry-app` (vc2-2c-4gb) | Coolify, SvelteKit web, FastAPI API — the only public VM (80/443) |
| `zentry-worker` (vc2-2c-4gb) | relay, scoring, investigator agents |
| `zentry-data` (vc2-4c-8gb) | Supabase (Postgres, Auth, Realtime) + NATS JetStream |
| 2 firewall groups | public: 80/443 + admin SSH/Coolify; private: admin SSH only |

The Training VM (M5) is **not** in Terraform: the API creates it from a snapshot through the Vultr API
when someone clicks Train, and deletes it when training finishes.

## One-time setup (done by a human)

1. Vultr Object Storage: create a bucket for Terraform state, e.g. `zentry-tfstate`.
2. Vultr API key (Account → API). GitHub-hosted runners use changing IPs, so the key's access
   control must allow them (or run Terraform locally only).
3. Repository secrets (Settings → Secrets and variables → Actions):
   `VULTR_API_KEY`, `ZENTRY_SSH_PUBLIC_KEY`, `ZENTRY_ADMIN_CIDR`,
   `TF_STATE_BUCKET`, `TF_STATE_ENDPOINT` (e.g. `https://sgp1.vultrobjects.com`),
   `TF_STATE_ACCESS_KEY`, `TF_STATE_SECRET_KEY`.
4. Repository environment `vultr` with a required reviewer — `apply`/`destroy` wait for approval.

## Run

Locally:

```bash
cd infra/vultr/terraform
cp backend.hcl.example backend.hcl && cp terraform.tfvars.example terraform.tfvars   # fill both in
export VULTR_API_KEY=...
terraform init -backend-config=backend.hcl
terraform plan
```

From GitHub: Actions → **Infra (Vultr)** → Run workflow → `plan`, `apply` or `destroy`.
Pull requests that change `terraform/` get the plan as a comment.

After `apply`, open the `coolify_dashboard` output, finish Coolify's setup, add the worker and data
VMs as servers (by private IP), and deploy the services from this repository.
