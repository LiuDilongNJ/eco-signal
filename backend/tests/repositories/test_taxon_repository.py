from typing import Any

from sqlmodel import Session

from app.models.taxon import Taxon
from app.repositories.taxon_repository import taxon_repository


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
        _session: Session,
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


def test_hierarchy_lookup_query_is_always_limited_to_requested_ids(
    db: Session, monkeypatch
) -> None:
    captured: dict[str, Any] = {}

    def fetch_rows(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        captured.update(sql=sql, params=params)
        return []

    monkeypatch.setattr(taxon_repository, "_use_direct_geo_lookup", lambda: True)
    monkeypatch.setattr(taxon_repository, "_fetch_geo_rows", fetch_rows)

    taxon_repository._fetch_hierarchy_names(
        db,
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
