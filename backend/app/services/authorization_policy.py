from dataclasses import dataclass
from enum import StrEnum


class AuthorizationAction(StrEnum):
    PROJECT_EDIT = "project.edit"
    PROJECT_DELETE = "project.delete"
    PROJECT_LINK = "project.link"
    COLLECTION_EDIT = "collection.edit"
    COLLECTION_VIEW = "collection.view"
    COLLECTION_DELETE = "collection.delete"
    COLLECTION_SET_TAXONS = "collection.set_taxons"
    COLLECTION_EXPORT_BUNDLE = "collection.export_bundle"
    MEDIA_EDIT = "media.edit"
    MEDIA_DELETE = "media.delete"
    MEDIA_LINK = "media.link"
    MEDIA_ASSIGN = "media.assign"
    MEDIA_RUN_AI_MODELS = "analysis.ai_models.run"
    MEDIA_RUN_ACOUSTIC = "analysis.acoustic.run"
    MEDIA_CREATE_ANNOTATION = "annotation.create"
    SITE_EDIT = "site.edit"
    SITE_DELETE = "site.delete"
    SITE_LINK = "site.link"
    ANNOTATION_EDIT = "annotation.edit"
    ANNOTATION_DELETE = "annotation.delete"
    ANNOTATION_ASSIGN = "annotation.assign"
    ANNOTATION_CREATE_REVIEW = "review.create"
    REVIEW_EDIT = "review.edit"
    REVIEW_DELETE = "review.delete"
    TASK_DELETE = "task.delete"
    TASK_VIEW = "task.view"
    INDEX_LOG_DELETE = "index_log.delete"
    QUEUE_DELETE = "queue.delete"


@dataclass(frozen=True)
class AuthorizationPolicy:
    resource_type: str | None = None
    action: str | None = None
    own_action: str | None = None
    allow_owner: bool = False
    allow_uploader: bool = False
    admin_only: bool = False
    project_scoped: bool = False


AUTHORIZATION_POLICIES: dict[AuthorizationAction, AuthorizationPolicy] = {
    AuthorizationAction.PROJECT_EDIT: AuthorizationPolicy("project", "write", project_scoped=True),
    AuthorizationAction.PROJECT_DELETE: AuthorizationPolicy(admin_only=True),
    AuthorizationAction.PROJECT_LINK: AuthorizationPolicy("project", "write", project_scoped=True),
    AuthorizationAction.COLLECTION_EDIT: AuthorizationPolicy("collection", "write"),
    AuthorizationAction.COLLECTION_VIEW: AuthorizationPolicy("collection", "read"),
    AuthorizationAction.COLLECTION_DELETE: AuthorizationPolicy("project", "write", project_scoped=True),
    AuthorizationAction.COLLECTION_SET_TAXONS: AuthorizationPolicy("collection", "write"),
    AuthorizationAction.COLLECTION_EXPORT_BUNDLE: AuthorizationPolicy("project", "write", project_scoped=True),
    AuthorizationAction.MEDIA_EDIT: AuthorizationPolicy("media", "write"),
    AuthorizationAction.MEDIA_DELETE: AuthorizationPolicy("media", "write"),
    AuthorizationAction.MEDIA_LINK: AuthorizationPolicy("media", "write"),
    AuthorizationAction.MEDIA_ASSIGN: AuthorizationPolicy("collection", "write"),
    AuthorizationAction.MEDIA_RUN_AI_MODELS: AuthorizationPolicy("media", "read", allow_uploader=True),
    AuthorizationAction.MEDIA_RUN_ACOUSTIC: AuthorizationPolicy("collection", "write", allow_uploader=True),
    AuthorizationAction.MEDIA_CREATE_ANNOTATION: AuthorizationPolicy("annotation", "write", "write_own"),
    AuthorizationAction.SITE_EDIT: AuthorizationPolicy("site", "write"),
    AuthorizationAction.SITE_DELETE: AuthorizationPolicy("site", "write"),
    AuthorizationAction.SITE_LINK: AuthorizationPolicy("site", "write"),
    AuthorizationAction.ANNOTATION_EDIT: AuthorizationPolicy(
        "annotation", "write", "write_own", allow_owner=True
    ),
    AuthorizationAction.ANNOTATION_DELETE: AuthorizationPolicy(
        "annotation", "write", "write_own", allow_owner=True
    ),
    AuthorizationAction.ANNOTATION_ASSIGN: AuthorizationPolicy("collection", "write"),
    AuthorizationAction.ANNOTATION_CREATE_REVIEW: AuthorizationPolicy("review", "write", "write_own"),
    AuthorizationAction.REVIEW_EDIT: AuthorizationPolicy(
        "review", "write", "write_own", allow_owner=True
    ),
    AuthorizationAction.REVIEW_DELETE: AuthorizationPolicy(
        "review", "write", "write_own", allow_owner=True
    ),
    AuthorizationAction.TASK_DELETE: AuthorizationPolicy("collection", "write", allow_owner=True),
    AuthorizationAction.TASK_VIEW: AuthorizationPolicy("collection", "write", allow_owner=True),
    AuthorizationAction.INDEX_LOG_DELETE: AuthorizationPolicy("collection", "write", allow_owner=True),
    AuthorizationAction.QUEUE_DELETE: AuthorizationPolicy(allow_owner=True),
}
