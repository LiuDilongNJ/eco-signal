"""媒体 API 路由。 / Media API routes."""
import logging
import mimetypes
from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.responses import Response as RawResponse

from app.api.deps import (
    ActiveManager,
    CanWriteProject,
    CurrentUser,
    CurrentUserOptional,
    SessionDep,
    TaskPublisherDep,
)
from app.api.query_params import MediaFilterQueryParams
from app.api.responses import build_download_content_disposition, csv_response
from app.core.config import settings
from app.models import User
from app.schemas.media import (
    MediaBatchOperationResponse,
    MediaBrowseGalleryItem,
    MediaBrowseListItem,
    MediaCollectionLinkOptionsResponse,
    MediaCollectionLinksSyncRequest,
    MediaCreate,
    MediaCreateResponse,
    MediaListPublic,
    MediaNavigation,
    MediaOption,
    MediaPublic,
    MediaTimelineResponse,
    MediaUpdate,
)
from app.schemas.response import (
    ApiErrorResponse,
    PagedApiResponse,
    ApiResponse,
    api_success,
)
from app.services import media_service, permission_service
from app.services.upload_validation_service import extension_for, validate_csv_content
from app.spectrogram import WINDOW_FUNCTIONS

router = APIRouter(prefix="/media", tags=["媒体 / media"])
router_views = APIRouter(tags=["媒体 / media"])

logger = logging.getLogger(__name__)
_SPECTROGRAM_FFT_SIZES = {128, 256, 512, 1024, 2048, 4096}
_MAX_SPECTROGRAM_PIXELS = 4_000_000


@router.get("", response_model=PagedApiResponse[list[MediaListPublic]], summary="列出媒体 / List Media")
def list_media(
    session: SessionDep,
    current_user: CurrentUserOptional,
    page: int = Query(default=1, ge=1, description="页码 / Page number"),
    page_size: int = Query(default=settings.DEFAULT_PAGE_LIMIT, ge=1, le=100, description="每页条目数 / Items per page"),
    project_id: int = Query(..., description="通过项目 ID 筛选（必传） / Filter by project ID (required)"),
    collection_id: Optional[int] = Query(default=None, description="通过集合 ID 筛选 / Filter by collection ID"),
    filters: MediaFilterQueryParams = Depends(),
    order_by: Optional[str] = Query(default="media_id", description="排序字段 / Sort field"),
    order_dir: Optional[str] = Query(default="asc", pattern="^(asc|desc)$", description="排序方向：asc 或 desc / Sort direction: asc or desc")
) -> PagedApiResponse[list[MediaListPublic]]:
    """
    列出所有带有分页和搜索功能的媒体。 / List all media with pagination and search.
    
    - 匿名用户 (Anonymous users)：仅查看项目内公开集合中的媒体 /
      Anonymous users: see media from public collections under the project only
    - 普通用户 (Regular users)：仅查看可访问集合中的媒体 / Regular users: see media from accessible collections only
    - 管理员 (Admins)：可以查看所有媒体 / Admins: can see all media
    
    支持按多个字段筛选和全文搜索。 / Supports filtering by many fields and full-text search.
    """
    return media_service.get_media_list(
        session, current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
        order_by=order_by,
        order_dir=order_dir,
        collection_id=collection_id,
        **filters.to_filter_dict(),
    )


