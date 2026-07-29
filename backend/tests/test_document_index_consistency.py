"""Regression tests for the temporary dual-index persistence boundary."""

import pytest

from app.api import routes
from app.services import document_qa_service


class _LegacyStore:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.deleted: list[int] = []

    def delete_document(self, document_id: int) -> None:
        self.deleted.append(document_id)
        if self.fail:
            raise RuntimeError("legacy delete failed")


class _DocumentService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.deleted: list[int] = []

    def delete_document(self, document_id: int) -> None:
        self.deleted.append(document_id)
        if self.fail:
            raise RuntimeError("chroma delete failed")


def test_remove_document_indexes_updates_both_stores(monkeypatch):
    legacy = _LegacyStore()
    document_service = _DocumentService()
    monkeypatch.setattr(
        document_qa_service,
        "get_document_qa_service",
        lambda: document_service,
    )

    routes.remove_document_indexes(42, legacy)

    assert legacy.deleted == [42]
    assert document_service.deleted == [42]


def test_remove_document_indexes_attempts_both_before_failing(monkeypatch):
    legacy = _LegacyStore(fail=True)
    document_service = _DocumentService(fail=True)
    monkeypatch.setattr(
        document_qa_service,
        "get_document_qa_service",
        lambda: document_service,
    )

    with pytest.raises(RuntimeError, match=r"2 index\(es\)"):
        routes.remove_document_indexes(43, legacy)

    assert legacy.deleted == [43]
    assert document_service.deleted == [43]
