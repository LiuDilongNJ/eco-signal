from sqlmodel import Session

from app.repositories.sound_classification_repository import (
    sound_classification_repository,
)
from app.schemas.sound_classification import SoundClassificationWrite


def test_list_page_filters_and_orders(db: Session) -> None:
    first = sound_classification_repository.create(
        db,
        SoundClassificationWrite(
            soundscape_component="repository-component",
            sound_type="alpha-repository",
        ),
    )
    second = sound_classification_repository.create(
        db,
        SoundClassificationWrite(
            soundscape_component="repository-component",
            sound_type="beta-repository",
        ),
    )

    items, total = sound_classification_repository.list_page(
        db,
        page=1,
        page_size=1,
        filters={"soundscape_component": "repository"},
        order_by="sound_type",
        order_dir="desc",
    )

    assert total == 2
    assert [item.sound_id for item in items] == [second.sound_id]
    assert first.sound_id != second.sound_id


def test_create_many_preserves_duplicates_and_null_values(db: Session) -> None:
    rows = [
        SoundClassificationWrite(soundscape_component="bulk-component", sound_type=None),
        SoundClassificationWrite(soundscape_component="bulk-component", sound_type=None),
    ]

    items = sound_classification_repository.create_many(db, rows)

    assert len(items) == 2
    assert items[0].sound_id != items[1].sound_id
    assert all(item.sound_type is None for item in items)


def test_update_export_and_delete(db: Session) -> None:
    item = sound_classification_repository.create(
        db,
        SoundClassificationWrite(soundscape_component="repository-update", sound_type="before"),
    )

    updated = sound_classification_repository.update(
        db,
        item,
        SoundClassificationWrite(soundscape_component="repository-update", sound_type="after"),
    )
    exported = sound_classification_repository.list_for_export(db, "sound_id", "desc")

    assert updated.sound_type == "after"
    assert any(row.sound_id == item.sound_id for row in exported)
    assert sound_classification_repository.is_referenced(db, item.sound_id) is False
    sound_classification_repository.delete(db, item)
    assert sound_classification_repository.get(db, item.sound_id) is None


def test_get_existing_keys_normalizes_and_keeps_null(db: Session) -> None:
    sound_classification_repository.create(
        db,
        SoundClassificationWrite(soundscape_component="  Existing-Component ", sound_type="  Alpha "),
    )
    sound_classification_repository.create(
        db,
        SoundClassificationWrite(soundscape_component="Null-Type", sound_type=None),
    )

    keys = sound_classification_repository.get_existing_keys(db)

    assert ("existing-component", "alpha") in keys
    assert ("null-type", None) in keys
