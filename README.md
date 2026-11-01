# IOMETE COMPASS

<p align="center">
  <strong>Understand. Experience. Resolve. Improve.</strong><br>
  <em>AI-powered customer enablement and Forward Deployed Engineer (FDE) productivity platform for the sovereign IOMETE Data Lakehouse.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Django-6.1-092E20?style=flat&logo=django&logoColor=white" alt="Django 6.1" />
  <img src="https://img.shields.io/badge/DRF-3.18-red?style=flat" alt="DRF" />
  <img src="https://img.shields.io/badge/Next.js-16-black?style=flat&logo=next.js&logoColor=white" alt="Next.js 16" />
  <img src="https://img.shields.io/badge/React-19-61DAFB?style=flat&logo=react&logoColor=black" alt="React 19" />
  <img src="https://img.shields.io/badge/TypeScript-5.9-blue?style=flat&logo=typescript&logoColor=white" alt="TypeScript" />
  <img src="https://img.shields.io/badge/TailwindCSS-v4-38B2AC?style=flat&logo=tailwind-css&logoColor=white" alt="Tailwind CSS" />
  <img src="https://img.shields.io/badge/PostgreSQL-17_%2B_pgvector-336791?style=flat&logo=postgresql&logoColor=white" alt="PostgreSQL" />
</p>

---

## 🧭 Executive Overview

**IOMETE** is a sovereign (self-hosted) modern data lakehouse platform powered by Apache Iceberg and Apache Spark. It empowers organizations to maintain 100% control over their data plane within their own VPC or on-premise infrastructure while drastically reducing warehouse compute costs.

**IOMETE COMPASS** is an intelligent enablement and support acceleration platform built specifically for this ecosystem. It addresses two critical operational challenges:

1. **Customer Enablement & Pre-Sales**: Prospects often struggle to evaluate whether an Apache Iceberg lakehouse fits their data stack and infrastructure. COMPASS provides interactive architecture modeling, honest workload fit scoring, and a live SQL playground.
2. **Support Repetition & FDE Efficiency**: Forward Deployed Engineers repeatedly investigate issues previously resolved for other tenants. COMPASS indexes prior incident resolutions, clusters related tickets, and guides engineers and customers through verified remediation playbooks.

> **Key Differentiator:** COMPASS is not a generic chatbot. Its foundation is built on **Resolution Replay** and **Knowledge Compounding**—turning incident resolutions into structured, human-approved playbooks that continuously improve operational intelligence.

---

## 🚀 Key Features

### 1. Public Enablement & Prospect Intelligence
* **Workload Fit Finder**: Multi-factor scoring engine evaluating data volumes, infrastructure topology (AWS, GCP, Azure, bare-metal Kubernetes), streaming/batch mix, and governance constraints. Delivers honest qualification with automatic capacity caps.
* **Interactive Architecture Canvas**: Dynamic visualization illustrating sovereign data plane isolation (customer VPC) versus the managed control plane.
* **Lakehouse SQL Playground**: In-browser SQL console running against synthetic Lakehouse catalogs with instant charting and performance breakdown.
* **Persona & Capability Explorer**: Interactive deep-dives for Data Engineers, Platform Admins, and FinOps leads backed by verified citations.
* **Sales Call Prep Briefs**: Automated generation of technical sales briefs, highlighting unknown architectural variables, sizing estimates, and key discovery questions.

### 2. Support Intelligence & FDE Command Center
* **Deterministic PII/Secret Redaction**: Offline, pattern-based redaction engine that scrubs AWS keys, Slack tokens, JWTs, IPs, and passwords *before* database persistence or embedding generation.
* **Hybrid Semantic Retrieval**: Multi-channel retrieval combining vector similarity (pgvector / cosine distance), BM25 lexical search, error fingerprint matching, and capability tagging via Reciprocal Rank Fusion (RRF).
* **Resolution Replay**: Interactive playbook runner that walks operators through diagnostic queries, log inspections, and remediation steps with enforced human approval gates.
* **Knowledge Compounding**: Post-incident extraction pipeline that sanitizes tenant-specific context, formats resolution steps into structured runbooks, and submits them for FDE lead approval.
* **Bidirectional Jira & IOMETE Integrations**: Synchronization with external ticketing systems and live Iceberg REST Catalog metadata with realistic demo modes.

---

## 🏛️ Security & Sovereignty Principles

