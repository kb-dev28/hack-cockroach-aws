# Anima — Autonomous Life-Pattern Diary

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Anima** is an agentic wellness diary for the [CockroachDB × AWS Hackathon — Build with Agentic Memory](https://devpost.com).

> **Open source:** this repository is published under the [MIT License](LICENSE). After pushing to GitHub, set **About → License → MIT** so judges can see it on the repository home page.

It does more than store text. When you write a free-form diary note, Anima:

1. Extracts structured life signals (emotion, meal, spend, people, weather, event)
2. Embeds the note as a **1536-dimension vector**
3. Persists both SQL facts and vector memory in **CockroachDB**
4. Recalls the closest past days with CockroachDB **cosine vector search** (`<=>`)
5. Returns a **pattern insight** when today resembles a previous episode

> Status: **MVP backend is working**. Frontend UI, public demo hosting, and the 3-minute video are planned next.

---

## Why this matters (Agentic Memory)

Traditional journals are write-only. Anima treats CockroachDB as the agent's **long-term memory**:

| Memory layer | What it stores | What the agent does with it |
|---|---|---|
| Relational SQL (`diary_entries`) | Emotion, spend, meal, people, weather, event | Metrics, filters, cross-checks |
| Distributed vectors (`life_vector_memory`) | Semantic embedding of the day | Similarity recall with `<=>` |

The agent **acts** after every write: it compares the new day to past days and surfaces invisible patterns (for example: *sad + mom + sunny + pharmacy spend*).

---

## Hackathon stack checklist

| Requirement | Tool | How Anima uses it |
|---|---|---|
| CockroachDB #1 | **Distributed Vector Indexing** | `VECTOR(1536)` + cosine vector index + `<=>` nearest-neighbor recall |
| CockroachDB #2 | **Cloud Managed MCP Server** | Cursor connected to the live cluster for schema inspection and development |
| CockroachDB #3 | **Agent Skills Repo** | Local skill `.agents/skills/cockroachdb-sql` (schema design, query patterns, `EXPLAIN` validation against the live cluster) |
| AWS #1 | **AWS Lambda** | Serverless backend that orchestrates AI + memory |
| AWS #2 | **Amazon Bedrock** | Claude Sonnet 4.5 for entity extraction; Titan Embeddings V1 for vectors |
| AWS (bonus) | **Secrets Manager** | CockroachDB URL stored as secret `hack-cockroach-aws/database-url` (never in code) |

---

## Architecture

```text
User note (JSON)
      │
      ▼
AWS Lambda (Python 3.12, arm64)
      │
      ├── AWS Secrets Manager     → DATABASE_URL (cold-start cache)
      ├── Amazon Bedrock Claude  → structured JSON
      ├── Amazon Bedrock Titan   → VECTOR(1536)
      │
      ▼
CockroachDB Cloud (TLS via packaged root.crt)
      ├── diary_entries
      └── life_vector_memory (+ VECTOR INDEX)
      │
      ▼
Vector search (<=>) → pattern_insight
```

---

## Current project status

### Done

- [x] CockroachDB Cloud cluster + schema
- [x] Vector index with `vector_cosine_ops`
- [x] CockroachDB MCP connected in Cursor
- [x] AWS Lambda function (Python 3.12 / arm64)
- [x] Bedrock Claude extraction + Titan embeddings
- [x] Transactional INSERT into SQL + vector tables
- [x] Similarity search (`<=>`) + `pattern_insight` response
- [x] SSL to CockroachDB Cloud via packaged `root.crt` + `PGSSLROOTCERT`
- [x] AWS Secrets Manager for `DATABASE_URL` (module-level cache on cold start)
- [x] Structured CloudWatch JSON logs (`PATTERN_RECALL_SUCCESS`, etc.)
- [x] Packaging script for Lambda deploy zip
- [x] Phase 3.5 proactive agent (`agent_suggestion` when cosine distance &lt; 0.15)
- [x] MIT open-source license (`LICENSE` + `LICENSE.md`)

### Coming next

- [ ] Simple web UI (diary input + insight display)
- [ ] Metrics panel (`GROUP BY` / `SUM` SQL charts)
- [ ] Public demo URL
- [ ] Public GitHub repo + **About → License: MIT** (one click after push)
- [ ] Demo video (&lt; 3 minutes)

---

## Repository layout

```text
hack-cockroach-aws/
├── README.md
├── LICENSE                 # MIT — detected by GitHub About section
├── LICENSE.md              # Same license (human-readable copy)
├── lambda/
│   ├── lambda_function.py   # Backend agent logic
│   ├── build_package.sh     # Builds ARM64 deploy zip with psycopg2 + root.crt
│   └── lambda-deploy.zip    # Generated artifact (gitignored)
├── cockroach-ca.crt         # Local CA download (gitignored; packed as root.crt)
└── docs/
    └── internal/            # Private notes (gitignored)
```

---

## Database schema

### `diary_entries`

| Column | Type | Purpose |
|---|---|---|
| `id` | UUID PK | Entry id |
| `user_note` | STRING | Raw diary text |
| `detected_emotion` | VARCHAR(50) | One-word emotion |
| `main_meal` | STRING | Primary food |
| `total_spend` | DECIMAL(10,2) | Money spent |
| `main_event` | VARCHAR(100) | Main activity |
| `people_involved` | STRING | People mentioned |
| `weather_condition` | VARCHAR(50) | Weather mentioned |
| `created_at` | TIMESTAMPTZ | Timestamp |

### `life_vector_memory`

| Column | Type | Purpose |
|---|---|---|
| `id` | UUID PK | Vector row id |
| `entry_id` | UUID FK → `diary_entries` | Link to diary day |
| `emotional_vector` | `VECTOR(1536)` | Titan embedding |

Vector index:

```sql
VECTOR INDEX life_vector_memory_emotional_vector_idx
  (emotional_vector vector_cosine_ops);
```

---

## Lambda API

Handler: `lambda_function.lambda_handler`

### 1) Health check (no Bedrock)

```bash
aws lambda invoke \
  --function-name YOUR_FUNCTION_NAME \
  --region us-east-1 \
  --cli-binary-format raw-in-base64-out \
  --payload '{"action":"health"}' \
  response.json && cat response.json
```

### 2) Process a diary note (AI + memory + pattern recall)

```bash
aws lambda invoke \
  --function-name YOUR_FUNCTION_NAME \
  --region us-east-1 \
  --cli-binary-format raw-in-base64-out \
  --payload '{"note":"Today I felt sad, my mom visited, it was sunny, ate pizza, spent $30 at the pharmacy"}' \
  response.json && cat response.json
```

Example success fields:

```json
{
  "message": "AI processing, memory save, and pattern recall successful",
  "entry_id": "...",
  "structured_data": {
    "detected_emotion": "sad",
    "main_meal": "pizza",
    "total_spend": 30.0,
    "main_event": "pharmacy visit",
    "people_involved": "mom",
    "weather_condition": "sunny"
  },
  "vector_length": 1536,
  "pattern_insight": {
    "has_pattern": true,
    "summary": "Pattern detected (cosine distance=0.04 < 0.15)...",
    "closest_distance": 0.04,
    "agent_suggestion": {
      "action_triggered": true,
      "cause_effect": "When interaction involving mom + meal cue pizza showed up before...",
      "agent_message": "Cap discretionary spend for the next few hours...",
      "ethical_note": "Suggestion only — not a diagnosis."
    }
  }
}
```

> Tip: send **two similar notes**. The first creates memory; the second should return `has_pattern: true` and `agent_suggestion`.

---

## Setup (for judges / developers)

### Prerequisites

- AWS account with Lambda + Bedrock access (Claude Sonnet 4.5 + Titan Embeddings V1)
- CockroachDB Cloud cluster
- AWS CLI configured locally (optional, for deploy/invoke)

### 1. Create schema in CockroachDB SQL Shell

```sql
CREATE TABLE IF NOT EXISTS diary_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_note TEXT NOT NULL,
    detected_emotion VARCHAR(50),
    main_meal TEXT,
    total_spend DECIMAL(10,2) DEFAULT 0.00,
    main_event VARCHAR(100),
    people_involved TEXT,
    weather_condition VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS life_vector_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entry_id UUID REFERENCES diary_entries(id) ON DELETE CASCADE,
    emotional_vector VECTOR(1536) NOT NULL,
    VECTOR INDEX (emotional_vector vector_cosine_ops)
);
```

### 2. Download Cockroach Cloud CA

```bash
curl -fsSL -o cockroach-ca.crt \
  "https://cockroachlabs.cloud/clusters/YOUR_CLUSTER_ID/cert"
```

### 3. Build the Lambda deploy package

```bash
./lambda/build_package.sh
```

This produces `lambda/lambda-deploy.zip` containing:

- `lambda_function.py`
- `psycopg2-binary` (manylinux2014 **aarch64** / Python 3.12)
- `root.crt` (from `cockroach-ca.crt`)

### 4. Configure secrets + Lambda

Store the CockroachDB URL in **AWS Secrets Manager** (not in source code):

```bash
aws secretsmanager create-secret \
  --name hack-cockroach-aws/database-url \
  --description "CockroachDB connection string for Anima" \
  --secret-string '{"DATABASE_URL":"postgresql://USER:PASSWORD@HOST:26257/defaultdb?sslmode=verify-full"}'
```

Grant the Lambda execution role read access:

```bash
aws iam put-role-policy \
  --role-name YOUR_LAMBDA_ROLE \
  --policy-name SecretsManagerReadAnima \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:hack-cockroach-aws/database-url-*"
    }]
  }'
```

| Setting | Value |
|---|---|
| Runtime | Python 3.12 |
| Architecture | **arm64** |
| Handler | `lambda_function.lambda_handler` |
| Timeout | 30+ seconds |
| Env `PGSSLROOTCERT` | `/var/task/root.crt` |
| Secret | `hack-cockroach-aws/database-url` → JSON key `DATABASE_URL` |

### 5. Deploy

```bash
aws lambda update-function-code \
  --function-name YOUR_FUNCTION_NAME \
  --region us-east-1 \
  --zip-file fileb://lambda/lambda-deploy.zip
```

---

## How CockroachDB tools are used

### Distributed Vector Indexing

- Stores Titan embeddings in `life_vector_memory.emotional_vector`
- Indexed with CockroachDB C-SPANN vector index (`vector_cosine_ops`)
- After every insert, Anima runs nearest-neighbor search with `<=>`
- Results power autonomous `pattern_insight` alerts

### Managed MCP Server

- Connected to Cursor during development
- Used to inspect live schema, indexes, and row counts safely
- Speeds up backend iteration against the real memory layer

### Agent Skills (`cockroachdb-sql`)

The hackathon allows the open-source [CockroachDB Agent Skills](https://github.com/cockroachdb/agent-skills) repo. This project installs the SQL skill under:

```text
.agents/skills/cockroachdb-sql/
```

Used during development to:

- Validate schema against CockroachDB rules (UUID PKs, `VECTOR(n)`, `CREATE VECTOR INDEX` + opclass)
- Align recall queries with documented vector operators (`<=>` + `vector_cosine_ops`)
- Run live `EXPLAIN` via MCP before changing SQL in Lambda

---

## How AWS services are used

### AWS Lambda

Serverless execution environment for the agent loop:

`note → Secrets Manager → Bedrock extract → Bedrock embed → INSERT → vector recall → insight`

Structured JSON logs go to **CloudWatch** (for example `PATTERN_RECALL_SUCCESS` with `request_id`, `closest_distance`, and `action_triggered`) so judges can verify agent decisions in production traces.

### Amazon Bedrock

- **Claude Sonnet 4.5** (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`): structured entity extraction
- **Amazon Titan Text Embeddings V1**: 1536-dim embeddings aligned with `VECTOR(1536)`

### AWS Secrets Manager

- Secret name: `hack-cockroach-aws/database-url`
- JSON payload: `{ "DATABASE_URL": "postgresql://..." }`
- Loaded once per cold start and cached in memory for warm invocations
- Keeps credentials out of source control and Lambda env screenshots

---

## Security notes

- Connection string lives in **Secrets Manager**, not in the repo
- Never commit passwords, `.env`, or raw connection strings
- `cockroach-ca.crt` and `*.zip` are gitignored
- TLS uses packaged CA + `PGSSLROOTCERT=/var/task/root.crt` with `sslmode=verify-full`
---

## Roadmap

1. Minimal HTML/JS diary UI calling the Lambda Function URL
2. Metrics page with SQL aggregations (emotions vs spend)
3. Public demo + Devpost submission links
4. Demo video showing note → memory write → vector recall → insight

---

## License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) (canonical file for GitHub detection) and [LICENSE.md](LICENSE.md).

Devpost requires a **public open-source repository** with a detectable license. This repo includes:

| Requirement | How Anima satisfies it |
|---|---|
| License file | `LICENSE` at repository root (MIT) |
| Visible on GitHub | Push the repo, then **Settings → General → Features** or edit **About → License → MIT** |
| Judges can run it | README setup steps, schema SQL, Lambda build script |

---

## Author

Built for the **CockroachDB × AWS Hackathon** by **karm-bit28** — a production-minded agentic memory demo focused on personal wellness patterns.
