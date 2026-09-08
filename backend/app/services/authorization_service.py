from dataclasses import dataclass
from functools import cached_property

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.models.collection import Collection
from app.models.media import MediaCollection
from app.models.project import ProjectCollection
from app.models.user import User
from app.repositories import permission_repository
from app.schemas.capability import (
    AnnotationCapabilities,
    CollectionCapabilities,
    IndexLogCapabilities,
    MediaCapabilities,
    ProjectCapabilities,
    QueueCapabilities,
    ReviewCapabilities,
    SiteCapabilities,
    TaskCapabilities,
    UserCapabilities,
)
from app.services.access_scope_service import resolve_collection_project_id
from app.services.authorization_policy import (
    AUTHORIZATION_POLICIES,
    AuthorizationAction,
)


@dataclass(frozen=True)
class AuthorizationSubject:
    collection_ids: frozenset[int] = frozenset()
    owner_id: int | None = None
    uploader_id: int | None = None


def is_admin(user: User | None) -> bool:
    if user is None or not user.role:
        return False
    return user.role.code == "administrator" or user.role.name == settings.ADMIN_ROLE_NAME


class AuthorizationEvaluator:
    """Evaluate business actions from the canonical effective-permission view."""

    def __init__(self, session: Session, user: User | None, project_id: int | None):
        self.session = session
        self.user = user
        self.project_id = project_id
        self._collection_grants: dict[tuple[str, str], frozenset[int]] = {}
        self._project_grants: dict[tuple[str, str], bool] = {}

    @cached_property
    def admin(self) -> bool:
        return is_admin(self.user)

    def _has_project_grant(self, resource_type: str, action: str) -> bool:
        key = (resource_type, action)
        if key not in self._project_grants:
            self._project_grants[key] = bool(
                self.user
                and self.user.user_id is not None
                and self.project_id is not None
                and permission_repository.has_effective_permission(
                    self.session,
                    self.user.user_id,
                    resource_type,
                    action,
                    project_id=self.project_id,
                    scope_type="project",
                )
            )
        return self._project_grants[key]

    def collection_grants(self, resource_type: str, action: str) -> frozenset[int]:
        key = (resource_type, action)
        if key not in self._collection_grants:
            if self.user is None or self.user.user_id is None:
                granted = frozenset()
            elif self.project_id is None:
                granted = frozenset(
                    permission_repository.get_accessible_collection_ids(
                        self.session,
                        self.user.user_id,
                        resource_type,
                        action,
                    )
                )
            else:
                granted = frozenset(
                    permission_repository.get_accessible_project_collection_ids(
                        self.session,
                        self.user.user_id,
                        self.project_id,
                        resource_type,
                        action,
                    )
                )
            self._collection_grants[key] = granted
        return self._collection_grants[key]

    def allows(self, action: AuthorizationAction, subject: AuthorizationSubject | None = None) -> bool:
        subject = subject or AuthorizationSubject()
        if self.admin:
            return True

        policy = AUTHORIZATION_POLICIES[action]
        user_id = self.user.user_id if self.user else None
        if policy.admin_only or user_id is None:
            return False
        if policy.allow_uploader and subject.uploader_id == user_id:
            return True
        if policy.allow_owner and subject.owner_id == user_id:
            if policy.own_action and policy.resource_type:
                return bool(
                    subject.collection_ids
                    & self.collection_grants(policy.resource_type, policy.own_action)
                )
            return True
        if policy.resource_type is None or policy.action is None:
            return False
        if policy.project_scoped:
            return self._has_project_grant(policy.resource_type, policy.action)
        if subject.collection_ids & self.collection_grants(policy.resource_type, policy.action):
            return True
        if policy.own_action and not policy.allow_owner:
            return bool(
                subject.collection_ids
                & self.collection_grants(policy.resource_type, policy.own_action)
            )
        return False

    def require(
        self,
        action: AuthorizationAction,
        subject: AuthorizationSubject | None = None,
        *,
        detail: str | None = None,
    ) -> None:
        if not self.allows(action, subject):
            raise HTTPException(status_code=403, detail=detail or f"Permission required: {action.value}")

    def media_capabilities(
        self,
        collection_ids: set[int],
        *,
        uploader_id: int | None,
    ) -> MediaCapabilities:
        subject = AuthorizationSubject(
            collection_ids=frozenset(collection_ids),
            uploader_id=uploader_id,
        )
        return MediaCapabilities(
            edit=self.allows(AuthorizationAction.MEDIA_EDIT, subject),
            delete=self.allows(AuthorizationAction.MEDIA_DELETE, subject),
            link=self.allows(AuthorizationAction.MEDIA_LINK, subject),
            assign=self.allows(AuthorizationAction.MEDIA_ASSIGN, subject),
            run_analysis=self.allows(AuthorizationAction.MEDIA_RUN_ACOUSTIC, subject),
            run_ai_models=self.allows(AuthorizationAction.MEDIA_RUN_AI_MODELS, subject),
            create_annotation=self.allows(AuthorizationAction.MEDIA_CREATE_ANNOTATION, subject),
        )

    def site_capabilities(self, collection_ids: set[int]) -> SiteCapabilities:
        subject = AuthorizationSubject(collection_ids=frozenset(collection_ids))
        return SiteCapabilities(
            edit=self.allows(AuthorizationAction.SITE_EDIT, subject),
            delete=self.allows(AuthorizationAction.SITE_DELETE, subject),
            link=self.allows(AuthorizationAction.SITE_LINK, subject),
        )

    def annotation_capabilities(
        self,
        collection_ids: set[int],
        *,
        creator_id: int | None,
    ) -> AnnotationCapabilities:
        subject = AuthorizationSubject(
            collection_ids=frozenset(collection_ids),
            owner_id=creator_id,
        )
        return AnnotationCapabilities(
            edit=self.allows(AuthorizationAction.ANNOTATION_EDIT, subject),
            delete=self.allows(AuthorizationAction.ANNOTATION_DELETE, subject),
            assign=self.allows(AuthorizationAction.ANNOTATION_ASSIGN, subject),
            create_review=self.allows(AuthorizationAction.ANNOTATION_CREATE_REVIEW, subject),
        )

    def review_capabilities(
        self,
        collection_ids: set[int],
        *,
        reviewer_id: int | None,
    ) -> ReviewCapabilities:
        subject = AuthorizationSubject(
            collection_ids=frozenset(collection_ids),
            owner_id=reviewer_id,
        )
        return ReviewCapabilities(
            edit=self.allows(AuthorizationAction.REVIEW_EDIT, subject),
            delete=self.allows(AuthorizationAction.REVIEW_DELETE, subject),
        )

    def task_capabilities(self, collection_ids: set[int], *, assigner_id: int | None) -> TaskCapabilities:
        return TaskCapabilities(delete=self.allows(
            AuthorizationAction.TASK_DELETE,
            AuthorizationSubject(frozenset(collection_ids), owner_id=assigner_id),
        ))

    def index_log_capabilities(self, collection_ids: set[int], *, user_id: int | None) -> IndexLogCapabilities:
        return IndexLogCapabilities(delete=self.allows(
            AuthorizationAction.INDEX_LOG_DELETE,
            AuthorizationSubject(frozenset(collection_ids), owner_id=user_id),
        ))

    def queue_capabilities(self, *, user_id: int | None) -> QueueCapabilities:
        return QueueCapabilities(delete=self.allows(
            AuthorizationAction.QUEUE_DELETE,
            AuthorizationSubject(owner_id=user_id),
        ))

    def user_capabilities(
        self,
        *,
        target_user_id: int,
        target_is_admin: bool,
        manageable: bool | None = None,
    ) -> UserCapabilities:
        actor_id = self.user.user_id if self.user else None
        is_self = actor_id is not None and target_user_id == actor_id
        if self.admin:
            return UserCapabilities(
                edit=True,
                delete=not is_self,
                reset_password=True,
                manage_permissions=True,
                set_contributor=True,
            )
        if target_is_admin:
            return UserCapabilities(
                edit=False,
                delete=False,
                reset_password=False,
                manage_permissions=False,
                set_contributor=False,
            )
        if is_self:
            return UserCapabilities(
                edit=False,
                delete=False,
                reset_password=False,
                manage_permissions=False,
                set_contributor=True,
            )
        is_mgr = bool(manageable)
        return UserCapabilities(
            edit=is_mgr,
            delete=is_mgr,
            reset_password=is_mgr,
            manage_permissions=is_mgr,
            set_contributor=True,
        )


