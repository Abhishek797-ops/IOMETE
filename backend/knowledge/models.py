"""
No models.

The IOMETE product knowledge base is a version-controlled, reviewable JSON file
(`docs/product-knowledge/knowledge.json`), not database rows. That is deliberate: product
claims must be reviewed in a pull request alongside their sources, and must be identical
in every environment. Putting them in the database would make them editable without review
and divergent between deployments.

Customer-specific knowledge that *does* belong in the database — resolution playbooks —
lives in the `playbooks` app.
"""
