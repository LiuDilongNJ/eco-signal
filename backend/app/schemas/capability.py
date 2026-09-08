from sqlmodel import SQLModel


class ProjectCapabilities(SQLModel):
    edit: bool = False
    delete: bool = False
    link: bool = False


class CollectionCapabilities(SQLModel):
    edit: bool = False
    delete: bool = False
    set_taxons: bool = False
    export_bundle: bool = False


class MediaCapabilities(SQLModel):
    edit: bool = False
    delete: bool = False
    link: bool = False
    assign: bool = False
    run_analysis: bool = False
    run_ai_models: bool = False
    create_annotation: bool = False


class SiteCapabilities(SQLModel):
    edit: bool = False
    delete: bool = False
    link: bool = False


class AnnotationCapabilities(SQLModel):
    edit: bool = False
    delete: bool = False
    assign: bool = False
    create_review: bool = False


class ReviewCapabilities(SQLModel):
    edit: bool = False
    delete: bool = False


class TaskCapabilities(SQLModel):
    delete: bool = False


class IndexLogCapabilities(SQLModel):
    delete: bool = False


class QueueCapabilities(SQLModel):
    delete: bool = False


class UserCapabilities(SQLModel):
    edit: bool = False
    delete: bool = False
    reset_password: bool = False
    manage_permissions: bool = False
    set_contributor: bool = False