def evaluator(session: Session, user: User | None, project_id: int | None) -> AuthorizationEvaluator:
    return AuthorizationEvaluator(session, user, project_id)


def project_capabilities(*, admin: bool, writable: bool) -> ProjectCapabilities:
    return ProjectCapabilities(edit=admin or writable, delete=admin, link=admin or writable)


def collection_capabilities(
    *,
    admin: bool,
    writable: bool,
    project_writable: bool,
) -> CollectionCapabilities:
    return CollectionCapabilities(
        edit=admin or writable,
        delete=admin or project_writable,
        set_taxons=admin or writable,
        export_bundle=admin or project_writable,
    )


def require_collection_action(
    session: Session,
    user: User,
    action: AuthorizationAction,
    *,
    collection_id: int,
    project_id: int | None,
    not_found_detail: str = "Collection not found",
    denied_detail: str | None = None,
) -> None:
    collection = session.get(Collection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail=not_found_detail)
    resolved_project_id = resolve_collection_project_id(session, collection_id, project_id)
    evaluator(session, user, resolved_project_id).require(
        action,
        AuthorizationSubject(frozenset({collection_id})),
        detail=denied_detail,
    )


def media_collection_map(
    session: Session,
    media_ids: set[int],
    project_id: int | None,
) -> dict[int, set[int]]:
    """Load project-local collection links for a page of media records."""
    if not media_ids or project_id is None:
        return {}
    rows = session.exec(
        select(MediaCollection.media_id, MediaCollection.collection_id)
        .join(
            ProjectCollection,
            ProjectCollection.collection_id == MediaCollection.collection_id,
        )
        .where(
            MediaCollection.media_id.in_(media_ids),
            ProjectCollection.project_id == project_id,
        )
        .distinct()
    ).all()
    result: dict[int, set[int]] = {}
    for media_id, collection_id in rows:
        result.setdefault(media_id, set()).add(collection_id)
    return result
