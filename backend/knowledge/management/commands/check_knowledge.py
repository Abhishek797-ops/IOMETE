"""
Validate the product knowledge base.

Run this in CI and before shipping any change to customer-facing copy. It fails the build
on an unresolvable citation or an unknown status, which is the mechanism that keeps
"source-backed" from degrading into "mostly source-backed".
"""

from django.core.management.base import BaseCommand, CommandError

from knowledge.services.product_knowledge import (
    KnowledgeBaseError,
    _read_raw,
    reload,
    validate,
)


class Command(BaseCommand):
    help = "Validate docs/product-knowledge/knowledge.json for schema and citation integrity."

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Treat warnings (e.g. a `verified` entry citing no source) as failures.",
        )

    def handle(self, *args, **options):
        try:
            data = _read_raw()
        except KnowledgeBaseError as exc:
            raise CommandError(str(exc)) from exc

        report = validate(data)

        for warning in report.warnings:
            self.stdout.write(self.style.WARNING(f"  warning: {warning}"))
        for error in report.errors:
            self.stdout.write(self.style.ERROR(f"  error:   {error}"))

        if report.errors:
            raise CommandError(
                f"Knowledge base validation failed with {len(report.errors)} error(s)."
            )
        if options["strict"] and report.warnings:
            raise CommandError(
                f"--strict: {len(report.warnings)} warning(s) treated as failures."
            )

        reload()
        from knowledge.services.product_knowledge import knowledge_meta

        meta = knowledge_meta()
        self.stdout.write(self.style.SUCCESS("Knowledge base is valid."))
        self.stdout.write(
            f"  last verified:          {meta['last_verified']}\n"
            f"  sources:                {meta['source_count']}\n"
            f"  capabilities:           {meta['capability_count']} "
            f"({meta['verified_capability_count']} verified, "
            f"{meta['needs_confirmation_count']} need confirmation)\n"
            f"  do-not-claim rules:     {meta['do_not_claim_count']}\n"
            f"  warnings:               {len(report.warnings)}"
        )