* **Strict Multi-Tenant Isolation**: Tenant boundaries are enforced at the database and ORM layer via `TenantOwnedModel` and `.for_user(user)`. Cross-tenant data leaks are physically prevented.
* **Human-in-the-Loop Safe Execution**: COMPASS never executes arbitrary LLM-generated commands on customer clusters. Remediation commands are presented for authorized operators to execute.
* **No Unsanitized Data Ingestion**: Incoming support payloads are redacted before being written to disk, embedded, or sent to model providers.
* **Encrypted Credentials**: External tokens and integration secrets are encrypted at rest using Fernet symmetric encryption (`backend/common/crypto.py`).

---

## 📂 Repository Structure

```
.
├── backend/                  # Django 6 + Django REST Framework API
│   ├── accounts/             # Custom User, Organization, RBAC & Demo Seeder
│   ├── aiengine/             # PII Redaction, RRF Retrieval, LLM Abstractions
│   ├── analytics/            # Operational metrics and telemetry
│   ├── common/               # Base models, tenant isolation, cryptography
│   ├── compass/              # Core project settings, WSGI/ASGI & Celery
│   ├── integrations/         # Jira & IOMETE Iceberg Catalog adapters
│   ├── knowledge/            # Product knowledge service & verification CLI
│   ├── lakehouse/            # Mock Lakehouse catalog & deterministic SQL engine
│   ├── organizations/        # Organization entities & workspace tenancy
│   ├── playbooks/            # Resolution playbooks, step runners & approval
│   ├── prospects/            # Fit assessment engine & sales call prep generator
│   └── tickets/              # Ticket intake, lifecycle, clustering & similarity
│
├── frontend/                 # Next.js 16 (App Router) + React 19 + TypeScript
│   ├── src/app/
│   │   ├── (public)/         # Landing, Architecture, Fit Finder, Playground, Call Prep
│   │   ├── app/              # Customer Support Portal & Ticket Workspaces
│   │   ├── fde/              # Forward Deployed Engineer Console & Knowledge Review
│   │   ├── admin/            # Tenant Administration & Audit Logs
│   │   └── login/            # Authentication
│   ├── src/components/       # UI Primitives, Charts, Diagrams, Layout Shells
│   ├── src/lib/              # Typed API Client, Auth context, Utilities
│   └── src/styles/           # Tailwind CSS v4 token themes
│
└── docs/                     # Product specifications & Lakehouse knowledge base
    └── product-knowledge/    # Single source of truth (knowledge.json)
```

---

## 🛠️ Quickstart & Local Development

### Prerequisites
* Python 3.12+
* Node.js 20+ & npm
* PostgreSQL 15+ (with `pgvector` extension) or SQLite (for offline dev)
* Redis (optional, for Celery task queuing)

---

### Backend Setup

1. **Navigate to the backend directory and activate a virtual environment**:
   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment**:
   ```bash
   cp ../.env.example .env
   ```

4. **Run Migrations & Seed Demo Data**:
   ```bash
   python manage.py migrate
   python manage.py check_knowledge --strict
   python manage.py seed_demo
   ```
   *The `seed_demo` command generates complete tenant organizations, sample tickets, verified playbooks, and prospect profiles.*

5. **Start the Development Server**:
   ```bash
   python manage.py runserver 8000
   ```
   * API root: `http://localhost:8000/api/v1/`
   * OpenAPI Schema: `http://localhost:8000/api/schema/`
   * Swagger Documentation: `http://localhost:8000/api/docs/`

---

### Frontend Setup

1. **Navigate to the frontend directory**:
   ```bash
   cd frontend
   ```

2. **Install dependencies**:
   ```bash
   npm install
   ```

3. **Start the Next.js development server**:
   ```bash
   npm run dev
   ```
   * Access the application at `http://localhost:3000`

---

## 🧪 Testing & Verification

### Backend Test Suite
Run the full test suite including unit, API contract, security isolation, and retrieval quality tests:
```bash
cd backend
pytest -v
```

Run code formatting and lint checks:
```bash
ruff check .
```

### Frontend Code Quality
```bash
cd frontend
npm run lint
npm run typecheck
```

---

## 👥 Demo Personas

When running with `seed_demo`, predefined accounts are available for testing:

| Role | Email | Description | Access |
|------|-------|-------------|--------|
| **FDE Lead** | `fde@iomete.com` | Forward Deployed Engineer | Full access to FDE console, knowledge review, resolution authoring |
| **Customer Operator** | `admin@acme-data.com` | Enterprise Lakehouse Admin | Customer portal, ticket creation, playbook replay runner |
| **Sales Rep** | `sales@iomete.com` | Commercial Account Executive | Prospect evaluations, architecture recommendations, call prep |

---

## 📄 License

This repository is maintained for IOMETE COMPASS enablement and internal engineering workflows.
Distributed under the MIT License. See `LICENSE` for details.
