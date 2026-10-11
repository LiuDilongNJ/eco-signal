from unittest.mock import MagicMock

import pytest
from sqlalchemy import text
from sqlmodel import Session, select

from app.models.taxon import Taxon
from app.services import taxon_service


HEADER = "cached_scientific_name,cached_common_name,col_genus_name,col_family_name,col_order_name,col_class_name,taxonomy_source\n"
ROW = "Species,Common,,,,,Dictionary\n"


@pytest.mark.parametrize("content,reason", [("", "empty"), ('"unfinished', "Malformed CSV")])
def test_import_invalid_file_does_not_query_dictionary(monkeypatch, content, reason):
    repository = MagicMock()
    monkeypatch.setattr(taxon_service, "taxon_repository", repository)
    report = taxon_service.import_taxons_csv(MagicMock(), content)
    assert reason in report.global_errors[0]
    assert not report.committed
    repository.ensure_import_dictionary.assert_not_called()
    repository.create_imported_taxons.assert_not_called()


@pytest.mark.parametrize("row", ["Species,Common,,,,,Dictionary,extra\n", "Species,,,,,,Dictionary\n"])
def test_import_invalid_row_rejects_entire_file(monkeypatch, row):
    repository = MagicMock()
    monkeypatch.setattr(taxon_service, "taxon_repository", repository)
    report = taxon_service.import_taxons_csv(MagicMock(), HEADER + ROW + row)
    assert report.failed == 2
    assert report.succeeded == 0
    assert not report.committed
    assert report.rows[0].reason == "No data was written because another row failed validation"
    repository.create_imported_taxons.assert_not_called()


@pytest.mark.parametrize("dry_run", [False, True])
def test_import_missing_dictionary_reports_error_without_writing(
    db: Session, taxon_dictionary: Session, dry_run: bool,
):
    taxon_dictionary.exec(text("DROP TABLE col_xr_taxon_species"))
    taxon_dictionary.commit()
    report = taxon_service.import_taxons_csv(db, HEADER + ROW, dry_run=dry_run)
    assert report.global_errors == ["Taxon dictionary is unavailable"]
    assert not report.committed
    assert report.rows[0].status == ("succeeded" if dry_run else "failed")
    assert db.exec(select(Taxon).where(Taxon.cached_scientific_name == "Species")).all() == []


def test_import_dry_run_resolves_dictionary_without_creating_taxon(db: Session, taxon_dictionary: Session):
    taxon_dictionary.exec(text("""
        INSERT INTO col_xr_taxon_species (col_species_id, cached_scientific_name)
        VALUES ('DRY1', 'Species')
    """))
    taxon_dictionary.commit()
    report = taxon_service.import_taxons_csv(db, HEADER + ROW, dry_run=True)
    assert report.succeeded == 1
    assert not report.failed and not report.global_errors and not report.committed
    assert db.exec(select(Taxon).where(Taxon.col_species_id == "DRY1")).all() == []
