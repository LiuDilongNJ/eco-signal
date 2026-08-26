import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, func, select

from app.ai.acoustic_indices.analyzer import AcousticIndexAnalyzer
from app.ai.batdetect.analyzer import BatDetect2Analyzer
from app.ai.birdnet.analyzer import BirdNETAnalyzer
from app.ai.insects.analyzer import InsectAnalyzer
from app.core.task_cancellation import CancellationToken
from app.enums import QueueStatus, WorkerTaskType
from app.media_paths import (
    logical_audio_media_path,
    resolve_existing_analysis_audio_media_path,
)
from app.models.annotation import Annotation
from app.models.media import AudioSetting, Media, MediaCollection
from app.models.project import ProjectCollection
from app.models.system import Queue
from app.models.taxon import Taxon
from app.models.user import User
from app.repositories import (
    annotation_repository,
    index_log_repository,
    index_type_repository,
    site_repository,
)
from app.schemas.analysis import (
    AcousticIndexPreviewRequest,
    AcousticIndexPreviewResponse,
    AcousticIndicesResponse,
    RunAcousticIndicesRequest,
    RunAnalysisRequest,
    RunAnalysisResponse,
)
from app.schemas.index_log import IndexLogCreateRequest, IndexLogCreateResponse
from app.schemas.queue import QueueDetail
from app.services import permission_service
from app.services.acoustic_selection_service import prepare_acoustic_selection
from app.workers.publisher import TaskPublisher

logger = logging.getLogger(__name__)


