"""Unit tests for BaseRepository (repositories/base.py)."""
from sqlmodel import Session

from app.models.index import IndexType
from app.repositories.index_repository import index_type_repository


class TestBaseRepositoryGetMultiPaginated:
    """Tests for get_multi_paginated (lines 84-119)."""

    def test_paginated_no_filters(self, db: Session):
        """Returns correct pagination structure without filters."""
        db.add(IndexType(name="BASE_PAG_1"))
        db.add(IndexType(name="BASE_PAG_2"))
        db.commit()

        result = index_type_repository.get_multi_paginated(db, page=1, page_size=10)
        assert "data" in result
        assert "count" in result
        assert "page" in result
        assert "page_size" in result
        assert "total_pages" in result

    def test_paginated_with_exact_filter(self, db: Session):
        """Exact-match filter narrows results correctly."""
        db.add(IndexType(name="BASE_EXACT_UNIQUE_XYZ"))
        db.commit()

        result = index_type_repository.get_multi_paginated(
            db, page=1, page_size=10, filters={"name": "BASE_EXACT_UNIQUE_XYZ"}
        )
        assert result["count"] == 1
        assert result["data"][0].name == "BASE_EXACT_UNIQUE_XYZ"

    def test_paginated_with_like_filter(self, db: Session):
        """__like filter performs case-insensitive substring search."""
        db.add(IndexType(name="BASE_LIKE_FUZZY_TEST"))
        db.commit()

        result = index_type_repository.get_multi_paginated(
            db, page=1, page_size=10, filters={"name__like": "FUZZY_TEST"}
        )
        assert result["count"] >= 1

    def test_paginated_none_filter_value_skipped(self, db: Session):
        """Filter entries with None values are skipped."""
        db.add(IndexType(name="BASE_NONE_FILTER"))
        db.commit()

        result = index_type_repository.get_multi_paginated(
            db, page=1, page_size=10, filters={"name": None}
        )
        assert result["count"] >= 1

    def test_paginated_unknown_field_skipped(self, db: Session):
        """Filters on non-existent fields are silently skipped."""
        result = index_type_repository.get_multi_paginated(
            db, page=1, page_size=10, filters={"nonexistent_field": "value"}
        )
        assert "data" in result

    def test_paginated_zero_count(self, db: Session):
        """total_pages is 0 when count is 0."""
        result = index_type_repository.get_multi_paginated(
            db, page=1, page_size=10, filters={"name": "ABSOLUTELY_NONEXISTENT_ZZZZZ"}
        )
        assert result["count"] == 0
        assert result["total_pages"] == 0


class TestBaseRepositoryUpdate:
    """Tests for update with schema object (line 161)."""

    def test_update_with_schema(self, db: Session):
        """update() accepts a schema object (not just a dict)."""
        from app.schemas.role import RoleUpdate

        # Use IndexType directly; update via dict is simpler since it doesn't have a schema
        # Instead use role_repository which has RoleCreate/RoleUpdate schemas
        from app.models.user import Role
        from app.repositories.role_repository import role_repository

        role = Role(name="BASE_UPDATE_ROLE")
        db.add(role)
        db.commit()
        db.refresh(role)

        update_schema = RoleUpdate(name="BASE_UPDATE_ROLE_RENAMED")
        updated = role_repository.update(db, db_obj=role, obj_in=update_schema)
        assert updated.name == "BASE_UPDATE_ROLE_RENAMED"
