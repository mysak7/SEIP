# SEIP — Sentinel Event Intelligence Platform

End-to-end security event pipeline: Windows endpoint collection → Kafka → DynamoDB → LLM analysis → pattern management → noise filtering.

---

## Architecture Overview

```
Windows Endpoints
  └── Sysmon + Fluent Bit (seip-agent-win)
            │
            ▼
        Kafka Topic
            │
            ▼
   seip-kafka-consumer  ──▶  DynamoDB (dev-security-events)
                                       │
                    ┌──────────────────┼──────────────────┐
                    ▼                  ▼                   ▼
            seip-deep-mind      seip-deep-mind      seip-orchestrator
            (primary worker)    (ASG workers 0–5)   (scales the ASG)
                    │
                    ▼
         DynamoDB (analysis, severity, model_id)
                    │
        ┌───────────┼────────────┐
        ▼           ▼            ▼
   seip-gui   seip-gui-easy  seip-manager
   (viewer)   (viewer+gen)   (patterns + Lua gen)
                                  │
                                  ▼
                          S3 (noise_filter.lua)
                                  │
                                  ▼
                       seip-agent-win (hot-reload)
```

---

## Projects

| Project | Purpose | Port | Language |
|---|---|---|---|
| [seip-agent-win](seip-agent-win/) | Windows endpoint agent — Sysmon + Fluent Bit → Kafka | — | PowerShell, Python |
| [seip-kafka-consumer](seip-kafka-consumer/) | Kafka → DynamoDB event ingestion | — | Python (FastAPI) |
| [seip-deep-mind](seip-deep-mind/) | LLM-powered event analysis with semantic caching | 8182 | Python (FastAPI) |
| [seip-manager](seip-manager/) | Pattern management + Lua noise filter generation | 8183 | Python (FastAPI) |
| [seip-orchestrator](seip-orchestrator/) | Deep Mind worker pool ASG control panel | 8501 | Python (FastAPI) |
| [seip-gui](seip-gui/) | Lightweight event browser | 3000 | Node.js (Express) |
| [seip-gui-easy](seip-gui-easy/) | Event browser + test data generator | 8080 | Python (FastAPI) |
| [seip-money](seip-money/) | AWS Cost & Usage Report dashboard | 3001 | Python (FastAPI) |
| [seip-infrastructure](seip-infrastructure/) | Terraform IaC for all AWS resources | — | Terraform |
| [seip-maintenance](seip-maintenance/) | Operational monitoring and debug scripts | — | Python, PowerShell |

---

## AWS Infrastructure

All services run in `eu-central-1`.

```
VPC (10.0.0.0/16)
├── Public Subnet (10.0.1.0/24)
│   └── Bastion / NAT  (t3.micro, public IP)
└── Private Subnet (10.0.2.0/24)
    ├── app-host (t3.micro) — kafka-consumer, GUIs, deep-mind primary,
    │                          manager, money, orchestrator
    └── Deep Mind Worker ASG (0–5 × t4g.small arm64)
```

**Key AWS resources:**

| Resource | Name / Details |
|---|---|
| DynamoDB — events | `dev-security-events` |
| DynamoDB — patterns | `dev-seip-patterns` |
| S3 — Lua filters | `mysak7-seip-lua` (public read) |
| ECR | `dev/seip-*` repositories |
| SSM config | `/dev/seip-deep-mind/config`, `/dev/seip-deep-mind/vertex-credentials` |
| CloudWatch metric | `SEIP/DeepMind.UnprocessedEvents` |

---

## DynamoDB Schema

**`dev-security-events`**

| Attribute | Key | Set by |
|---|---|---|
| `event_id` | PK | Kafka consumer |
| `timestamp` | SK | Kafka consumer |
| `message` | — | Kafka consumer |
| `eid` | — | Kafka consumer |
| `severity` | — | seip-deep-mind |
| `analysis` | — | seip-deep-mind |
| `model_id` | — | seip-deep-mind |
| `matched_pattern_id` | — | seip-deep-mind |

**`dev-seip-patterns`**

| Attribute | Key | Set by |
|---|---|---|
| `hash` | PK | seip-manager |
| `pattern_id` | — | seip-manager |
| `hit_count` | — | seip-manager |
| `analysis` | — | seip-manager |
| `model_id` | — | seip-manager |
| `created_at` | — | seip-manager |
| `last_used_at` | — | seip-manager |

---

## CI/CD

Each service has a `.github/workflows/deploy.yml` that:
1. Builds an `arm64` Docker image
2. Pushes to ECR (`317781017752.dkr.ecr.eu-central-1.amazonaws.com/dev/<service>`)
3. SSMs a `systemctl restart <service>` to `dev-app-host`

Infrastructure changes go through `terraform apply` in `seip-infrastructure/`.

---

## Access

All services run in the private subnet. Access via SSH tunnel through the bastion:

```bash
ssh -L <local_port>:<app_host_private_ip>:<service_port> \
    -J ec2-user@<bastion_public_ip> \
    ec2-user@<app_host_private_ip>
```

Then open `http://localhost:<local_port>` in the browser.

---

## Further Reading

- [seip-agent-win/README.md](seip-agent-win/README.md) — endpoint agent setup
- [docs/seip-deep-mind.md](docs/seip-deep-mind.md) — Deep Mind technical reference
- [seip-infrastructure/docs/infrastructure.md](seip-infrastructure/docs/infrastructure.md) — full AWS architecture
- [seip-infrastructure/docs/live-config-updates.md](seip-infrastructure/docs/live-config-updates.md) — updating config without restart
