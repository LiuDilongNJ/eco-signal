from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session, select

from app.models.taxon import Taxon
from app.repositories.taxon_repository import RemoteTaxonLookupError, taxon_repository
from app.repositories import taxon_repository as taxon_module


def _create_taxon(db: Session, suffix: int, **overrides: Any) -> Taxon:
    values = {
        "cached_scientific_name": f"Species {suffix}",
        "col_species_id": f"SP{suffix}",
        "col_genus_id": f"GEN{suffix}",
        "col_family_id": f"FAM{suffix}",
        "col_order_id": f"ORD{suffix}",
        "col_class_id": f"CLS{suffix}",
    }
    values.update(overrides)
    taxon = Taxon(**values)
    db.add(taxon)
    db.commit()
    db.refresh(taxon)
    return taxon


def test_list_taxons_enriches_only_paginated_ids(
    db: Session, monkeypatch
) -> None:
    for suffix in range(1, 4):
        _create_taxon(db, suffix)
    calls: list[dict[str, set[str]]] = []

    def fetch_names(
        ids_by_rank: dict[str, set[str]],
        name_filters: dict[str, str] | None = None,
    ) -> dict[str, dict[str, str]]:
        assert name_filters is None
        calls.append(ids_by_rank)
        return {
            rank: {value: f"Name {value}" for value in values}
            for rank, values in ids_by_rank.items()
        }

    monkeypatch.setattr(taxon_repository, "_fetch_hierarchy_names", fetch_names)

    items, total = taxon_repository.list_taxons(
        db,
        page=1,
        page_size=1,
        order_by="taxon_id",
        order_dir="asc",
    )

    assert total >= 3
    assert len(items) == 1
    assert len(calls) == 1
    assert all(len(values) <= 1 for values in calls[0].values())