@router_views.get(
    "/media-browse-items",
    response_model=PagedApiResponse[list[MediaBrowseGalleryItem | MediaBrowseListItem]],
    summary="浏览媒体列表 / Browse Media List",
)
def browse_media(
    session: SessionDep,
    current_user: CurrentUserOptional,
    project_id: int = Query(..., description="通过项目 ID 筛选（必传） / Filter by project ID (required)"),
    view_type: Literal["gallery", "list"] = Query(..., description="展示类型：gallery 或 list / View type: gallery or list"),
    page: int = Query(default=1, ge=1, description="页码 / Page number"),
    page_size: int = Query(default=settings.DEFAULT_PAGE_LIMIT, ge=1, le=100, description="每页条目数 / Items per page"),
    collection_id: Optional[int] = Query(default=None, description="通过集合 ID 筛选 / Filter by collection ID"),
    site_id: Optional[int] = Query(default=None, description="通过站点 ID 筛选 / Filter by site ID"),
    name: Optional[str] = Query(default=None, description="browse 跨字段搜索词（不区分大小写） / Browse multi-field search term (case-insensitive)"),
    media_type: Literal["all", "audio", "photo"] = Query(default="all", description="媒体类型筛选：all / audio / photo / Filter by media type"),
    order_by: Optional[str] = Query(default="media_id", description="排序字段 / Sort field"),
    order_dir: Optional[str] = Query(default="asc", pattern="^(asc|desc)$", description="排序方向：asc 或 desc / Sort direction: asc or desc"),
) -> PagedApiResponse[list[MediaBrowseGalleryItem | MediaBrowseListItem]]:
    """
    浏览媒体列表（支持两种展示模式）。 / Browse media list with two view modes.

    权限规则 / Permission rules:
    - 未登录用户 (Anonymous)：仅返回公开集合中的媒体 / Returns media from public collections only
    - 登录用户 (Authenticated)：按权限返回（管理员全量，普通用户为可访问集合 + 公开集合） /
      Returns by permission (admin: all, regular user: accessible collections + public collections)
    - `preview_url`：返回站点根相对的媒体地址（若有预览图），例如 `/sounds/...` /
      `preview_url`: site-root-relative media URL (when preview exists), for example `/sounds/...`
    - `view_type=list` 时包含站点 `freshwater_depth_m`（米，可选） /
      When `view_type=list`, each item includes site `freshwater_depth_m` (meters, optional)
    """
    return media_service.browse_media_list(
        session,
        current_user,
        project_id=project_id,
        view_type=view_type,
        page=page,
        page_size=page_size,
        collection_id=collection_id,
        site_id=site_id,
        name=name,
        media_type=media_type,
        order_by=order_by,
        order_dir=order_dir,
    )


@router_views.get("/audios/exports", summary="导出音频 / Export Audios")
def export_audios(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: int = Query(..., description="项目 ID（必传） / Project ID (required)"),
    collection_id: int | None = Query(None, description="集合 ID（可选） / Collection ID (optional)"),
    order_by: str = Query(default="media_id", description="排序字段 / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction"),
):
    """导出权限范围内的音频。 / Export permitted audio records."""
    csv_content = media_service.export_media_csv(
        session,
        current_user,
        project_id=project_id,
        collection_id=collection_id,
        media_type="audio",
        order_by=order_by,
        order_dir=order_dir,
    )
    return csv_response(csv_content, "audios.csv")


@router_views.get("/photos/exports", summary="导出图片 / Export Photos")
def export_photos(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: int = Query(..., description="项目 ID（必传） / Project ID (required)"),
    collection_id: int | None = Query(None, description="集合 ID（可选） / Collection ID (optional)"),
    order_by: str = Query(default="media_id", description="排序字段 / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction"),
):
    """导出权限范围内的图片。 / Export permitted photo records."""
    csv_content = media_service.export_media_csv(
        session,
        current_user,
        project_id=project_id,
        collection_id=collection_id,
        media_type="photo",
        order_by=order_by,
        order_dir=order_dir,
    )
    return csv_response(csv_content, "photos.csv")