class AnalysisService:
    """
    Analysis service.

    Responsibilities:
    1. Call AI models for analysis
    2. Convert analysis results to annotations
    3. Store annotations to database

    Note: session is no longer passed in __init__ to align with requested pattern.
    All methods now require session: Session as an argument.
    """

    # Generic biophony sound_id (sound_classification: biophony, empty sound_type)
    BIOPHONY_SOUND_ID = 6

    # Default frequency range (Hz)
    DEFAULT_MIN_FREQ = 1
    DEFAULT_MAX_FREQ = 15000

    # Bat frequency range (Hz)
    BAT_MIN_FREQ = 15000
    BAT_MAX_FREQ = 120000
    ANNOTATION_COMMENTS_MAX_LENGTH = 500
    FULL_TIME_WINDOW_TOLERANCE_SECONDS = 0.001
    MERGE_MODEL_NAMES = {
        "BirdNET-Analyzer": "BirdNET",
        "batdetect2": "batdetect2",
        "insects-base-cnn10-96k-t": "insects-base-cnn10-96k-t",
    }

    def __init__(self):
        self._birdnet: BirdNETAnalyzer | None = None
        self._batdetect: BatDetect2Analyzer | None = None
        self._insects: InsectAnalyzer | None = None
        self._acoustic_index: AcousticIndexAnalyzer | None = None

    @property
    def birdnet(self) -> BirdNETAnalyzer:
        """Lazy load BirdNET analyzer."""
        if self._birdnet is None:
            self._birdnet = BirdNETAnalyzer()
        return self._birdnet

    @property
    def batdetect(self) -> BatDetect2Analyzer:
        """Lazy load batdetect2 analyzer."""
        if self._batdetect is None:
            self._batdetect = BatDetect2Analyzer()
        return self._batdetect

    @property
    def insects(self) -> InsectAnalyzer:
        """Lazy load insects-base-cnn10-96k-t analyzer."""
        if self._insects is None:
            self._insects = InsectAnalyzer()
        return self._insects

    @property
    def acoustic_index(self) -> AcousticIndexAnalyzer:
        """Lazy load scikit-maad acoustic index analyzer."""
        if self._acoustic_index is None:
            self._acoustic_index = AcousticIndexAnalyzer()
        return self._acoustic_index

    def _is_full_time_window(self, min_time: float, max_time: float, duration_s: float | int | None) -> bool:
        if duration_s is None:
            return False
        return (
            min_time <= self.FULL_TIME_WINDOW_TOLERANCE_SECONDS
            and abs(max_time - float(duration_s)) <= self.FULL_TIME_WINDOW_TOLERANCE_SECONDS
        )

    def _ensure_acoustic_write_access(
        self,
        session: Session,
        project_id: int,
        media_id: int,
        media: Media,
        current_user: User,
    ) -> None:
        if permission_service.is_admin(current_user) or media.uploader_id == current_user.user_id:
            return

        statement = select(MediaCollection).where(MediaCollection.media_id == media_id)
        collections = session.exec(statement).all()
        has_write = permission_service.has_resource_permission_on_any_collection_path(
            session,
            current_user,
            [mc.collection_id for mc in collections],
            "collection",
            "write",
            project_id=project_id,
        )
        if not has_write:
            raise HTTPException(status_code=403, detail="collection:write permission required")

    def preview_acoustic_index(
        self,
        session: Session,
        request: AcousticIndexPreviewRequest,
        current_user: User,
    ) -> AcousticIndexPreviewResponse:
        """Compute one acoustic index result without writing index_log rows."""
        media = self.get_media_for_user(session, request.project_id, request.media_id, current_user)
        self._ensure_acoustic_write_access(session, request.project_id, request.media_id, media, current_user)

        index_type = index_type_repository.get_by_id(session, request.index_id)
        if index_type is None or not index_type.name:
            raise HTTPException(status_code=404, detail="Acoustic index not found")

        media_context = self._get_media_context(session, media)
        audio_path = Path(self._resolve_audio_path(session, media, request.media_id))
        requested_channel = self._resolve_acoustic_index_channel(
            media_context["channel_num"],
            request.channel,
        )
        min_time = request.selection.min_time
        max_time = request.selection.max_time
        min_frequency = max(self.DEFAULT_MIN_FREQ, request.selection.min_frequency)
        max_frequency = request.selection.max_frequency
        selected_audio_path = prepare_acoustic_selection(
            audio_path,
            media_id=request.media_id,
            min_time=min_time,
            max_time=max_time,
            min_frequency=min_frequency,
            max_frequency=max_frequency,
            filter_enabled=request.selection.filter_enabled,
        )
        execution_params = self.build_index_params(index_type.param, request.params)
        results = self.acoustic_index.run_index(
            selected_audio_path,
            index_name=index_type.name,
            params=execution_params,
            channel=requested_channel,
            min_time=min_time,
            max_time=max_time,
            min_frequency=min_frequency,
            max_frequency=max_frequency,
        )
        if not results:
            results = {"Invalid Parameter": ""}

        version = self.acoustic_index.get_version()
        log_params = {
            "Channel": self._channel_label(requested_channel),
            **request.params,
        }
        save_payload = IndexLogCreateRequest(
            project_id=request.project_id,
            media_id=request.media_id,
            index_id=request.index_id,
            version=version,
            min_time=self._stringify_bound(min_time),
            max_time=self._stringify_bound(max_time),
            min_frequency=self._stringify_bound(min_frequency),
            max_frequency=self._stringify_bound(max_frequency),
            params=log_params,
            results=results,
        )
        return AcousticIndexPreviewResponse(
            media_id=request.media_id,
            index_id=request.index_id,
            index_name=index_type.name,
            version=version,
            params=log_params,
            results=results,
            save_payload=save_payload,
        )

    def save_acoustic_index_preview(
        self,
        session: Session,
        request: IndexLogCreateRequest,
        current_user: User,
        *,
        commit: bool = True,
    ) -> IndexLogCreateResponse:
        """Persist one confirmed acoustic index result group."""
        self.validate_acoustic_index_preview(session, request, current_user)

        log_id = index_log_repository.reserve_log_id(session)
        repository_kwargs = {
            "media_id": request.media_id,
            "user_id": current_user.user_id,
            "index_id": request.index_id,
            "version": request.version,
            "results": request.results,
            "params": request.params,
            "output_first": False,
            "min_time": request.min_time,
            "max_time": request.max_time,
            "min_frequency": request.min_frequency,
            "max_frequency": request.max_frequency,
            "log_id": log_id,
        }
        if not commit:
            repository_kwargs["commit"] = False

        stored_count = index_log_repository.create_from_results(session, **repository_kwargs)
        return IndexLogCreateResponse(log_id=log_id, stored_count=stored_count)

    def validate_acoustic_index_preview(
        self,
        session: Session,
        request: IndexLogCreateRequest,
        current_user: User,
    ) -> None:
        """Validate an acoustic index result without reserving an ID or writing rows."""
        media = self.get_media_for_user(session, request.project_id, request.media_id, current_user)
        self._ensure_acoustic_write_access(session, request.project_id, request.media_id, media, current_user)

        index_type = index_type_repository.get_by_id(session, request.index_id)
        if index_type is None or not index_type.name:
            raise HTTPException(status_code=404, detail="Acoustic index not found")

    def analyze_and_store_acoustic_index(
        self,
        session: Session,
        audio_path: Path,
        media_id: int,
        user_id: int,
        index_type_name: str,
        index_id: int,
        params: dict[str, Any] | None = None,
        stored_params: dict[str, Any] | None = None,
        channel: str = "left",
        min_time: str | int | float = 0,
        max_time: str | int | float | None = None,
        min_frequency: str | int | float = DEFAULT_MIN_FREQ,
        max_frequency: str | int | float | None = None,
        log_id: int | None = None,
        filter_enabled: bool = False,
        cancellation_token: CancellationToken | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """
        Compute one acoustic index and store its input/output rows to index_log.
        """
        if index_id is None:
            raise ValueError("index_id is required for acoustic index calculation")
        logger.info(f"Starting {index_type_name} analysis for media {media_id}")

        media = session.get(Media, media_id)
        media_context = (
            self._get_media_context(session, media)
            if isinstance(media, Media)
            else {"duration_s": None, "nyquist_hz": None, "channel_num": None}
        )
        normalized_params = dict(params or {})
        requested_channel = normalized_params.pop("Channel", normalized_params.pop("channel", channel))
        effective_channel = self._resolve_acoustic_index_channel(
            media_context.get("channel_num"),
            requested_channel,
        )
        effective_max_time = max_time if max_time is not None else media_context["duration_s"]
        effective_max_frequency = max_frequency if max_frequency is not None else media_context["nyquist_hz"]
        selected_audio_path = prepare_acoustic_selection(
            audio_path,
            media_id=media_id,
            min_time=float(min_time),
            max_time=None if effective_max_time is None else float(effective_max_time),
            min_frequency=float(min_frequency),
            max_frequency=None if effective_max_frequency is None else float(effective_max_frequency),
            filter_enabled=filter_enabled,
        )
        results = self.acoustic_index.run_index(
            selected_audio_path,
            index_name=index_type_name,
            params=normalized_params,
            channel=effective_channel,
            min_time=min_time,
            max_time=effective_max_time,
            min_frequency=min_frequency,
            max_frequency=effective_max_frequency,
            cancellation_token=cancellation_token,
        )
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        if not results:
            results = {"Invalid Parameter": ""}

        version = self.acoustic_index.get_version()
        stored_log_params = normalized_params if stored_params is None else stored_params
        log_params = {
            "Channel": self._channel_label(effective_channel),
            **stored_log_params,
        }

        stored_count = index_log_repository.create_from_results(
            session,
            media_id=media_id,
            user_id=user_id,
            index_id=index_id,
            version=version,
            results=results,
            params=log_params,
            output_first=False,
            min_time=self._stringify_bound(min_time),
            max_time=self._stringify_bound(effective_max_time),
            min_frequency=self._stringify_bound(min_frequency),
            max_frequency=self._stringify_bound(effective_max_frequency),
            log_id=log_id,
            commit=commit,
        )

        logger.info(f"Stored {stored_count} {index_type_name} entries for media {media_id}")
        return {"stored_count": stored_count, **results}

    def analyze_acoustic_selection(
        self,
        session: Session,
        audio_path: Path,
        media_id: int,
        user_id: int,
        analysis_type: str,
        params: dict[str, Any],
        channel: str,
        min_time: float,
        max_time: float,
        min_frequency: float,
        max_frequency: float,
        filter_enabled: bool = False,
        cancellation_token: CancellationToken | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Run one transient acoustic analysis without writing index logs."""
        searchable_path = prepare_acoustic_selection(
            audio_path,
            media_id=media_id,
            min_time=0,
            max_time=None,
            min_frequency=min_frequency,
            max_frequency=max_frequency,
            filter_enabled=filter_enabled,
        )
        index_name = "template_matching" if analysis_type == "template_matching" else "max_frequency"
        results = self.acoustic_index.run_index(
            searchable_path,
            index_name=index_name,
            params=params if analysis_type == "template_matching" else {},
            channel=channel,
            min_time=min_time,
            max_time=max_time,
            min_frequency=min_frequency,
            max_frequency=max_frequency,
            cancellation_token=cancellation_token,
        )
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        if analysis_type != "template_matching":
            value = next(iter(results.values()), "")
            return {"stored_count": 1, "Frequency of maximum energy": value}

        raw_matches = results.get("MATCHES", "[]")
        matches = json.loads(str(raw_matches))
        annotations: list[Annotation] = []
        for match in matches:
            start = float(match.get("min_t", match.get("peak_time", 0)))
            end = float(match.get("max_t", start))
            min_match_frequency = float(match.get("min_f", min_frequency))
            max_match_frequency = float(match.get("max_f", max_frequency))
            xcorrcoef = float(match.get("xcorrcoef", 0))
            annotations.append(
                Annotation(
                    media_id=media_id,
                    creator_id=user_id,
                    creator_type="template_matching",
                    sound_id=22,
                    confidence=xcorrcoef,
                    min_x=start,
                    max_x=end,
                    min_y=min_match_frequency,
                    max_y=max_match_frequency,
                    individual_num=1,
                    reference=False,
                    comments=(
                        f"matched template min_freq={min_match_frequency:g}, "
                        f"max_freq={max_match_frequency:g}, min_time={start:g}, "
                        f"max_time={end:g} from media_id={media_id} "
                        f"with xcorrcoeff = {xcorrcoef:g}"
                    ),
                )
            )
        count = len(annotations)
        if annotations:
            annotation_repository.create_batch(session, annotations, commit=commit)
        return {
            "stored_count": count,
            "detection_count": count,
            "completion_message": (
                f"Scikit-maad template_matching found and inserted {count} detections as tags."
                if count
                else "No valid data matched."
            ),
        }

    def analyze_and_store_birdnet(
        self,
        session: Session,
        audio_path: Path,
        media_id: int,
        creator_id: int,
        min_confidence: float = 0.1,
        overlap: float = 0.0,
        sensitivity: float = 1.0,
        sf_thresh: float = 0.03,
        min_frequency: int = 1,
        max_frequency: int = 15000,
        lat: float | None = None,
        lon: float | None = None,
        week: int | None = None,
        locale: str = "en_us",
        top_n: int | None = None,
        cancellation_token: CancellationToken | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """
        Analyze audio with BirdNET and store results.
        """
        creator_type = f"BirdNET-Analyzer {self.birdnet.version}"

        logger.info(f"Starting BirdNET analysis for media {media_id}")
        detections = self.birdnet.analyze(
            audio_path,
            min_confidence=min_confidence,
            overlap=overlap,
            sensitivity=sensitivity,
            sf_thresh=sf_thresh,
            lat=lat,
            lon=lon,
            week=week,
            locale=locale,
            top_n=top_n,
            cancellation_token=cancellation_token,
        )
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()

        if not detections:
            logger.info(f"No detections found for media {media_id}")
            return {
                "media_id": media_id,
                "detection_count": 0,
                "annotation_count": 0,
                "annotation_ids": [],
                "unmatched_species": [],
                "unmatched_species_count": 0,
                "analysis_message_model": f"BirdNET v{self.birdnet.version}",
            }

        annotations: list[Annotation] = []
        unmatched_species: list[str] = []
        unknown_taxon = self._get_unknown_taxon(session)
        unknown_taxon_id = unknown_taxon.taxon_id if unknown_taxon else None

        for detection in detections:
            annotation, unmatched = self._annotation_from_detection(
                session,
                media_id=media_id,
                creator_id=creator_id,
                creator_type=creator_type,
                species_name=str(detection.get("species", "")),
                start_time=detection.get("start_time", 0),
                end_time=detection.get("end_time", 0),
                min_freq=min_frequency,
                max_freq=max_frequency,
                confidence=detection.get("confidence", 0),
                unknown_taxon=unknown_taxon,
                unknown_taxon_id=unknown_taxon_id,
            )
            if unmatched is not None:
                unmatched_species.append(unmatched)
            annotations.append(annotation)

        created = annotation_repository.create_batch(session, annotations, commit=commit)

        logger.info(
            f"BirdNET analysis complete for media {media_id}: "
            f"{len(detections)} detections, {len(created)} annotations created"
        )

        return {
            "media_id": media_id,
            "detection_count": len(detections),
            "annotation_count": len(created),
            "annotation_ids": [ann.annotation_id for ann in created if ann.annotation_id is not None],
            "unmatched_species": list(dict.fromkeys(unmatched_species)),
            "unmatched_species_count": len(unmatched_species),
            "analysis_message_model": f"BirdNET v{self.birdnet.version}",
        }

    def analyze_and_store_batdetect(
        self,
        session: Session,
        audio_path: Path,
        media_id: int,
        creator_id: int,
        detection_threshold: float = 0.3,
        chunk_size: float = 2.0,
        cancellation_token: CancellationToken | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """
        Analyze audio with batdetect2 and store results.
        """
        creator_type = f"batdetect2 {self.batdetect.version}"

        logger.info(f"Starting batdetect2 analysis for media {media_id}")
        detections = self.batdetect.analyze(
            audio_path,
            detection_threshold=detection_threshold,
            chunk_size=chunk_size,
            cancellation_token=cancellation_token,
        )
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()

        if not detections:
            logger.info(f"No bat detections found for media {media_id}")
            return {
                "media_id": media_id,
                "detection_count": 0,
                "annotation_count": 0,
                "annotation_ids": [],
                "unmatched_species": [],
                "unmatched_species_count": 0,
                "analysis_message_model": f"Batdetect2 {self.batdetect.version}",
            }

        annotations: list[Annotation] = []
        unmatched_species: list[str] = []
        unknown_taxon = self._get_unknown_taxon(session)
        unknown_taxon_id = unknown_taxon.taxon_id if unknown_taxon else None

        for detection in detections:
            annotation, unmatched = self._annotation_from_detection(
                session,
                media_id=media_id,
                creator_id=creator_id,
                creator_type=creator_type,
                species_name=str(detection.get("species", "")),
                start_time=detection.get("start_time", 0),
                end_time=detection.get("end_time", 0),
                min_freq=detection.get("min_freq"),
                max_freq=detection.get("max_freq"),
                confidence=detection.get("confidence", 0),
                unknown_taxon=unknown_taxon,
                unknown_taxon_id=unknown_taxon_id,
            )
            if unmatched is not None:
                unmatched_species.append(unmatched)
            annotations.append(annotation)

        created = annotation_repository.create_batch(session, annotations, commit=commit)

        logger.info(
            f"batdetect2 analysis complete for media {media_id}: "
            f"{len(detections)} detections, {len(created)} annotations created"
        )

        return {
            "media_id": media_id,
            "detection_count": len(detections),
            "annotation_count": len(created),
            "annotation_ids": [ann.annotation_id for ann in created if ann.annotation_id is not None],
            "unmatched_species": list(dict.fromkeys(unmatched_species)),
            "unmatched_species_count": len(unmatched_species),
            "analysis_message_model": f"Batdetect2 {self.batdetect.version}",
        }

    def analyze_and_store_insects(
        self,
        session: Session,
        audio_path: Path,
        media_id: int,
        creator_id: int,
        window_size: float = 4.0,
        stride_length: float = 4.0,
        max_freq: int = 48000,
        recording_duration: float | None = None,
        cancellation_token: CancellationToken | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """
        Analyze audio with insects-base-cnn10-96k-t and store results as annotations.
        """
        creator_type = "insects-base-cnn10-96k-t"
        if recording_duration is None:
            media = session.get(Media, media_id)
            if isinstance(media, Media):
                recording_duration = self._get_media_context(session, media)["duration_s"]

        logger.info(f"Starting insects-base-cnn10-96k-t analysis for media {media_id}")
        detections = self.insects.analyze(
            audio_path,
            window_size=window_size,
            stride_length=stride_length,
            cancellation_token=cancellation_token,
        )
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()

        if not detections:
            logger.info(f"No insect detections found for media {media_id}")
            return {
                "media_id": media_id,
                "detection_count": 0,
                "annotation_count": 0,
                "annotation_ids": [],
                "unmatched_species": [],
                "unmatched_species_count": 0,
                "analysis_message_model": creator_type,
            }

        annotations: list[Annotation] = []
        unmatched_species: list[str] = []
        skipped_count = 0
        unknown_taxon = self._get_unknown_taxon(session)
        unknown_taxon_id = unknown_taxon.taxon_id if unknown_taxon else None

        for detection in detections:
            species_name = detection.get("species", "")
            confidence = detection.get("confidence", 0)
            start_time = detection.get("start_time", 0)
            end_time = detection.get("end_time", 0)

            if (
                start_time < 0
                or end_time < 0
                or end_time <= start_time
                or (
                    recording_duration is not None
                    and end_time > recording_duration
                )
            ):
                logger.warning(
                    "Skipping insects detection with invalid time bounds for media %s: start=%s end=%s duration=%s",
                    media_id,
                    start_time,
                    end_time,
                    recording_duration,
                )
                skipped_count += 1
                continue

            annotation, unmatched = self._annotation_from_detection(
                session,
                media_id=media_id,
                creator_id=creator_id,
                creator_type=creator_type,
                species_name=str(species_name),
                start_time=start_time,
                end_time=end_time,
                min_freq=1,
                max_freq=max_freq,
                confidence=confidence,
                unknown_taxon=unknown_taxon,
                unknown_taxon_id=unknown_taxon_id,
            )
            if unmatched is not None:
                unmatched_species.append(unmatched)
            annotations.append(annotation)

        created = annotation_repository.create_batch(session, annotations, commit=commit)

        logger.info(
            f"insects-base-cnn10-96k-t analysis complete for media {media_id}: "
            f"{len(detections)} detections, {len(created)} annotations created"
        )

        warning = (
            f"{skipped_count} detections were skipped because their time bounds were outside the audio duration."
            if skipped_count
            else None
        )

        return {
            "media_id": media_id,
            "detection_count": len(detections),
            "annotation_count": len(created),
            "annotation_ids": [ann.annotation_id for ann in created if ann.annotation_id is not None],
            "unmatched_species": list(dict.fromkeys(unmatched_species)),
            "unmatched_species_count": len(unmatched_species),
            "analysis_message_model": creator_type,
            "warning": warning,
        }

    def _get_unknown_taxon(self, session: Session) -> Taxon | None:
        """Return the Unknown taxon when available."""
        for scientific_name in ("Unknown", "unknown"):
            taxon = self._find_local_taxon(session, scientific_name)
            if taxon is not None:
                return taxon
        return None

    def _annotation_from_detection(
        self,
        session: Session,
        *,
        media_id: int,
        creator_id: int,
        creator_type: str,
        species_name: str,
        start_time: Any,
        end_time: Any,
        min_freq: Any,
        max_freq: Any,
        confidence: Any,
        unknown_taxon: Taxon | None,
        unknown_taxon_id: int | None,
    ) -> tuple[Annotation, str | None]:
        """Map one detection row to an annotation record."""
        taxon = self._find_local_taxon(session, species_name)
        unmatched_species: str | None = None
        if taxon is None:
            taxon = unknown_taxon
            unmatched_species = species_name

        final_taxon_id = taxon.taxon_id if taxon else None
        comment = ""
        if (
            unmatched_species is not None
            and unknown_taxon_id is not None
            and final_taxon_id == unknown_taxon_id
        ):
            comment = self._truncate_annotation_comments(unmatched_species) or ""

        return (
            Annotation(
                media_id=media_id,
                creator_id=creator_id,
                creator_type=creator_type,
                sound_id=self.BIOPHONY_SOUND_ID,
                taxon_id=final_taxon_id,
                min_x=start_time,
                max_x=end_time,
                min_y=min_freq,
                max_y=max_freq,
                confidence=confidence,
                individual_num=1,
                distance_not_estimable=True,
                reference=False,
                comments=comment,
            ),
            unmatched_species,
        )

    def _find_local_taxon(self, session: Session, scientific_name: str | None) -> Taxon | None:
        """Match only already-imported taxa."""
        normalized_name = " ".join((scientific_name or "").split()).strip()
        if not normalized_name:
            return None
        return session.exec(
            select(Taxon).where(func.lower(Taxon.cached_scientific_name) == normalized_name.lower())
        ).first()

    def _get_audio_setting(self, session: Session, media: Media) -> AudioSetting | None:
        """Resolve audio settings for a media record."""
        audio_setting = getattr(media, "audio_setting", None)
        if isinstance(audio_setting, AudioSetting):
            return audio_setting
        if media.audio_setting_id is None:
            return None
        resolved = session.get(AudioSetting, media.audio_setting_id)
        return resolved if isinstance(resolved, AudioSetting) else None

    def _get_media_context(self, session: Session, media: Media) -> dict[str, Any]:
        """Collect media context for analysis jobs."""
        audio_setting = self._get_audio_setting(session, media)
        resolved_lon: float | None = None
        resolved_lat: float | None = None
        if media.site_id is not None:
            resolved_lon, resolved_lat = site_repository.resolve_analysis_coordinates(
                session,
                media.site_id,
            )
        sampling_rate = (
            audio_setting.sampling_rate_hz
            if audio_setting and audio_setting.sampling_rate_hz
            else None
        )
        duration = (
            audio_setting.duration_s
            if audio_setting and audio_setting.duration_s is not None
            else None
        )
        return {
            "sampling_rate_hz": sampling_rate,
            "duration_s": duration,
            "nyquist_hz": int(sampling_rate / 2) if sampling_rate else None,
            "date_time": media.date_time,
            "site_id": media.site_id,
            "resolved_lon": resolved_lon,
            "resolved_lat": resolved_lat,
            "channel_num": (
                audio_setting.channel_num
                if audio_setting and audio_setting.channel_num is not None
                else None
            ),
        }

    def _resolve_week_from_datetime(self, value: datetime | None) -> int | None:
        """Resolve analysis week from the recording timestamp."""
        if value is None:
            return None
        if value.year == 1970 and value.month == 1 and value.day == 1:
            return None
        return value.isocalendar().week

    def _resolve_birdnet_frequency_bounds(
        self,
        *,
        min_frequency: int,
        max_frequency: int | None,
        nyquist_hz: int | None,
    ) -> tuple[int, int]:
        """Validate BirdNET annotation bounds against the media frequency ceiling."""
        effective_max = max_frequency if max_frequency is not None else nyquist_hz
        if effective_max is None:
            effective_max = self.DEFAULT_MAX_FREQ
        if min_frequency >= effective_max:
            raise ValueError("min_frequency must be less than max_frequency")
        if nyquist_hz is not None:
            if min_frequency > nyquist_hz or effective_max > nyquist_hz:
                raise ValueError("Frequency range exceeds audio maximum frequency")
        return min_frequency, effective_max

    def _channel_name(self, channel_num: int | None) -> str:
        """Resolve the default bulk-analysis channel from the audio channel count."""
        if channel_num == 1:
            return "mono"
        if channel_num == 2:
            return "right"
        return "left"

    def _normalize_channel(self, value: Any) -> str:
        """Normalize API-provided channel values to scikit-maad channel names."""
        normalized = str(value).strip().lower()
        if normalized in {"mono", "left", "right"}:
            return normalized
        if normalized == "1":
            return "mono"
        if normalized == "2":
            return "right"
        return "left"

    def _resolve_acoustic_index_channel(self, channel_num: int | None, requested: Any = None) -> str:
        """Resolve the acoustic index channel from the request and audio channel count."""
        if channel_num == 1:
            return "mono"
        if requested is not None:
            return self._normalize_channel(requested)
        return self._channel_name(channel_num)

    def _channel_label(self, channel: str) -> str:
        """Render the channel label stored in index_log."""
        if channel == "mono":
            return "Mono"
        if channel == "right":
            return "Right"
        return "Left"

    def _parse_index_type_defaults(self, raw_param: Any) -> dict[str, Any]:
        """Parse structured index_type.param defaults."""
        if raw_param is None:
            return {}
        if not isinstance(raw_param, list):
            raise ValueError("index_type.param must be a structured parameter array")

        defaults: dict[str, Any] = {}
        for item in raw_param:
            if not isinstance(item, dict) or not item.get("key"):
                raise ValueError("index_type.param contains an invalid parameter entry")
            if item.get("default") is not None:
                defaults[str(item["key"])] = item.get("default")
        return defaults

    def build_index_params(self, raw_param: Any, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        """Merge DB defaults with request overrides for acoustic index execution."""
        params: dict[str, Any] = self._parse_index_type_defaults(raw_param)
        for key, value in (overrides or {}).items():
            params[key] = value
        return params

    def _stringify_bound(self, value: Any) -> str | None:
        """Stringify boundary values for index_log rows."""
        if value is None:
            return None
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    def _merge_model_name(self, creator_type: str) -> str:
        """Convert creator type strings to merge model names."""
        for prefix, model_name in self.MERGE_MODEL_NAMES.items():
            if creator_type.startswith(prefix):
                return model_name
        return creator_type

    def _truncate_annotation_comments(self, comments: str | None) -> str | None:
        """Keep generated comments within the current annotation column limit."""
        if not comments:
            return comments
        return comments[: self.ANNOTATION_COMMENTS_MAX_LENGTH]

    def get_media_for_user(
        self,
        session: Session,
        project_id: int,
        media_id: int,
        current_user: User,
    ) -> Media:
        """
        Get a media record and verify the user has access to it.

        Raises 404 if not found, 403 if no permission.
        """
        media = session.get(Media, media_id)
        if not media:
            raise HTTPException(status_code=404, detail="Media not found")
        if media.media_type != "audio":
            raise HTTPException(status_code=422, detail="Acoustic analysis is only available for audio media")

        if permission_service.is_admin(current_user):
            return media

        if media.uploader_id == current_user.user_id:
            return media

        statement = (
            select(MediaCollection)
            .join(ProjectCollection, ProjectCollection.collection_id == MediaCollection.collection_id)
            .where(MediaCollection.media_id == media_id, ProjectCollection.project_id == project_id)
        )
        collections = session.exec(statement).all()

        if not collections:
            raise HTTPException(status_code=403, detail="Access denied")

        if permission_service.has_resource_permission_on_any_collection_path(
            session,
            current_user,
            [mc.collection_id for mc in collections],
            "audio",
            "read",
            project_id=project_id,
        ):
            return media

        raise HTTPException(status_code=403, detail="Access denied")

    def _resolve_audio_path(
        self,
        session: Session,
        media: Media,
        media_id: int,
    ) -> str:
        """Resolve the on-disk audio path for a media record."""
        collection_id = session.exec(
            select(MediaCollection.collection_id)
            .where(MediaCollection.media_id == media_id)
            .order_by(MediaCollection.added_date.asc())
        ).first()
        path_root = collection_id if collection_id else media.audio_setting_id
        filename = media.filename or ""
        resolved = resolve_existing_analysis_audio_media_path(
            path_root,
            media.directory,
            filename,
        )
        if resolved is not None:
            return str(resolved)
        expected = logical_audio_media_path(path_root, media.directory, filename)
        raise FileNotFoundError(
            "No supported analysis audio file found for media "
            f"{media_id}; expected WAV or FLAC near {expected}"
        )

    async def _enqueue_job(
        self,
        session: Session,
        publisher: TaskPublisher,
        task_type: str,
        queue_type: str,
        user_id: int,
        message: str,
        **job_kwargs: Any,
    ) -> QueueDetail:
        """Create a Queue record, enqueue the RabbitMQ job, and return a status response."""
        queue = Queue(type=queue_type, user_id=user_id, status=QueueStatus.PENDING)
        session.add(queue)
        session.commit()
        session.refresh(queue)

        try:
            await publisher.enqueue_task(task_type, queue_id=queue.queue_id, **job_kwargs)
        except Exception:
            queue.status = QueueStatus.ERROR
            queue.error = "Failed to enqueue job"
            session.commit()
            raise

        logger.info(f"Enqueued {queue_type} task for queue {queue.queue_id}")
        return QueueDetail(
            queue_id=queue.queue_id,
            status="pending",
            message=message,
            progress=0,
            completed=0,
            total=0,
            type=queue_type,
        )

    async def enqueue_analysis(
        self,
        session: Session,
        publisher: TaskPublisher,
        request: RunAnalysisRequest,
        current_user: User,
    ) -> RunAnalysisResponse:
        """
        Enqueue AI analysis jobs (BirdNET, BatDetect2, insects) for a media file.

        Validates media access, resolves audio path, creates Queue records and enqueues RabbitMQ jobs.
        """
        queued: list[QueueDetail] = []
        failed: list[dict] = []
        prepared_media: list[tuple[int, dict[str, Any], str]] = []

        for media_id in request.media_ids:
            try:
                media = self.get_media_for_user(session, request.project_id, media_id, current_user)
                media_context = self._get_media_context(session, media)
                audio_path = self._resolve_audio_path(session, media, media_id)
                prepared_media.append((media_id, media_context, audio_path))
            except Exception as e:
                failed.append({"media_id": media_id, "reason": str(e)})

        if request.birdnet is not None:
            for _, media_context, _ in prepared_media:
                self._resolve_birdnet_frequency_bounds(
                    min_frequency=request.birdnet.min_freq,
                    max_frequency=request.birdnet.max_freq,
                    nyquist_hz=media_context["nyquist_hz"],
                )

        for media_id, media_context, audio_path in prepared_media:
            if request.birdnet is not None:
                try:
                    validated_week = self._resolve_week_from_datetime(media_context["date_time"])
                    resolved_lat = media_context["resolved_lat"]
                    resolved_lon = media_context["resolved_lon"]
                    if resolved_lat is None or resolved_lon is None:
                        resolved_lat = None
                        resolved_lon = None
                    min_frequency, max_frequency = self._resolve_birdnet_frequency_bounds(
                        min_frequency=request.birdnet.min_freq,
                        max_frequency=request.birdnet.max_freq,
                        nyquist_hz=media_context["nyquist_hz"],
                    )
                    resp = await self._enqueue_job(
                        session, publisher, WorkerTaskType.ANALYZE_BIRDNET, "birdnet",
                        current_user.user_id, "BirdNET task submitted",
                        audio_path=audio_path,
                        media_id=media_id,
                        min_confidence=request.birdnet.min_conf,
                        overlap=request.birdnet.overlap,
                        sensitivity=request.birdnet.sensitivity,
                        sf_thresh=request.birdnet.sf_thresh,
                        min_frequency=min_frequency,
                        max_frequency=max_frequency,
                        lat=resolved_lat,
                        lon=resolved_lon,
                        week=validated_week,
                        locale=request.birdnet.locale,
                        top_n=request.birdnet.top_n,
                        merge_enabled=request.merge.is_merged,
                        merge_max_gap=request.merge.max_gap,
                        merge_keep_only=request.merge.keep_merged,
                    )
                    queued.append(resp)
                except Exception as e:
                    logger.exception("Failed to enqueue BirdNET task")
                    failed.append({"media_id": media_id, "model": "birdnet", "reason": str(e)})

            if request.batdetect is not None:
                try:
                    resp = await self._enqueue_job(
                        session, publisher, WorkerTaskType.ANALYZE_BATDETECT, "batdetect2",
                        current_user.user_id, "BatDetect2 task submitted",
                        audio_path=audio_path,
                        media_id=media_id,
                        detection_threshold=request.batdetect.detection_threshold,
                        chunk_size=request.batdetect.chunk_size,
                        merge_enabled=request.merge.is_merged,
                        merge_max_gap=request.merge.max_gap,
                        merge_keep_only=request.merge.keep_merged,
                    )
                    queued.append(resp)
                except Exception as e:
                    logger.exception("Failed to enqueue BatDetect2 task")
                    failed.append({"media_id": media_id, "model": "batdetect", "reason": str(e)})

            if request.insects is not None:
                try:
                    stride_length = request.insects.stride_length
                    max_freq = request.insects.max_freq
                    if max_freq is None:
                        max_freq = media_context["nyquist_hz"] or 48000
                    resp = await self._enqueue_job(
                        session, publisher, WorkerTaskType.ANALYZE_INSECTS, "insects",
                        current_user.user_id, "insects-base-cnn10-96k-t task submitted",
                        audio_path=audio_path,
                        media_id=media_id,
                        window_size=request.insects.window_size,
                        stride_length=stride_length,
                        max_freq=max_freq,
                        merge_enabled=request.merge.is_merged,
                        merge_max_gap=request.merge.max_gap,
                        merge_keep_only=request.merge.keep_merged,
                    )
                    queued.append(resp)
                except Exception as e:
                    logger.exception("Failed to enqueue insects task")
                    failed.append({"media_id": media_id, "model": "insects", "reason": str(e)})

        return RunAnalysisResponse(queued=queued, failed=failed)

    async def enqueue_acoustic_indices(
        self,
        session: Session,
        publisher: TaskPublisher,
        request: RunAcousticIndicesRequest,
        current_user: User,
    ) -> AcousticIndicesResponse:
        """
        Enqueue acoustic indices jobs (ACI, NDSI) for a media file.

        Requires collection:write permission. Creates Queue records and enqueues RabbitMQ jobs.
        """
        queued: list[QueueDetail] = []
        failed: list[dict] = []
        batch_log_id: int | None = None

        for media_id in request.media_ids:
            try:
                media = self.get_media_for_user(session, request.project_id, media_id, current_user)
                self._ensure_acoustic_write_access(session, request.project_id, media_id, media, current_user)
                media_context = self._get_media_context(session, media)
                audio_path = self._resolve_audio_path(session, media, media_id)
                requested_channel = self._resolve_acoustic_index_channel(
                    media_context["channel_num"],
                    request.channel,
                )
                min_time = request.selection.min_time if request.selection else 0
                max_time = request.selection.max_time if request.selection else media_context["duration_s"]
                min_frequency = max(
                    self.DEFAULT_MIN_FREQ,
                    request.selection.min_frequency if request.selection else self.DEFAULT_MIN_FREQ,
                )
                max_frequency = request.selection.max_frequency if request.selection else media_context["nyquist_hz"]
                filter_enabled = request.selection.filter_enabled if request.selection else False
            except Exception as e:
                failed.append({"media_id": media_id, "reason": str(e)})
                continue

            for index_job in request.indices:
                is_analysis_job = index_job.analysis_type is not None
                index_type = None if is_analysis_job else index_type_repository.get_by_id(session, index_job.index_id)
                if not is_analysis_job and (index_type is None or not index_type.name):
                    failed.append(
                        {
                            "media_id": media_id,
                            "index_id": index_job.index_id,
                            "reason": "Unknown acoustic index",
                        }
                    )
                    continue

                task_name = index_job.analysis_type if is_analysis_job else index_type.name
                params = index_job.params if is_analysis_job else self.build_index_params(index_type.param, index_job.params)
                try:
                    if (
                        task_name == "template_matching"
                        and self._is_full_time_window(float(min_time), float(max_time), media_context["duration_s"])
                    ):
                        raise ValueError("Please zoom in before executing.")
                    if not is_analysis_job and batch_log_id is None:
                        batch_log_id = index_log_repository.reserve_log_id(session)
                    resp = await self._enqueue_job(
                        session, publisher, WorkerTaskType.ANALYZE_ACOUSTIC_INDEX, task_name,
                        current_user.user_id, f"{task_name} task submitted",
                        audio_path=audio_path,
                        media_id=media_id,
                        index_id=None if is_analysis_job else index_type.index_id,
                        index_name=task_name,
                        params=params,
                        stored_params={} if is_analysis_job else index_job.params,
                        channel=requested_channel,
                        min_time=min_time,
                        max_time=max_time,
                        min_frequency=min_frequency,
                        max_frequency=max_frequency,
                        filter_enabled=filter_enabled,
                        log_id=None if is_analysis_job else batch_log_id,
                    )
                    queued.append(resp)
                except Exception as e:
                    logger.exception("Failed to enqueue acoustic calculation task")
                    failed_item = {
                        "media_id": media_id,
                        "reason": str(e),
                    }
                    if is_analysis_job:
                        failed_item["analysis_type"] = task_name
                    else:
                        failed_item["index_id"] = index_type.index_id
                        failed_item["index_name"] = index_type.name
                    failed.append(failed_item)

        return AcousticIndicesResponse(queued=queued, failed=failed)

    def merge_annotations(
        self,
        session: Session,
        media_id: int,
        creator_type: str,
        max_gap: float = 0.0,
        keep_merged_only: bool = False,
        annotation_ids: list[int] | None = None,
        commit: bool = True,
    ) -> int:
        """
        Merge conspecific annotations that are close in time.
        """
        if not annotation_ids:
            return 0

        annotations = list(
            session.exec(
                select(Annotation)
                .where(
                    Annotation.media_id == media_id,
                    Annotation.creator_type == creator_type,
                    Annotation.annotation_id.in_(annotation_ids),
                )
                .order_by(Annotation.min_x)
            ).all()
        )

        if not annotations:
            return 0

        unknown_taxon = self._get_unknown_taxon(session)
        unknown_taxon_id = unknown_taxon.taxon_id if unknown_taxon else None

        sorted_annotations = sorted(
            annotations,
            key=lambda ann: (
                ann.taxon_id if ann.taxon_id is not None else -1,
                str(ann.comments),
                float(ann.min_x),
            ),
        )

        merged_results: list[tuple[Annotation, bool, list[int]]] = []
        buffer: list[Annotation] = []

        def shared_optional_value(attr: str) -> Any:
            """Preserve a merged field only when every source annotation agrees."""
            values = [getattr(annotation, attr) for annotation in buffer]
            if not values:
                return None
            first_value = values[0]
            return first_value if all(value == first_value for value in values) else None

        def flush_buffer() -> None:
            if not buffer:
                return
            if len(buffer) == 1:
                isolated = buffer[0]
                merged_results.append((
                    Annotation(
                        media_id=isolated.media_id,
                        creator_id=isolated.creator_id,
                        creator_type=isolated.creator_type,
                        sound_id=isolated.sound_id,
                        taxon_id=isolated.taxon_id,
                        min_x=float(isolated.min_x),
                        max_x=float(isolated.max_x),
                        min_y=float(isolated.min_y) if isolated.min_y is not None else None,
                        max_y=float(isolated.max_y) if isolated.max_y is not None else None,
                        confidence=round(float(isolated.confidence), 4)
                        if isolated.confidence is not None
                        else None,
                        uncertain=isolated.uncertain,
                        sound_distance_m=isolated.sound_distance_m,
                        individual_num=isolated.individual_num,
                        animal_sound_type=isolated.animal_sound_type,
                        distance_not_estimable=isolated.distance_not_estimable,
                        reference=isolated.reference,
                        comments=self._truncate_annotation_comments(isolated.comments),
                    ),
                    False,
                    [isolated.annotation_id],
                ))
                return

            representative = buffer[0]
            confs = [float(a.confidence) for a in buffer if a.confidence is not None]
            merged_confidence = round(sum(confs) / len(confs), 4) if confs else None
            conf_scores = ", ".join(str(round(c, 4)) for c in confs)
            original_comment = representative.comments or ""
            merge_info = (
                f"merged {len(buffer)} {self._merge_model_name(creator_type)} tags with confidence scores: "
                f"{conf_scores}"
            )
            merged_comments = (
                f"{original_comment}, {merge_info}"
                if original_comment
                else merge_info
            )
            merged_results.append((
                Annotation(
                    media_id=representative.media_id,
                    creator_id=representative.creator_id,
                    creator_type=representative.creator_type,
                    sound_id=representative.sound_id,
                    taxon_id=representative.taxon_id,
                    min_x=min(float(a.min_x) for a in buffer),
                    max_x=max(float(a.max_x) for a in buffer),
                    min_y=min(float(a.min_y) for a in buffer if a.min_y is not None),
                    max_y=max(float(a.max_y) for a in buffer if a.max_y is not None),
                    confidence=merged_confidence,
                    uncertain=shared_optional_value("uncertain"),
                    sound_distance_m=shared_optional_value("sound_distance_m"),
                    individual_num=1,
                    animal_sound_type=shared_optional_value("animal_sound_type"),
                    distance_not_estimable=True,
                    reference=False,
                    comments=self._truncate_annotation_comments(merged_comments),
                ),
                True,
                [a.annotation_id for a in buffer],
            ))

        for ann in sorted_annotations:
            if not buffer:
                buffer = [ann]
                continue

            last = buffer[-1]
            same_known_species = (
                last.taxon_id == ann.taxon_id
                and last.taxon_id is not None
                and last.taxon_id != unknown_taxon_id
            )
            same_unknown_comment = (
                last.taxon_id == unknown_taxon_id
                and ann.taxon_id == unknown_taxon_id
                and last.comments == ann.comments
            )

            if (same_known_species or same_unknown_comment) and (
                float(ann.min_x) - float(last.max_x) <= max_gap
            ):
                buffer.append(ann)
                continue

            flush_buffer()
            buffer = [ann]

        flush_buffer()

        merged_annotations = [
            merged_ann
            for merged_ann, was_merged, _annotation_ids in merged_results
            if was_merged
        ]

        if keep_merged_only:
            result_annotations = [merged_ann for merged_ann, _was_merged, _ids in merged_results]
            to_delete_ids = [
                annotation_id
                for _merged_ann, _was_merged, annotation_ids in merged_results
                for annotation_id in annotation_ids
                if annotation_id is not None
            ]
        else:
            result_annotations = merged_annotations
            to_delete_ids = []

        if to_delete_ids:
            annotation_repository.delete_by_ids(session, to_delete_ids, commit=commit)
        if result_annotations:
            annotation_repository.create_batch(session, result_annotations, commit=commit)

        logger.info(
            "Merged annotations for media %s creator_type=%s: %s merged groups, %s originals removed",
            media_id,
            creator_type,
            len(merged_annotations),
            len(to_delete_ids),
        )
        return len(result_annotations) if keep_merged_only else len(merged_annotations)

analysis_service = AnalysisService()
