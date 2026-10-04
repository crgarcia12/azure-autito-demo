import io
import json
import hashlib

from docx import Document
import pytest

from fleet import repair_policy
from tools.publish_repair_policy import build_document


def test_word_document_contains_the_complete_versioned_policy():
    policy = repair_policy.repair_policy()
    document = Document(io.BytesIO(build_document(policy)))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert policy["id"] in text and f"Version {policy['version']}" in text
    assert policy["effective_date"] in text
    assert "New genuine OEM replacement parts only" in text
    for clause in policy["clauses"]:
        assert clause["id"] in text and clause["title"] in text
        assert clause["text"] in text
    assert document.core_properties.author == policy["owner"]
    assert document.styles["Normal"].font.name == "Aptos"
    assert policy["downtime_cost_per_day"] == 100 and policy["maximum_repair_quote"] == 2500


def test_policy_source_changes_require_word_republication(tmp_path, monkeypatch):
    publication = tmp_path / "publication.json"
    publication.write_text(json.dumps({"source_sha256": "outdated"}), encoding="utf-8")
    monkeypatch.setattr(repair_policy, "PUBLICATION_PATH", publication)
    with pytest.raises(ValueError, match="Republish"):
        repair_policy.policy_reference()


def test_local_word_is_the_exact_published_version():
    reference = repair_policy.policy_reference()
    payload = repair_policy.POLICY_PATH.with_name("Caldova-Repair-Policy.docx").read_bytes()
    assert hashlib.sha256(payload).hexdigest() == reference["document_sha256"]
    assert reference["document_url"].startswith("https://caldova08667473-my.sharepoint.com/")