@router_views.get("/media-options", response_model=ApiResponse[list[MediaOption]], summary="媒体下拉选项 / Media Options")
def list_media_options(
    session: SessionDep,
    current_user: CurrentUserOptional,
    project_id: int = Query(..., description="通过项目 ID 筛选（必传） / Filter by project ID (required)"),
    collection_id: Optional[int] = Query(default=None, description="通过集合 ID 筛选 / Filter by collection ID"),
    name: Optional[str] = Query(default=None, description="通过文件名或名称筛选 / Filter by filename or name")
) -> Any:
    """
    获取媒体下拉选项列表（仅返回 media_id 和名称）。 / Get media dropdown options (media_id and name only).
    
    - 匿名用户 (Anonymous users)：仅查看该项目下公开集合中的媒体 /
      Anonymous users: see media from public collections in the project only
    - 管理员 (Admins)：可以查看该项目下的所有媒体 / Admins: can see all media in the project
    - 普通用户 (Regular users)：仅查看可访问集合中的媒体 / Regular users: see media from accessible collections only
    """
    options = media_service.get_media_options(
        session, current_user, 
        project_id=project_id, 
        collection_id=collection_id,
        name=name
    )
    return api_success(data=options)


@router_views.get(
    "/media-timeline-items",
    response_model=ApiResponse[MediaTimelineResponse],
    summary="媒体时间线数据 / Get Media Timeline Data",
)
def get_media_timeline(
    session: SessionDep,
    current_user: CurrentUserOptional = None,
    project_id: int = Query(..., description="项目 ID（必填） / Project ID (required)"),
    collection_id: Optional[int] = Query(default=None, description="集合 ID（选填） / Collection ID (optional)"),
    site_ids: Optional[str] = Query(default=None, description="按站点过滤（逗号分隔） / Filter by site IDs (comma-separated)"),
    include_metadata: bool = Query(default=True, description="是否包含 metadata 条目 / Whether to include metadata items"),
    response_mode: Literal["overview", "detail"] = Query(default="overview", description="响应模式：overview 概览或 detail 站点视窗明细 / ApiResponse mode: overview or site-window detail"),
    site_key: Optional[str] = Query(default=None, description="detail 模式站点键 / Site key for detail mode"),
    start_date: Optional[datetime] = Query(default=None, description="detail 模式开始时间 / Detail window start"),
    end_date: Optional[datetime] = Query(default=None, description="detail 模式结束时间 / Detail window end"),
    media_type: Literal["all", "audio", "photo"] = Query(default="all", description="媒体类型筛选：all / audio / photo / Filter by media type"),
) -> Any:
    """
    获取媒体 timeline 视图所需数据。 / Get media timeline data.

    权限规则 / Permission rules:
    - 仅传 `project_id`：匿名仅可访问公开项目中的公开集合媒体；登录用户可访问项目下“公开集合 + 有 `audio:read` 权限集合”的媒体。
      / `project_id` only: anonymous users can access media from public collections under a public project; authenticated users can access public + `audio:read` collections under the project.
    - 同时传 `collection_id`：该集合必须属于项目，且权限按 `audio:read` 校验。
      / With `collection_id`: the collection must belong to the project, and access is checked with `audio:read`.

    查询行为 / Query behavior:
    - `site_ids` 过滤命中指定站点，同时保留未地理关联记录。 /
      `site_ids` matches the requested sites and still keeps non geo-referenced records.
    - `include_metadata` 仅控制 metadata 条目是否进入 timeline。 /
      `include_metadata` only controls whether metadata rows are included in the timeline.
    - overview 模式下 metadata 固定按站点和月份汇总。 /
      In overview mode, metadata is always grouped by site and month.
    - `response_mode=detail` 需要 `site_key`、`start_date`、`end_date`，只返回当前站点视窗明细。 /
      `response_mode=detail` requires `site_key`, `start_date`, and `end_date`, returning one site-window detail.
    - timeline 固定按名称升序排序。 /
      Timeline is always sorted by name ascending.
    """
    parsed_site_ids = media_service.parse_timeline_site_ids(site_ids)
    data = media_service.build_media_timeline_data(
        session,
        current_user=current_user,
        project_id=project_id,
        collection_id=collection_id,
        site_ids=parsed_site_ids,
        include_metadata=include_metadata,
        response_mode=response_mode,
        site_key=site_key,
        start_date=start_date,
        end_date=end_date,
        media_type=media_type,
    )
    return api_success(data=data)


