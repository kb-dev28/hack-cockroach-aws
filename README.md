# Anima — Memory That Acts

**Anima** is an agentic diary that turns long-term personal memory into action. Built for the [CockroachDB × AWS Hackathon — Build with Agentic Memory](https://devpost.com).

> **Open source:** This repository is published under the [MIT License](LICENSE).

## Try Anima

* **Live Demo:** https://hack-cockroach-aws.vercel.app
* **GitHub:** https://github.com/kb-dev28/hack-cockroach-aws

Anima lets a user write a free-form diary entry and turns it into persistent, searchable memory.

It does more than store text. When a user writes a note, Anima:

1. Extracts structured life signals such as emotion, meal, spending, people, weather, and events.
2. Generates a **1536-dimensional vector embedding**.
3. Persists both structured SQL facts and vector memory in **CockroachDB**.
4. Recalls similar past experiences using CockroachDB **cosine vector search** with `<=>`.
5. Evaluates the retrieved memory against structured signals.
6. Generates a **proactive agent suggestion** when a meaningful recurring pattern is detected.

The core idea is simple:

> **Anima doesn't just remember what happened. It uses memory to decide when something is worth bringing back to the user's attention.**

---

## Why Agentic Memory?

Traditional journals are mostly write-only. They can contain years of valuable information, but the information remains passive.

Anima treats **CockroachDB as the agent's long-term memory**.

| Memory Layer                         | What It Stores                                    | What the Agent Does With It               |
| ------------------------------------ | ------------------------------------------------- | ----------------------------------------- |
| Relational SQL (`diary_entries`)     | Emotion, spending, meals, people, weather, events | Metrics, filters, structured cross-checks |
| Vector memory (`life_vector_memory`) | Semantic embedding of the diary entry             | Similarity recall with `<=>`              |

After a new memory is written, Anima searches the user's previous memories and evaluates whether the new entry resembles a meaningful previous situation.

For example, a new entry could resemble a previous combination such as:

**sad + mom + sunny + pharmacy spending**

If the similarity is strong enough and the structured signals support the pattern, the agent can surface a proactive suggestion based on the user's own historical context.

Suggestions are intentionally non-prescriptive. Anima is not designed to provide clinical diagnoses.

---

## Agentic Memory Loop

The core loop is:

**Write → Understand → Remember → Recall → Evaluate → Act**

### 1. Write

The user enters a free-form diary note through the web interface.

### 2. Understand

Amazon Bedrock extracts structured information such as:

* Emotion
* Meal
* Spending
* People
* Weather
* Event

### 3. Remember

Amazon Titan Text Embeddings V1 converts the entry into a **1536-dimensional embedding**.

Both the structured data and embedding are persisted in CockroachDB.

### 4. Recall

Anima performs a nearest-neighbor search using CockroachDB's vector support and the cosine distance operator:

```sql
ORDER BY emotional_vector <=> %s
```

The vector memory is indexed using `vector_cosine_ops`.

### 5. Evaluate

The agent combines the vector similarity with structured SQL signals.

The current proactive threshold is:

```text
cosine distance < 0.3
```

### 6. Act

When a meaningful pattern is detected, Anima returns a `pattern_insight` and can generate an `agent_suggestion` based on the user's previous context.

This is the key difference from a simple RAG application:

> The retrieved memory is not only displayed. It is evaluated as part of the agent's decision-making process.

---

## Architecture

```text
                         User
                          │
                          ▼
                   Anima Web UI
                   Next.js + Tailwind
                          │
                          ▼
                 AWS Lambda (Python)
                          │
              ┌───────────┼───────────┐
              │           │           │
              ▼           ▼           ▼
       Secrets Manager  Bedrock    Bedrock
       DATABASE_URL     Claude      Titan
                       Sonnet      Embeddings
              │           │           │
              │           └─────┬─────┘
              │                 │
              └──────────┬──────┘
                         ▼
                  CockroachDB Cloud
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
       diary_entries        life_vector_memory
       Structured SQL        VECTOR(1536)
              │                     │
              └──────────┬──────────┘
                         ▼
                  Cosine Search
                       (<=>)
                         │
                         ▼
                  Pattern Evaluation
                         │
                         ▼
                  Agent Suggestion
                         │
                         ▼
                      User
```

---

## Hackathon Stack

### CockroachDB

Anima uses three CockroachDB capabilities:

#### 1. Distributed Vector Indexing

* Stores Titan embeddings in `life_vector_memory.emotional_vector`.
* Uses `VECTOR(1536)`.
* Uses a cosine vector index with `vector_cosine_ops`.
* Performs nearest-neighbor recall with `<=>`.
* Keeps structured data and semantic memory in the same database.

#### 2. Cloud Managed MCP Server

During development, Cursor was connected to the live CockroachDB cluster through the Managed MCP Server.

It was used to:

* Inspect the live database schema.
* Inspect indexes and row counts.
* Validate queries against the real cluster.
* Run `EXPLAIN` while iterating on SQL.

#### 3. CockroachDB Agent Skills

The project uses the local `cockroachdb-sql` Agent Skill under:

```text
.agents/skills/cockroachdb-sql/
```

It was used to:

* Validate schema design.
* Validate `VECTOR(n)` and vector index patterns.
* Align vector recall queries with `<=>` and `vector_cosine_ops`.
* Validate SQL behavior against the live CockroachDB cluster.

#### 4. ccloud CLI

The ccloud CLI was used during development to interact with and inspect the CockroachDB Cloud environment from the terminal.

It was used to:

* Inspect and manage the CockroachDB Cloud environment.
* Test database and schema operations.
* Verify the development cluster configuration.

---

## AWS Services

### AWS Lambda

Lambda runs the serverless agent pipeline:

```text
note
  ↓
Secrets Manager
  ↓
Bedrock structured extraction
  ↓
Titan embedding
  ↓
CockroachDB transaction
  ↓
Vector recall
  ↓
Pattern evaluation
  ↓
Agent suggestion
```

The Lambda function uses **Python 3.12 on arm64**.

### Amazon Bedrock

Two Bedrock models are used:

* **Claude Sonnet 4.5** for structured entity extraction.
* **Amazon Titan Text Embeddings V1** for 1536-dimensional vector embeddings.

### AWS Secrets Manager

The CockroachDB connection string is stored in AWS Secrets Manager rather than source code.

The secret is loaded during Lambda cold start and cached for warm invocations.

### Amazon CloudWatch

Structured JSON logs are emitted to CloudWatch.

Example event:

```text
PATTERN_RECALL_SUCCESS
```

Logs include fields such as:

* `request_id`
* `closest_distance`
* `action_triggered`

This allows agent decisions to be inspected through production traces.

---

## Database Schema

### `diary_entries`

| Column              | Type          | Purpose             |
| ------------------- | ------------- | ------------------- |
| `id`                | UUID          | Entry primary key   |
| `user_note`         | TEXT          | Raw diary entry     |
| `detected_emotion`  | VARCHAR(50)   | Extracted emotion   |
| `main_meal`         | TEXT          | Primary meal        |
| `total_spend`       | DECIMAL(10,2) | Extracted spending  |
| `main_event`        | VARCHAR(100)  | Main activity/event |
| `people_involved`   | TEXT          | People mentioned    |
| `weather_condition` | VARCHAR(50)   | Weather mentioned   |
| `created_at`        | TIMESTAMPTZ   | Entry timestamp     |

### `life_vector_memory`

| Column             | Type           | Purpose                        |
| ------------------ | -------------- | ------------------------------ |
| `id`               | UUID           | Vector row primary key         |
| `entry_id`         | UUID           | Foreign key to `diary_entries` |
| `emotional_vector` | `VECTOR(1536)` | Titan embedding                |

Vector index:

```sql
CREATE VECTOR INDEX life_vector_memory_emotional_vector_idx
  ON life_vector_memory (emotional_vector vector_cosine_ops);
```

---

## Example Agent Response

An example processed entry can produce:

```json
{
  "message": "AI processing, memory save, and pattern recall successful",
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
    "closest_distance": 0.04,
    "agent_suggestion": {
      "action_triggered": true,
      "ethical_note": "Suggestion only — not a diagnosis."
    }
  }
}
```

To demonstrate the memory behavior, send two semantically similar diary entries. The first creates the memory; the second can retrieve it and trigger a pattern insight.

---

## Project Structure

```text
hack-cockroach-aws/
├── README.md
├── LICENSE.md
├── lambda/
│   ├── lambda_function.py
│   └── build_package.sh
├── frontend/
│   └── app/
│       └── page.tsx
├── sql/
│   └── migration_add_user_id.sql
└── .agents/
    └── skills/
        └── cockroachdb-sql/
```

---

## Security

* CockroachDB credentials are stored in **AWS Secrets Manager**.
* No passwords or raw connection strings are committed to the repository.
* CockroachDB Cloud connections use TLS with `sslmode=verify-full`.
* The CockroachDB CA certificate is packaged only for Lambda deployment.
* Deployment artifacts and sensitive files are excluded through `.gitignore`.
* User memory is isolated using `user_id` at the Lambda and SQL layers.
* Structured CloudWatch logs provide observability without exposing database credentials.

---

## Setup

### Prerequisites

* AWS account with access to Lambda and Amazon Bedrock.
* CockroachDB Cloud cluster.
* AWS CLI configured locally.
* Python 3.12 for Lambda packaging.
* Node.js for the frontend.

### 1. Create the CockroachDB Schema

Run the SQL schema and migration files in CockroachDB Cloud SQL Shell.

### 2. Configure AWS Secrets Manager

Store the CockroachDB connection string as:

```text
hack-cockroach-aws/database-url
```

with:

```json
{
  "DATABASE_URL": "postgresql://USER:PASSWORD@HOST:26257/defaultdb?sslmode=verify-full"
}
```

### 3. Build the Lambda Package

```bash
./lambda/build_package.sh
```

### 4. Deploy Lambda

Deploy the generated Lambda package and configure:

```text
Runtime: Python 3.12
Architecture: arm64
Handler: lambda_function.lambda_handler
PGSSLROOTCERT: /var/task/root.crt
```

### 5. Run the Frontend

The frontend is a Next.js + Tailwind application.

The production deployment is available at:

https://hack-cockroach-aws.vercel.app

---

## Current Status

* CockroachDB Cloud cluster + schema
* Distributed vector index
* CockroachDB MCP connected in Cursor
* CockroachDB Agent Skills integration
* AWS Lambda backend
* Amazon Bedrock Claude extraction
* Amazon Titan embeddings
* Transactional SQL + vector persistence
* Cosine similarity search with `<=>`
* Proactive agent suggestion
* AWS Secrets Manager
* Structured CloudWatch logs
* Multi-user memory isolation
* Anima web UI
* Production frontend deployment on Vercel
* MIT open-source license
* Final demo video under 3 minutes

---

## Links

* **Video Pitch:** https://www.youtube.com/watch?v=tOJ5U_pKCNc
* **Live Demo:** https://hack-cockroach-aws.vercel.app
* **Source Code:** https://github.com/kb-dev28/hack-cockroach-aws
* **Hackathon:** https://devpost.com

---

## License

This project is licensed under the **MIT License**. See [LICENSE](LICENSE).

---

## Author

Built for the **CockroachDB × AWS Hackathon — Build with Agentic Memory** by **karm-bit28**.
