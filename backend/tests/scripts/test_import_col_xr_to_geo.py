import csv
import importlib.util
import sys
from pathlib import Path


def _load_script_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "import_col_xr_to_geo.py"
    script_dir = str(script_path.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    spec = importlib.util.spec_from_file_location("import_col_xr_to_geo", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def test_resolve_lineage_ids_returns_real_rank_ids():
    module = _load_script_module()

    index = {
        "SP1": {"parent_id": "GEN1", "rank": "species", "scientific_name": "Species one"},
        "GEN1": {"parent_id": "FAM1", "rank": "genus", "scientific_name": "Genus one"},
        "FAM1": {"parent_id": "ORD1", "rank": "family", "scientific_name": "Family one"},
        "ORD1": {"parent_id": "CLS1", "rank": "order", "scientific_name": "Order one"},
        "CLS1": {"parent_id": None, "rank": "class", "scientific_name": "Class one"},
    }

    lineage = module._resolve_lineage_ids("SP1", index)

    assert lineage == {
        "col_genus_id": "GEN1",
        "col_family_id": "FAM1",
        "col_order_id": "ORD1",
        "col_class_id": "CLS1",
    }


def test_normalize_writes_lineage_ids_not_rank_names(tmp_path):
    module = _load_script_module()
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    nameusage_rows = [
        {
            "col:ID": "SP1",
            "col:parentID": "GEN1",
            "col:status": "accepted",
            "col:scientificName": "Species one",
            "col:rank": "species",
            "col:genus": "Genus name",
            "col:family": "Family name",
            "col:order": "Order name",
            "col:class": "Class name",
        },
        {
            "col:ID": "GEN1",
            "col:parentID": "FAM1",
            "col:status": "accepted",
            "col:scientificName": "Genus name",
            "col:rank": "genus",
            "col:genus": "Genus name",
            "col:family": "Family name",
            "col:order": "Order name",
            "col:class": "Class name",
        },
        {
            "col:ID": "FAM1",
            "col:parentID": "ORD1",
            "col:status": "accepted",
            "col:scientificName": "Family name",
            "col:rank": "family",
            "col:genus": "",
            "col:family": "Family name",
            "col:order": "Order name",
            "col:class": "Class name",
        },
        {
            "col:ID": "ORD1",
            "col:parentID": "CLS1",
            "col:status": "accepted",
            "col:scientificName": "Order name",
            "col:rank": "order",
            "col:genus": "",
            "col:family": "",
            "col:order": "Order name",
            "col:class": "Class name",
        },
        {
            "col:ID": "CLS1",
            "col:parentID": "",
            "col:status": "accepted",
            "col:scientificName": "Class name",
            "col:rank": "class",
            "col:genus": "",
            "col:family": "",
            "col:order": "",
            "col:class": "Class name",
        },
    ]
    _write_tsv(
        input_dir / "NameUsage.tsv",
        [
            "col:ID",
            "col:parentID",
            "col:status",
            "col:scientificName",
            "col:rank",
            "col:genus",
            "col:family",
            "col:order",
            "col:class",
        ],
        nameusage_rows,
    )
    _write_tsv(
        input_dir / "VernacularName.tsv",
        ["col:taxonID", "col:name", "col:language", "col:preferred"],
        [{"col:taxonID": "SP1", "col:name": "Species Common", "col:language": "eng", "col:preferred": "true"}],
    )
    (input_dir / "metadata.yaml").write_text("alias: COL26.3 XR\n", encoding="utf-8")

    module.WORKING_ROOT = tmp_path / "working"
    stats = module.RunStats(run_id="col_xr_263", source_alias="COL26.3 XR", input_dir=str(input_dir))

    output_file = module.normalize(input_dir=input_dir, run_id="col_xr_263", stats=stats)

    with output_file.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))

    assert len(rows) == 1
    assert rows[0]["col_species_id"] == "SP1"
    assert rows[0]["cached_common_name"] == ""
    assert rows[0]["col_genus_id"] == "GEN1"
    assert rows[0]["col_genus_name"] == "Genus name"
    assert rows[0]["col_family_id"] == "FAM1"
    assert rows[0]["col_family_name"] == "Family name"
    assert rows[0]["col_order_id"] == "ORD1"
    assert rows[0]["col_order_name"] == "Order name"
    assert rows[0]["col_class_id"] == "CLS1"
    assert rows[0]["col_class_name"] == "Class name"
    assert rows[0]["col_genus_id"] != "Genus name"


def test_import_normalized_assigns_best_vernacular_name(tmp_path, monkeypatch):
    module = _load_script_module()
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    normalized_file = tmp_path / "species_accepted.tsv"

    _write_tsv(
        normalized_file,
        [
            "col_species_id",
            "cached_scientific_name",
            "cached_common_name",
            "col_genus_id",
            "col_genus_name",
            "col_family_id",
            "col_family_name",
            "col_order_id",
            "col_order_name",
            "col_class_id",
            "col_class_name",
        ],
        [
            {
                "col_species_id": "SP1",
                "cached_scientific_name": "Species one",
                "cached_common_name": "",
                "col_genus_id": "GEN1",
                "col_genus_name": "Genus one",
                "col_family_id": "FAM1",
                "col_family_name": "Family one",
                "col_order_id": "ORD1",
                "col_order_name": "Order one",
                "col_class_id": "CLS1",
                "col_class_name": "Class one",
            }
        ],
    )
    _write_tsv(
        input_dir / "VernacularName.tsv",
        ["col:taxonID", "col:name", "col:language", "col:preferred"],
        [
            {"col:taxonID": "SP1", "col:name": "Species One", "col:language": "eng", "col:preferred": "false"},
            {"col:taxonID": "SP1", "col:name": "Preferred Species One", "col:language": "eng", "col:preferred": "true"},
        ],
    )

    captured: dict[str, list[dict[str, str]]] = {}

    class DummyConn:
        def execute(self, *_args, **_kwargs):
            class DummyResult:
                def scalar_one(self):
                    return 0

            return DummyResult()

    class DummyBegin:
        def __enter__(self):
            return DummyConn()

        def __exit__(self, exc_type, exc, tb):
            return False

    class DummyEngine:
        def begin(self):
            return DummyBegin()

    def fake_create_engine(*_args, **_kwargs):
        return DummyEngine()

    def fake_ensure_geo_tables(_conn):
        return None

    def fake_text(sql):
        return sql

    original_execute = DummyConn.execute

    def capturing_execute(self, statement, params=None, **kwargs):
        if isinstance(statement, str) and statement.lstrip().startswith("INSERT INTO col_xr_taxon_species_stage"):
            captured["stage_rows"] = params
        return original_execute(self, statement, params=params, **kwargs)

    monkeypatch.setattr(module, "create_engine", fake_create_engine)
    monkeypatch.setattr(module, "_ensure_geo_tables", fake_ensure_geo_tables)
    monkeypatch.setattr(module, "text", fake_text)
    monkeypatch.setattr(DummyConn, "execute", capturing_execute)

    stats = module.RunStats(run_id="col_xr_263", source_alias="COL26.3 XR", input_dir=str(input_dir))
    module.import_normalized(
        input_dir=input_dir,
        normalized_file=normalized_file,
        run_id="col_xr_263",
        batch_size=100,
        dry_run=False,
        stats=stats,
    )

    assert stats.vernacular_assigned_rows == 1
    assert captured["stage_rows"][0]["cached_common_name"] == "Preferred Species One"