@router.get("/{media_id}", response_model=ApiResponse[MediaPublic], summary="获取媒体 / Get Media")
def get_media(
    session: SessionDep,
    media_id: int,
    current_user: CurrentUserOptional,
    project_id: int = Query(..., description="项目 ID（必填） / Project ID (required)"),
) -> Any:
    """
    通过 ID 获取媒体。 / Get a media by ID.

    匿名仅可访问关联到任一 public_access 集合的媒体；非公开媒体返回 403。
    / Anonymous can access media linked to at least one public_access collection; non-public media returns 403.
    返回包含 previews、关联实体名称、集合/项目信息和当前用户标签状态的完整响应。
    Returns full response with previews, related entity names, collection/project info, and user label status.
    - `previews[].url` 返回站点根相对的静态媒体地址，例如 `/sounds/...`。 /
      `previews[].url` is a site-root-relative static media URL, for example `/sounds/...`.
    """
    media_public = media_service.get_media(session, project_id, media_id, current_user)
    return api_success(data=media_public)


@router.get(
    "/{media_id}/collection-options",
    response_model=ApiResponse[MediaCollectionLinkOptionsResponse],
    summary="获取媒体关联集合弹窗数据 / Get Media Collection Link Options",
)
def get_media_collection_link_options(
    session: SessionDep,
    media_id: int,
    current_user: User = CanWriteProject,
    project_id: int = Query(..., description="当前项目 ID（必填） / Current project ID (required)"),
    name: Optional[str] = Query(default=None, description="按集合名称搜索 / Search by collection name"),
    other_project_name: Optional[str] = Query(default=None, description="按其他项目名称搜索 / Search by other project name"),
) -> Any:
    """
    获取媒体关联集合弹窗数据。 / Get grouped options for media-collection link dialog.

    - 需要对当前项目有 project:write 权限。 / Requires project:write on the current project.
    - 还需要对该媒体当前所属任一集合有 audio:write 权限。 /
      Also requires audio:write on at least one collection currently linked to the media.
    """
    media_service.require_media_resource_write(
        session,
        current_user,
        media_id,
        project_id=project_id,
    )
    data = media_service.get_media_collection_link_options(
        session,
        media_id,
        current_user,
        project_id=project_id,
        name=name,
        other_project_name=other_project_name,
    )
    return api_success(data=data)


@router.post("", response_model=ApiResponse[MediaCreateResponse], summary="批量处理媒体 / Create Media")
async def create_media(
    request: MediaCreate,
    session: SessionDep,
    current_user: ActiveManager,
    publisher: TaskPublisherDep,
    project_id: int | None = Query(default=None, description="项目 ID / Project ID"),
) -> Any:
    """
    创建一批上传的媒体。 / Create a batch of uploaded media.

    本接口： / This endpoint:
    1. 验证集合是否存在以及用户的写入权限（控制器层） / Validates collection existence and user write permission (Controller Layer)
    2. 对于 `file_upload_ids` 数组中的每个 ID：验证其是否存在且处于待处理 (pending) 状态（服务层） / For each ID in `file_upload_ids`: validates it exists and is in pending status (Service Layer)
    3. 为整批文件创建一个后台处理队列（服务层） / Creates one background processing queue for the batch (Service Layer)

    文件必须先通过 /file-upload-chunks 上传。 / Files must have been uploaded via /file-upload-chunks first.
    当收到最后一个分块时，将自动创建 FileUpload 记录。 / The FileUpload record is automatically created when the last chunk is received.

    字段语义说明（音频）： / Field semantics (audio):
    - `name` 保留原始上传文件名（展示语义）。 / `name` keeps the original uploaded filename for display.
    - `filename` 保存转码后的实际文件名（音频统一为 `.flac`，含前缀时也会反映在此字段）。 / `filename` stores the normalized storage filename (audio is normalized to `.flac`, including prefix when provided).
    - 实际落盘文件统一为 FLAC，并通过路径兼容规则解析。 / Physical storage is normalized to FLAC and resolved through compatibility path lookup.
    """
    permission_service.require_collection_resource_permission(
        session,
        collection_id=request.collection_id,
        project_id=project_id,
        user=current_user,
        resource_type="audio",
        action="write",
        denied_detail="No write permission on collection",
    )

    data = await media_service.create_media(
        session,
        request,
        current_user,
        publisher,
        project_id=project_id,
    )

    if not data.queued and data.failed and data.queue_id is None:
        parts: list[str] = []
        if data.failed:
            reasons = "; ".join(f.reason for f in data.failed[:5])
            parts.append(f"{len(data.failed)} file(s) failed to process: {reasons}")
        error_payload = ApiErrorResponse(code=409, message=" ".join(parts))
        return JSONResponse(status_code=409, content=error_payload.model_dump())

    return api_success(data=data)