def test_hierarchy_lookup_query_is_always_limited_to_requested_ids(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fetch_rows(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        captured.update(sql=sql, params=params)
        return []

    monkeypatch.setattr(taxon_repository, "_fetch_geo_rows", fetch_rows)

    taxon_repository._fetch_hierarchy_names(
        {"genus": {"GEN1", "GEN2"}, "family": {"FAM1"}},
    )

    assert "unnest(CAST(:genus_ids AS varchar[]))" in captured["sql"]
    assert "col_genus_id = ids.hierarchy_id" in captured["sql"]
    assert "unnest(CAST(:family_ids AS varchar[]))" in captured["sql"]
    assert "col_family_id = ids.hierarchy_id" in captured["sql"]
    assert captured["params"] == {
        "genus_ids": ["GEN1", "GEN2"],
        "family_ids": ["FAM1"],
    }


def test_get_existing_lowest_col_ids_matches_case_insensitively(db: Session) -> None:
    _create_taxon(db, 7, col_species_id="SpMixedCase")

    found = taxon_repository.get_existing_lowest_col_ids(
        db, {"spmixedcase", "missing-id"}
    )

    assert "spmixedcase" in found
    assert "missing-id" not in found


def test_get_existing_lowest_col_ids_returns_empty_for_empty_input(db: Session) -> None:
    assert taxon_repository.get_existing_lowest_col_ids(db, set()) == set()


@pytest.mark.parametrize("method", ["_fetch_geo_rows", "_fetch_geo_scalar"])
def test_dictionary_query_failure_returns_unavailable_and_releases_connection(
    taxon_dictionary: Session, method: str,
) -> None:
    fetch = getattr(taxon_repository, method)
    with pytest.raises(RemoteTaxonLookupError) as error:
        fetch("SELECT 1 FROM public.missing_dictionary", {})
    assert error.value.status_code == 503
    assert isinstance(error.value.__cause__, DBAPIError)
    assert taxon_repository._fetch_geo_scalar("SELECT 42", {}) == 42


def test_dictionary_slow_query_times_out_and_releases_connection(
    taxon_dictionary: Session,
) -> None:
    with pytest.raises(RemoteTaxonLookupError) as error:
        taxon_repository._fetch_geo_rows("SELECT pg_sleep(10)", {})
    assert error.value.status_code == 503
    assert isinstance(error.value.__cause__, DBAPIError)
    assert error.value.__cause__.orig.sqlstate == "57014"
    assert taxon_repository._fetch_geo_rows("SELECT 42 AS value", {}) == [{"value": 42}]


def test_dictionary_query_applies_requested_timeout(taxon_dictionary: Session) -> None:
    rows = taxon_repository._fetch_geo_rows("SHOW statement_timeout", {}, timeout_ms=60_000)
    assert rows == [{"statement_timeout": "1min"}]
    assert taxon_repository._fetch_geo_rows("SHOW statement_timeout", {}) == [{"statement_timeout": "3s"}]


def test_import_prefetch_uses_extended_timeout(monkeypatch) -> None:
    captured: list[int] = []

    def fetch_rows(_sql, _params, timeout_ms=0):
        captured.append(timeout_ms)
        return []

    monkeypatch.setattr(taxon_repository, "_fetch_geo_rows", fetch_rows)
    assert taxon_repository.prefetch_import_candidates({"Species"}) == {}
    assert captured == [taxon_module._IMPORT_STATEMENT_TIMEOUT_MS]


def test_hierarchy_options_cache_expires_and_still_requires_dictionary(
    db: Session, taxon_dictionary: Session, monkeypatch,
) -> None:
    taxon_dictionary.exec(text("INSERT INTO col_xr_taxon_species (col_class_id, col_class_name) VALUES ('C1', 'Birds')"))
    taxon_dictionary.commit()
    clock = [0.0]
    monkeypatch.setattr(taxon_module, "monotonic", lambda: clock[0])
    first = taxon_repository.get_hierarchy_options("class")
    taxon_dictionary.exec(text("UPDATE col_xr_taxon_species SET col_class_name = 'Mammals'"))
    taxon_dictionary.commit()
    assert taxon_repository.get_hierarchy_options("class") == first
    clock[0] = 301
    assert taxon_repository.get_hierarchy_options("class") == ([{"id": "C1", "name": "Mammals"}], 1)
    taxon_dictionary.exec(text("DROP TABLE col_xr_taxon_species"))
    taxon_dictionary.commit()
    with pytest.raises(RemoteTaxonLookupError) as error:
        taxon_repository.get_hierarchy_options("class")
    assert error.value.status_code == 503


def test_dictionary_import_write_failure_rolls_back_batch(db: Session, monkeypatch) -> None:
    def fail_commit():
        raise DBAPIError("insert", {}, Exception("write failed"))
    monkeypatch.setattr(db, "commit", fail_commit)
    with pytest.raises(DBAPIError):
        taxon_repository.create_imported_taxons(db, [{"lowest_col_id": "BATCH1", "col_species_id": "BATCH1"}])
    assert db.exec(select(Taxon).where(Taxon.col_species_id == "BATCH1")).all() == []


def test_local_taxon_list_keeps_business_fields_when_dictionary_is_unavailable(
    db: Session, taxon_dictionary: Session,
) -> None:
    taxon = _create_taxon(db, 99)
    taxon_dictionary.exec(text("DROP TABLE col_xr_taxon_species"))
    taxon_dictionary.commit()
    rows, total = taxon_repository.list_taxons(db, filters={"taxon_id": taxon.taxon_id})
    assert total == 1
    assert rows[0]["taxon_id"] == taxon.taxon_id
    assert rows[0]["col_species_name"] == "Species 99"
    assert rows[0]["col_genus_name"] is None


@pytest.mark.parametrize("genus_id", [None, "G-MISSING"])
def test_hierarchy_name_filter_has_no_matches_without_dictionary_names(db: Session, taxon_dictionary: Session, genus_id):
    _create_taxon(db, 101, col_genus_id=genus_id)
    assert taxon_repository.list_taxons(db, filters={"col_genus_name": "Birds"}) == ([], 0)


def test_hierarchy_sort_keeps_taxons_without_dictionary_names(db: Session, taxon_dictionary: Session):
    taxon = _create_taxon(db, 102)
    rows, total = taxon_repository.list_taxons(db, filters={"taxon_id": taxon.taxon_id}, order_by="col_genus_name")
    assert total == 1
    assert rows[0]["taxon_id"] == taxon.taxon_id
