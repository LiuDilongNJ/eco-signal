from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlmodel import Session, SQLModel, func, select

ModelType = TypeVar("ModelType", bound=SQLModel)
CreateSchemaType = TypeVar("CreateSchemaType", bound=SQLModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=SQLModel)


class BaseRepository(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    """
    Base repository class with generic CRUD operations.
    
    Attributes:
        model: SQLModel class for the entity
    """
    
    def __init__(self, model: type[ModelType]):
        """
        Initialize repository with model class.
        
        Args:
            model: SQLModel class for the entity
        """
        self.model = model
    
    def get(self, session: Session, id: UUID | int) -> ModelType | None:
        """
        Get a single record by ID.
        
        Args:
            session: Database session
            id: Record ID
        
        Returns:
            Record if found, None otherwise
        """
        return session.get(self.model, id)
    
    def get_multi_paginated(
        self, 
        session: Session, 
        *, 
        page: int = 1, 
        page_size: int = 15,
        filters: dict[str, Any] | None = None
    ) -> dict:
        """
        Get multiple records with pagination and full pagination info.
        
        Args:
            session: Database session
            page: Page number (1-indexed)
            page_size: Number of records per page
            filters: Optional dict of field_name: value pairs for filtering.
                     Supports special operators:
                     - "field__like": value -> field ILIKE %value%
                     - "field": value -> field == value
        
        Returns:
            Dict with data, count, page, page_size, and total_pages
        """
        # Calculate skip from page number
        skip = (page - 1) * page_size
        
        # Build base queries
        base_query = select(self.model)
        count_query = select(func.count()).select_from(self.model)
        
        # Apply filters
        if filters:
            for key, value in filters.items():
                if value is None:
                    continue
                if key.endswith("__like"):
                    # Fuzzy search: field__like -> ILIKE
                    field_name = key[:-6]  # Remove "__like"
                    if hasattr(self.model, field_name):
                        field = getattr(self.model, field_name)
                        base_query = base_query.where(field.ilike(f"%{value}%"))
                        count_query = count_query.where(field.ilike(f"%{value}%"))
                else:
                    # Exact match
                    if hasattr(self.model, key):
                        field = getattr(self.model, key)
                        base_query = base_query.where(field == value)
                        count_query = count_query.where(field == value)
        
        # Get total count
        count = session.exec(count_query).one()
        
        # Calculate total pages
        total_pages = (count + page_size - 1) // page_size if count > 0 else 0
        
        # Get paginated data
        data_query = base_query.offset(skip).limit(page_size)
        data = list(session.exec(data_query).all())
        
        return {
            "data": data,
            "count": count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }
    
    def create(self, session: Session, *, obj_in: CreateSchemaType) -> ModelType:
        """
        Create a new record.
        
        Args:
            session: Database session
            obj_in: Creation schema data
        
        Returns:
            Created record
        """
        db_obj = self.model.model_validate(obj_in)
        session.add(db_obj)
        session.commit()
        session.refresh(db_obj)
        return db_obj
    
    def update(
        self, session: Session, *, db_obj: ModelType, obj_in: UpdateSchemaType | dict[str, Any]
    ) -> ModelType:
        """
        Update an existing record.
        
        Args:
            session: Database session
            db_obj: Existing database object
            obj_in: Update schema data or dict
        
        Returns:
            Updated record
        """
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.model_dump(exclude_unset=True)
        
        db_obj.sqlmodel_update(update_data)
        session.add(db_obj)
        session.commit()
        session.refresh(db_obj)
        return db_obj
    
    def delete(self, session: Session, *, id: UUID | int) -> ModelType | None:
        """
        Delete a record by ID.
        
        Args:
            session: Database session
            id: Record ID
        
        Returns:
            Deleted record if found, None otherwise
        """
        obj = session.get(self.model, id)
        if obj:
            session.delete(obj)
            session.commit()
        return obj
    
