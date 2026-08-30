from sqlmodel import SQLModel


class RowCapabilities(SQLModel):
    """Operation capabilities for one list row."""

    edit: bool = False
    delete: bool = False
    link: bool = False
    assign: bool = False
    run_analysis: bool = False
    set_taxons: bool = False
    export_bundle: bool = False
    reset_password: bool = False
    manage_permissions: bool = False
    set_contributor: bool = False
