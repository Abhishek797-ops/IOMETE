"""
Redaction.

Two properties, in tension, both required:

1. **Nothing sensitive survives.** Customers paste logs, and logs contain credentials.
2. **The diagnostic signal survives.** Replacing everything with `***` would protect the
   secret and destroy the retrieval this product depends on. The placeholders keep the
   shape of what was removed so the surrounding error is still readable and still matches.

Both are asserted for every pattern. A redaction test that only checked the first property
would pass on an implementation that broke the product.
"""

from __future__ import annotations

import pytest

from aiengine.services import redaction

pytestmark = pytest.mark.security


class TestSecretsAreRemoved:
    @pytest.mark.parametrize(
        "text,secret,kind",
        [
            (
                "export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE",
                "AKIAIOSFODNN7EXAMPLE",
                "AWS_ACCESS_KEY",
            ),
            (
                "aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                "AWS_SECRET",
            ),
            (
                "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.abcdefghij",
                "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.abcdefghij",
                "JWT",
            ),
            (
                "Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz0123",
                "sk-abcdefghijklmnopqrstuvwxyz0123",
                "BEARER_TOKEN",
            ),
            (
                "github token ghp_abcdefghijklmnopqrstuvwxyz0123456789",
                "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
                "GITHUB_TOKEN",
            ),
            (
                "slack webhook xoxb-dummy-test-token-value-9999",
                "xoxb-dummy-test-token-value-9999",
                "SLACK_TOKEN",
            ),
            (
                "AccountKey=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWX==",
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWX==",
                "AZURE_STORAGE_KEY",
            ),
            (
                "api_key: 7f3b9a2c8e1d4f6a0b5c9d8e",
                "7f3b9a2c8e1d4f6a0b5c9d8e",
                "ASSIGNED_SECRET",
            ),
            (
                "client_secret=abc123def456ghi789",
                "abc123def456ghi789",
                "ASSIGNED_SECRET",
            ),
        ],
    )
    def test_each_credential_shape_is_removed(self, text, secret, kind):
        result = redaction.redact(text)
        assert secret not in result.text, f"{kind} survived redaction"
        assert kind in result.summary, f"{kind} was removed but not reported: {result.summary}"

    def test_a_private_key_block_is_removed_whole(self):
        text = (
            "Here is the key we use:\n"
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEAx3f8k2j4lMnOpQrStUvWxYz0123456789abcdefghij\n"
            "klmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/=\n"
            "-----END RSA PRIVATE KEY-----\n"
            "and the cluster still fails."
        )
        result = redaction.redact(text)
        assert "MIIEowIBAAKCAQEA" not in result.text
        assert "BEGIN RSA PRIVATE KEY" not in result.text
        assert result.summary.get("PRIVATE_KEY_BLOCK") == 1
        # Surrounding prose is preserved.
        assert "the cluster still fails" in result.text

    def test_a_jdbc_password_is_removed_but_the_user_and_host_survive(self):
        """
        Keeping the username and host is deliberate: "connecting as iomete_app to
        postgres.internal" is diagnostically essential, and only the password is a secret.
        """
        text = "jdbc:postgresql://iomete_app:Sup3rS3cretPw@db.internal:5432/iomete_metastore"
        result = redaction.redact(text)
        assert "Sup3rS3cretPw" not in result.text
        assert "iomete_app" in result.text
        assert "db.internal" in result.text
        assert "iomete_metastore" in result.text

    def test_a_kubernetes_secret_dump_is_redacted(self):
        text = (
            "kubectl get secret data-plane -o yaml\n"
            "data:\n"
            "  storage.accessKey: YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY3OA==\n"
            "  storage.secretKey: cXdlcnR5dWlvcGFzZGZnaGprbHp4Y3Zibm0xMjM0NTY3ODkw\n"
        )
        result = redaction.redact(text)
        assert "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY3OA==" not in result.text
        assert "cXdlcnR5dWlvcGFzZGZnaGprbHp4Y3Zibm0xMjM0NTY3ODkw" not in result.text
        # The key *names* survive, which is what tells an engineer which credential matters.
        assert "storage.accessKey" in result.text

    def test_personal_and_network_identifiers_are_removed(self):
        text = "Contact alex.smith@customer.example about node 10.4.19.22 in the cluster."
        result = redaction.redact(text)
        assert "alex.smith@customer.example" not in result.text
        assert "10.4.19.22" not in result.text
        assert result.summary.get("EMAIL") == 1
        assert result.summary.get("IPV4") == 1

    def test_loopback_and_wildcard_addresses_are_kept(self):
        """
        `127.0.0.1` and `0.0.0.0` carry no personal data and are often the diagnostically
        important part — "failed to bind to 0.0.0.0" must stay readable.
        """
        text = "Failed to bind to 0.0.0.0:15002 and could not reach 127.0.0.1:10000."
        result = redaction.redact(text)
        assert "0.0.0.0" in result.text
        assert "127.0.0.1" in result.text
        assert "IPV4" not in result.summary

    def test_high_entropy_catch_all_fires_on_an_unrecognised_token(self):
        text = "The request carried qX7vP2mK9wL4nR8tY6uI3oA5sD1fG0hJ as its handle."
        result = redaction.redact(text)
        assert "qX7vP2mK9wL4nR8tY6uI3oA5sD1fG0hJ" not in result.text
        assert result.summary.get("HIGH_ENTROPY_TOKEN") == 1