@router_views.post("/media-metadata-imports", summary="导入元数据 / Import Metadata")
async def import_metadata(
    session: SessionDep,
    current_user: ActiveManager,
    project_id: int = Form(..., description="项目 ID / Project ID"),
    collection_id: int = Form(..., description="目标集合 ID / Target collection ID"),
    file: UploadFile = File(..., description="带有元数据的 CSV 文件 / CSV file with metadata"),
    media_type: Literal["audio", "photo"] = Form(default="audio", description="元数据类型：audio 或 photo / Metadata type: audio or photo"),
) -> Any:
    """
    从 CSV 文件导入媒体元数据。 / Import media metadata from a CSV file.

    CSV 列要求随 `media_type` 不同而不同： / Required CSV columns differ by `media_type`:
    - `audio`（默认）：date_time, duration_s, sampling_rate_hz, name, bit_depth, channel_num, duty_cycle_recording, duty_cycle_period /
      `audio` (default): date_time, duration_s, sampling_rate_hz, name, bit_depth, channel_num, duty_cycle_recording, duty_cycle_period
    - `photo`：date_time, name, exposure_ms, aperture, iso /
      `photo`: date_time, name, exposure_ms, aperture, iso

    首先校验表头：按列名（不区分大小写）匹配，不依赖列顺序；出现未知列、重复列或缺少必填列时整个导入将被中止。 / Headers are validated first: columns are matched by name (case-insensitive) instead of position; unknown, duplicated or missing required columns abort the import.

    然后对所有行进行验证并返回逐行结果。任何行失败时整个导入不会写入数据。 / All rows are validated and reported. If any row fails, the import writes no data.

    与目标集合中已有元数据记录（或文件内前面的行）所有字段完全一致的行将被跳过，并通过逐行结果及 `skipped` 计数返回。 / Duplicate rows are returned as skipped with a row-level reason.
    """
    permission_service.require_collection_resource_permission(
        session,
        current_user,
        "audio",
        "write",
        project_id=project_id,
        collection_id=collection_id,
        denied_detail="No write permission on collection",
    )

    extension_for(file.filename or "", {"csv"})
    # validate_csv_content 已完成解码与严格 CSV 校验，直接复用其文本，避免重复读取解析。 /
    # validate_csv_content already decoded and strictly validated the CSV; reuse its text to avoid re-reading/re-parsing.
    text = validate_csv_content(await file.read())

    try:
        data = media_service.import_metadata_csv(
            session, text, collection_id, current_user, media_type=media_type
        )
    except HTTPException as exc:
        message = (
            str(exc.detail.get("message"))
            if isinstance(exc.detail, dict) and "message" in exc.detail
            else str(exc.detail)
        )
        error_payload = ApiErrorResponse(
            code=exc.status_code,
            message=message,
        )
        return JSONResponse(status_code=exc.status_code, content=error_payload.model_dump())
    return api_success(data=data)


