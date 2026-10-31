---
name: resolution-playbooks
description: Authoring safe, version-aware troubleshooting playbooks and the FDE approval lifecycle for this repo. Use when creating, editing, seeding or reviewing ResolutionPlaybook / PlaybookStep data or the Resolution Replay engine.
---

# Resolution playbooks

## What a playbook is

A reviewed, versioned, human-approved troubleshooting workflow. It is **data**, never code, and
never executed by the backend. Diagnostic commands are *displayed for a human to run*.

## Required fields

`playbook_id` (stable slug), `title`, `description`, `component`, `applicable_versions`
(spec string, e.g. `>=3.0,<4.0`), `applicable_environments`, `symptoms[]`, `confirmed_root_cause`,
`preconditions[]`, `diagnostic_steps` (ordered `PlaybookStep` rows), `expected_evidence[]`,
`resolution_instructions`, `verification_steps[]`, `risk_level`, `approval_status`,
`approved_by`, `last_reviewed_at`, `review_due_at`, `version`, `supersedes`.

## Step contract

Every `PlaybookStep` carries: `title`, `plain_explanation` (understandable by a customer
engineer who is not an IOMETE expert), `what_to_inspect`, `expected_observation`,
`response_schema` (how the user answers: `boolean` / `choice` / `text` / `numeric`), and
`branches` — a mapping from response to `next_step` or a terminal outcome.

### Step types and their safety contract

| `step_type` | May change the system? | Requires approval? |
| --- | --- | --- |
| `informational` | No | No |
| `read_only_diagnostic` | No | No |
| `configuration_review` | No (read config, do not edit) | No |
| `change_requiring_approval` | Yes | **Yes** — `approval_granted_by` with role `customer_admin`, `fde` or above |
| `verification` | No | No |
| `escalation` | No | No |

`PlaybookExecutionService.advance()` refuses to complete a `change_requiring_approval` step
without a valid approval record. This is enforced in the service and covered by a test.

## Authoring rules

1. **Collect evidence before remediating.** A remediation step must be unreachable until the
   diagnostic steps that establish the root cause have been answered. Express that with
   `branches`, not with instructions in prose.
2. **Branch on observations, not on guesses.** Each branch condition references the previous
   step's `expected_observation` vocabulary.
3. **Never author an unsafe command.** No `kubectl delete`, no `DROP`, no credential echo, no
   blanket restarts. Prefer `kubectl describe`, `kubectl get -o yaml`, `kubectl logs --previous`,
   `SHOW`/`DESCRIBE` SQL. If remediation is genuinely destructive, the step is an
   `escalation` to an FDE instead.
4. **Label impact.** `risk_level` ∈ `{informational, low, medium, high}`. Anything `medium`+
   renders a confirmation gate in the UI with the blast radius spelled out.
5. **Version-gate honestly.** If you do not know that a playbook applies to a version, exclude
   that version. A false positive here produces a wrong fix on a production cluster.
6. **A completed checklist is not proof of a fix.** Every playbook ends with an explicit
   outcome capture: resolved / partially resolved / not resolved / escalated, plus evidence.

## Approval lifecycle

```
resolved ticket → KnowledgeExtractionService draft (approval_status=draft)
  → FDE review (edit, redact, set applicability, set risk)
  → approve  → approval_status=approved, version=n, last_reviewed_at=now, review_due_at=+180d
  → reject   → approval_status=rejected (retained with reason; never silently deleted)
  → supersede → new version row, old row approval_status=deprecated, supersedes set
```

Only `approval_status=approved` rows enter trusted retrieval. `deprecated` rows are excluded
from recommendations but remain readable for audit and are explicitly flagged in the UI.
Duplicate prevention: `KnowledgeExtractionService` checks the candidate's fingerprint and
root-cause cluster before creating a draft and links to the existing playbook instead.

## Seeded playbooks

Seeded examples cover Spark executor OOM, Kubernetes resource quota exhaustion, Iceberg
metadata/table-access failure, SQL permission denial via Ranger, ingestion failure, and object
storage connectivity. All are **synthetic** and labelled as such — they are plausible
engineering scenarios, not IOMETE incident records.
