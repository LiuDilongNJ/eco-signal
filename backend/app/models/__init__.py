"""
Database models package.

This module exports all SQLModel database models for the ecoSignal application.
"""

# Annotations & Taxonomy
from app.models.annotation import (
    Annotation,
    AnnotationBase,
    AnnotationReview,
    AnnotationReviewStatus,
)
from app.models.collection import (
    Collection,
    CollectionBase,
    CollectionContributor,
    CollectionTaxon,
)
from app.models.collection_bundle_export import CollectionBundleExport
# Devices & Sensors
from app.models.device import (
    Camera,
    CameraLens,
    Lens,
    Microphone,
    Recorder,
    RecorderMicrophone,
    Sensor,
)
from app.models.effective_permission import UserEffectivePermission
# Acoustic Indices
from app.models.index import IndexLog, IndexType
from app.models.label import Label, LabelMedia
# Media & Content
from app.models.media import (
    AudioSetting,
    License,
    Media,
    MediaBase,
    MediaCollection,
    PhotoSetting,
    Preview,
)
# Network Federation
from app.models.network import NetworkNode
from app.models.operation_log import OperationLog
from app.models.permission import Permission, UserPermission
# Projects & Collections
from app.models.project import Project, ProjectBase, ProjectCollection, ProjectContributor
# Sites & Geography
from app.models.site import IucnGet, Site, SiteBase, SiteCollection, SiteProject, IhoSeaArea
# System Management
from app.models.system import FileUpload, MLModel, News, Queue, Setting
# Tasks
from app.models.task import Task
from app.models.taxon import SoundClassification, Taxon, TaxonBase, TaxonSoundType
# User & Auth
from app.models.user import Role, User, UserBase, UserPreference

__all__ = [
    # User & Auth
    "Role",
    "User",
    "UserBase",
    "UserPreference",
    "Permission",
    "UserPermission",
    # Projects & Collections
    "Project",
    "ProjectBase",
    "ProjectContributor",
    "ProjectCollection",
    "Collection",
    "CollectionBase",
    "CollectionContributor",
    "CollectionTaxon",
    "CollectionBundleExport",
    # Sites & Geography
    "IucnGet",
    "Site",
    "SiteBase",
    "SiteCollection",
    "SiteProject",
    "IhoSeaArea",
    # Devices & Sensors
    "Recorder",
    "Microphone",
    "RecorderMicrophone",
    "Camera",
    "Lens",
    "CameraLens",
    "Sensor",
    # Media & Content
    "License",
    "AudioSetting",
    "PhotoSetting",
    "Media",
    "MediaBase",
    "MediaCollection",
    "Preview",
    # Annotations & Taxonomy
    "AnnotationReviewStatus",
    "Annotation",
    "AnnotationBase",
    "AnnotationReview",
    "Taxon",
    "TaxonBase",
    "TaxonSoundType",
    "SoundClassification",
    # Acoustic Indices
    "IndexType",
    "IndexLog",
    # System Management
    "MLModel",
    "Queue",
    "News",
    "Setting",
    "FileUpload",
    "OperationLog",
    # Network Federation
    "NetworkNode",
    "Label",
    "LabelMedia",
    # Tasks
    "Task",
    # Permission View
    "UserEffectivePermission",
]