@router.patch(
    "/{media_id}",
    response_model=ApiResponse[None],
    summary="更新媒体 / Update Media"
)
def update_media(
    session: SessionDep,
    media_id: int,
    media_in: MediaUpdate,
    current_user: CurrentUser,
    project_id: int = Query(..., description="项目 ID（必填） / Project ID (required)"),
) -> Any:
    """
    更新媒体记录。 / Update a media record.

    需要对该媒体所属的至少一个集合拥有 audio:write 权限。 / Requires audio:write permission on at least one of its collections.
    通过完整的权限继承链进行检查（project:write 和 collection:write 均可满足）。 /
    Checked via the inherited permission chain (project:write and collection:write both satisfy it).
    """
    media_service.require_media_resource_write(
        session,
        current_user,
        media_id,
        project_id=project_id,
    )

    media_service.update_media(
        session,
        media_id,
        media_in,
        current_user=current_user,
        project_id=project_id,
    )
    return api_success()


@router_views.put(
    "/media-collection-links",
    response_model=ApiResponse[MediaBatchOperationResponse],
    summary="批量同步媒体集合关联 / Batch Sync Media Collection Links",
)
def sync_media_collection_links(
    session: SessionDep,
    payload: MediaCollectionLinksSyncRequest,
    current_user: CurrentUser,
    project_id: int = Query(..., description="当前项目 ID（必填） / Current project ID (required)"),
) -> Any:
    """
    批量全量同步媒体与集合关系。 / Fully sync media-collection links in batch.

    - 对每个媒体：需要对该媒体当前所属任一集合有 audio:write 权限。 /
      For each media: requires audio:write on at least one collection currently linked to it.
    - 对请求中的每个集合都需要 audio:write 权限。 / Requires audio:write on every requested collection.
    - 所有媒体都会被覆盖为同一组 collection_ids。 / Every media is overwritten with the same collection_ids.
    """
    data = media_service.sync_media_collection_links(
        session,
        current_user,
        payload.media_ids,
        payload.collection_ids,
        project_id=project_id,
    )
    return api_success(data=data)


@router.delete("/{media_id}", response_model=ApiResponse, summary="删除媒体 / Delete Media")
def delete_media(
    session: SessionDep,
    media_id: int,
    current_user: CurrentUser,
    project_id: int | None = Query(default=None, description="项目 ID / Project ID"),
) -> ApiResponse:
    """
    删除媒体记录。 / Delete a media record.

    需要 audio:write 权限。 / Requires audio:write permission.
    """
    return media_service.delete_media(session, media_id, current_user, project_id=project_id)