class TestDiagnosticSignalSurvives:
    """
    Over-redaction is its own failure. These assertions exist because an earlier, simpler
    redactor would have destroyed exactly the tokens retrieval depends on.
    """

    @pytest.mark.parametrize(
        "token",
        [
            "OOMKilled",
            "CrashLoopBackOff",
            "ExecutorLostFailure",
            "org.apache.iceberg.exceptions.CommitFailedException",
            "RangerAccessControlException",
            "java.lang.OutOfMemoryError",
            "spark.executor.memoryOverhead",
            "FailedScheduling",
            "3.19.1",
            "137",
        ],
    )
    def test_diagnostic_tokens_are_not_redacted(self, token):
        text = f"The failure reported {token} during the run."
        result = redaction.redact(text)
        assert token in result.text, f"{token} was wrongly redacted"

    def test_a_realistic_stack_trace_survives_intact(self):
        text = (
            "org.apache.spark.SparkException: Job aborted due to stage failure: "
            "Task 14 in stage 7.0 failed 4 times, most recent failure: "
            "Lost task 14.3 in stage 7.0 (TID 1823) (executor 9): "
            "ExecutorLostFailure (executor 9 exited caused by one of the running tasks) "
            "Reason: Container killed: OOMKilled (exit code 137)\n"
            "\tat org.apache.spark.scheduler.DAGScheduler.failJobAndIndependentStages"
        )
        result = redaction.redact(text)
        for token in (
            "SparkException", "ExecutorLostFailure", "OOMKilled", "137",
            "org.apache.spark.scheduler.DAGScheduler",
        ):
            assert token in result.text, f"{token} lost from the stack trace"

    def test_a_uuid_is_preserved_as_an_identifier(self):
        text = "The run id was 3f2504e0-4f89-11d3-9a0c-0305e82c3301 and it failed."
        result = redaction.redact(text)
        assert "3f2504e0-4f89-11d3-9a0c-0305e82c3301" in result.text

    def test_a_git_sha_is_preserved(self):
        text = "Deployed at commit a1b2c3d4e5f6 and it broke."
        result = redaction.redact(text)
        assert "a1b2c3d4e5f6" in result.text

    def test_a_storage_uri_keeps_its_scheme(self):
        """The scheme identifies the storage backend, which drives component inference."""
        text = "getFileStatus on s3a://northwind-lakehouse/data/ failed."
        result = redaction.redact(text)
        assert "s3a://" in result.text


