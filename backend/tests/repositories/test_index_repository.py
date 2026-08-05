"""Unit tests for IndexTypeRepository (index_repository.py)."""
from sqlmodel import Session

from app.models.index import IndexType
from app.repositories.index_repository import index_type_repository


class TestIndexTypeRepository:
    """Tests for IndexTypeRepository."""

    def test_get_by_name_returns_existing(self, db: Session):
        """get_by_name returns the matching IndexType."""
        index_type = IndexType(name="ACI_TEST", description="Test index")
        db.add(index_type)
        db.commit()
        db.refresh(index_type)

        result = index_type_repository.get_by_name(db, "ACI_TEST")

        assert result is not None
        assert result.name == "ACI_TEST"
        assert result.index_id == index_type.index_id

    def test_get_by_name_returns_none_for_missing(self, db: Session):
        """get_by_name returns None when name does not exist."""
        result = index_type_repository.get_by_name(db, "NONEXISTENT_INDEX_XYZ")

        assert result is None

    def test_get_or_create_creates_new(self, db: Session):
        """get_or_create inserts and returns a new IndexType."""
        result = index_type_repository.get_or_create(
            db, name="NDSI_REPO_TEST", description="Created by test"
        )

        assert result is not None
        assert result.name == "NDSI_REPO_TEST"
        assert result.description == "Created by test"
        assert result.index_id is not None

    def test_get_or_create_returns_existing(self, db: Session):
        """get_or_create returns the existing record without duplicating."""
        existing = IndexType(name="BI_REPO_TEST", description="Original")
        db.add(existing)
        db.commit()
        db.refresh(existing)

        result = index_type_repository.get_or_create(db, name="BI_REPO_TEST")

        assert result.index_id == existing.index_id
        assert result.name == "BI_REPO_TEST"

    def test_get_or_create_without_description(self, db: Session):
        """get_or_create works when description is omitted."""
        result = index_type_repository.get_or_create(db, name="H_REPO_TEST")

        assert result is not None
        assert result.name == "H_REPO_TEST"
        assert result.description is None