@router.get("/{media_id}/audio", summary="获取音频流 / Stream Audio")
def stream_audio(
    session: SessionDep,
    media_id: int,
    current_user: CurrentUserOptional,
    project_id: int = Query(..., description="项目 ID（必填） / Project ID (required)"),
    start_time: Optional[float] = Query(None, description="开始时间（秒） / Start time in seconds"),
    end_time: Optional[float] = Query(None, description="结束时间（秒） / End time in seconds"),
    min_freq: Optional[float] = Query(None, ge=0, description="最低频率（Hz） / Minimum frequency (Hz)"),
    max_freq: Optional[float] = Query(None, ge=0, description="最高频率（Hz），默认 Nyquist / Maximum frequency (Hz), defaults to Nyquist"),
    channel: Optional[int] = Query(None, description="声道（1=左/2=右，不传则混合/原始） / Channel (1=left, 2=right, None=original)"),
    filter: bool = Query(False, description="是否先按频段过滤音频 / Whether to filter audio by frequency band"),
    fft_size: Optional[int] = Query(None, description="共享详情临时资源 key 的 FFT 参数 / FFT used for shared detail asset key"),
):
    """
    流式返回音频文件，支持带权限校验、时间裁切、频段带通和声道选择。
    Stream an audio file with permission check, optional time trimming, bandpass and channel selection.

    支持 HTTP Range 请求（无任何处理参数时）。 / Supports HTTP Range requests when no processing is requested.
    匿名可访问公开集合媒体；私有媒体返回 403。登录用户需具备 audio:read 或命中公开集合。
    / Anonymous can access media in public collections; private media returns 403.
    Authenticated users need audio:read or public-collection access.
    前端下载当前视口时必须传 `start_time` 和 `end_time`；若启用频带裁剪，还应同时传
    `min_freq`、`max_freq` 和 `filter=true`，并优先使用响应头中的下载文件名。
    / Frontend viewport downloads must send `start_time` and `end_time`; when band filtering is enabled,
    also send `min_freq`, `max_freq`, and `filter=true`, and prefer the server-provided download filename.
    """
    if fft_size is not None and fft_size not in _SPECTROGRAM_FFT_SIZES:
        raise HTTPException(status_code=422, detail="Invalid FFT size")

    # Permission check (reuse get_media which checks permissions)
    media_service.get_media(session, project_id, media_id, current_user)

    try:
        file_path, media_type, download_filename = media_service.get_audio_stream_payload(
            session,
            media_id,
            start_time=start_time,
            end_time=end_time,
            min_freq=min_freq if filter else None,
            max_freq=max_freq if filter else None,
            channel=channel,
            filter_enabled=filter,
            fft_size=(
                int(fft_size)
                if fft_size is not None
                else media_service.resolve_spectrogram_fft_size(session, current_user)
            ),
        )
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        logger.error("audio processing failed: %s", exc)
        raise HTTPException(status_code=500, detail="Audio processing failed") from exc

    return FileResponse(
        str(file_path),
        media_type=media_type,
        headers={
            "Content-Disposition": build_download_content_disposition(download_filename)
        } if download_filename else None,
    )


@router.get("/{media_id}/content", summary="获取图片原件 / Get Photo Content")
def get_media_content(
    session: SessionDep,
    media_id: int,
    current_user: CurrentUserOptional,
    project_id: int = Query(..., description="项目 ID（必填） / Project ID (required)"),
):
    """返回经媒体读取权限校验后的图片原件。 / Return a photo after media read access is verified."""
    media = media_service.get_media(session, project_id, media_id, current_user)
    if media.media_type != "photo":
        raise HTTPException(status_code=404, detail="Photo content is not available for this media")
    file_path = media_service.get_media_content_path(session, media_id)
    media_type, _ = mimetypes.guess_type(str(file_path))
    return FileResponse(file_path, media_type=media_type or "application/octet-stream")