class TestReporting:
    def test_redaction_is_reported_not_silent(self):
        text = "key: AKIAIOSFODNN7EXAMPLE and contact a@b.com"
        result = redaction.redact(text)
        assert result.was_redacted
        assert result.redaction_count >= 2
        description = result.describe()
        assert "Redacted before storage" in description
        assert "AWS access key" in description

    def test_clean_text_reports_nothing_removed(self):
        result = redaction.redact("Executors are restarting with OOMKilled.")
        assert not result.was_redacted
        assert result.summary == {}
        assert "No sensitive values" in result.describe()

    def test_empty_input_is_handled(self):
        for value in ("", None):
            result = redaction.redact(value)
            assert result.text == ""
            assert result.summary == {}

    def test_redact_many_combines_summaries(self):
        cleaned, summary = redaction.redact_many(
            [
                "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE",
                "contact one@example.com",
                "contact two@example.com",
            ]
        )
        assert len(cleaned) == 3
        assert summary["AWS_ACCESS_KEY"] == 1
        assert summary["EMAIL"] == 2

    def test_assert_redacted_helper_detects_leaks(self):
        with pytest.raises(AssertionError) as excinfo:
            redaction.assert_redacted("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE")
        assert "not redacted" in str(excinfo.value)
        # And passes on clean text.
        redaction.assert_redacted("Executors restarting with OOMKilled.")

    def test_redaction_is_idempotent(self):
        """
        Regression. Several patterns match on the structure *around* a secret
        (`user:SECRET@host`, `key=SECRET`), so a placeholder left by an earlier pass sits
        where a secret would and matched again — making a second scan report phantom
        findings on text that was already clean.
        """
        dirty = (
            "jdbc:postgresql://app:Pa55word@db.internal:5432/meta with "
            "api_key=7f3b9a2c8e1d4f6a0b5c9d8e and contact ops@example.com"
        )
        once = redaction.redact(dirty)
        twice = redaction.redact(once.text)

        assert twice.text == once.text, "A second pass changed already-redacted text."
        assert not twice.was_redacted, (
            f"A second pass reported phantom findings: {twice.summary}"
        )
        # And the helper agrees, which is what the LLM-layer DEBUG guard relies on.
        redaction.assert_redacted(once.text)

    def test_internal_notes_may_keep_contact_details(self):
        """
        An FDE writing "spoke to alex@customer.example about the 10.0.3.4 node" is recording
        legitimate operational context. Customer-submitted content never gets this exemption
        — only `intake.add_comment` with `is_internal=True` passes these flags.
        """
        text = "Spoke to alex@customer.example about node 10.0.3.4."
        result = redaction.redact(text, redact_emails=False, redact_ips=False)
        assert "alex@customer.example" in result.text
        assert "10.0.3.4" in result.text


@pytest.mark.django_db
class TestRedactionIsAppliedThroughoutThePipeline:
    DIRTY = (
        "The cluster fails with OOMKilled. We use "
        "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY and the connection "
        "string jdbc:postgresql://app:Pa55word!@db.internal:5432/meta. "
        "Contact ops@customer.example."
    )

    def test_a_submitted_ticket_never_stores_the_secret(
        self, make_ticket, org_a, customer_a
    ):
        ticket = make_ticket(
            organization=org_a,
            reporter=customer_a,
            description=self.DIRTY,
            error_message=self.DIRTY,
            diagnostics=self.DIRTY,
        )
        for field in (ticket.description, ticket.error_message, ticket.diagnostics):
            assert "wJalrXUtnFEMI" not in field
            assert "Pa55word!" not in field
            assert "ops@customer.example" not in field
        # And the diagnostic signal survived into the searchable text.
        assert "OOMKilled" in ticket.search_text
        assert ticket.redaction_summary

    def test_the_embedding_is_computed_from_redacted_text(
        self, make_ticket, org_a, customer_a
    ):
        """
        A vector derived from un-redacted text is a secret stored in a different encoding,
        and it would travel to an external embedding provider.
        """
        ticket = make_ticket(
            organization=org_a, reporter=customer_a, description=self.DIRTY
        )
        redaction.assert_redacted(ticket.search_text)

    def test_a_comment_is_redacted(self, make_ticket, org_a, customer_a):
        from tickets.services import intake

        ticket = make_ticket(organization=org_a, reporter=customer_a)
        event = intake.add_comment(ticket=ticket, author=customer_a, body=self.DIRTY)
        assert "wJalrXUtnFEMI" not in event.body
        assert "ops@customer.example" not in event.body

    def test_an_uploaded_text_file_is_redacted_on_disk(
        self, make_ticket, org_a, customer_a
    ):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from tickets.services import attachments

        ticket = make_ticket(organization=org_a, reporter=customer_a)
        attachment = attachments.upload(
            ticket=ticket,
            uploaded_file=SimpleUploadedFile(
                "diag.log", self.DIRTY.encode(), content_type="text/plain"
            ),
            user=customer_a,
        )
        assert attachment.redaction_applied is True
        stored = attachment.file.read().decode()
        assert "wJalrXUtnFEMI" not in stored
        assert "Pa55word!" not in stored
        assert "OOMKilled" in stored

    def test_an_execution_observation_is_redacted(
        self, make_ticket, org_a, customer_a, approved_playbook
    ):
        from playbooks.services import execution as execution_service

        ticket = make_ticket(organization=org_a, reporter=customer_a)
        execution = execution_service.start(
            ticket=ticket, playbook=approved_playbook, user=customer_a
        )
        result = execution_service.advance(
            execution=execution,
            user=customer_a,
            response_value="yes",
            observation=self.DIRTY,
        )
        assert "wJalrXUtnFEMI" not in result.response.observation