@router.get("/{media_id}/spectrogram", summary="获取频谱图 / Get Spectrogram")
def get_spectrogram(
    session: SessionDep,
    media_id: int,
    current_user: CurrentUserOptional,
    project_id: int = Query(..., description="项目 ID（必填） / Project ID (required)"),
    start_time: float = Query(0.0, description="开始时间（秒） / Start time in seconds"),
    end_time: Optional[float] = Query(None, description="结束时间（秒） / End time in seconds"),
    min_freq: float = Query(1.0, ge=0, description="最低频率（Hz） / Minimum frequency (Hz)"),
    max_freq: Optional[float] = Query(None, ge=0, description="最高频率（Hz），默认 Nyquist / Maximum frequency (Hz), defaults to Nyquist"),
    fft_size: Optional[int] = Query(None, description="FFT 窗口大小，可选 128/256/512/1024/2048/4096；默认取用户偏好或系统设置 / FFT window size"),
    window: str = Query("hanning", description="窗函数：hanning/hann/bartlett/blackman/hamming/kaiser / Window function"),
    channel: int = Query(1, ge=0, le=2, description="声道：0=混合，1=左，2=右 / Channel: 0=mix, 1=left, 2=right"),
    filter: bool = Query(False, description="是否先按频段过滤音频后再绘图 / Whether to filter audio by band before rendering"),
    width: int = Query(1200, ge=100, le=4096, description="图像宽度（像素） / Image width in pixels"),
    height: int = Query(400, ge=100, le=2048, description="图像高度（像素） / Image height in pixels"),
):
    """
    服务端生成频谱图 PNG（逐列 FFT、120 dB 动态范围、8-bit 调色板、线性频率轴）。
    Generate spectrogram PNG server-side via per-column FFT, 120 dB range, 8-bit palette, linear frequency axis.

    匿名可访问公开集合媒体；私有媒体返回 403。登录用户需具备 audio:read 或命中公开集合。
    / Anonymous can access media in public collections; private media returns 403.
    Authenticated users need audio:read or public-collection access.
    当前视口下载应沿用本接口参数，并优先使用响应头中的当前下载文件名。
    / Viewport downloads should reuse this endpoint's query params and prefer the current download filename
    from the response headers.
    """
    if fft_size is not None and fft_size not in _SPECTROGRAM_FFT_SIZES:
        raise HTTPException(status_code=422, detail="Invalid FFT size")
    if window not in WINDOW_FUNCTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid window function '{window}'. Must be one of: {', '.join(sorted(WINDOW_FUNCTIONS))}"
        )
    if width * height > _MAX_SPECTROGRAM_PIXELS:
        raise HTTPException(
            status_code=422,
            detail="Spectrogram dimensions exceed 4,000,000 pixels",
        )

    media_service.get_media(session, project_id, media_id, current_user)
    resolved_fft_size = (
        int(fft_size)
        if fft_size is not None
        else media_service.resolve_spectrogram_fft_size(session, current_user)
    )

    try:
        result = media_service.get_spectrogram(
            session,
            media_id,
            start_time=start_time,
            end_time=end_time,
            min_freq=min_freq,
            max_freq=max_freq,
            fft_size=resolved_fft_size,
            window=window,
            channel=channel,
            width_px=width,
            height_px=height,
            apply_frequency_filter=filter,
        )
        download_filename = media_service.get_spectrogram_download_filename(
            session,
            media_id,
            start_time=start_time,
            end_time=end_time,
            min_freq=min_freq,
            max_freq=max_freq,
            fft_size=resolved_fft_size,
            channel=channel,
            apply_frequency_filter=filter,
        )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        logger.error(f"Spectrogram generation failed for media {media_id}: {e}")
        raise HTTPException(status_code=500, detail="Spectrogram generation failed")

    return RawResponse(
        content=result,
        media_type="image/png",
        headers={
            "Content-Disposition": build_download_content_disposition(download_filename)
        },
    )



@router.get("/{media_id}/previews/{preview_id}", summary="获取预览文件 / Get Preview File")
def get_preview_file(
    session: SessionDep,
    media_id: int,
    preview_id: int,
    current_user: CurrentUser,
    project_id: int = Query(..., description="项目 ID（必填） / Project ID (required)"),
):
    """
    获取媒体的预览文件（频谱图/波形图）。 / Get preview file (spectrogram/waveform) for a media.

    权限：同 GET /media/{id}。 / Permission: same as GET /media/{id}.
    """
    # Permission check
    media_service.get_media(session, project_id, media_id, current_user)

    file_path = media_service.get_preview_file_path(session, media_id, preview_id)
    return FileResponse(file_path, media_type="image/png")

@router.get(
    "/{media_id}/navigation-items",
    response_model=ApiResponse[MediaNavigation],
    summary="获取媒体上下导航 / Get Media Navigation",
)
def get_media_navigation(
    session: SessionDep,
    media_id: int,
    current_user: CurrentUser,
    collection_id: int = Query(..., description="集合 ID（必传） / Collection ID (required)"),
) -> Any:
    """
    返回同一集合中当前媒体的上一条和下一条（按 media_id 排序）。
    Return prev/next media within the same collection (ordered by media_id).
    """
    nav = media_service.get_media_navigation(session, media_id, collection_id, current_user)
    return api_success(data=nav)
