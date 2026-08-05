/**
 * DescriptionTab - 项目描述页
 *
 * 包含项目标题、元数据、富文本描述、项目图片和 Collection 描述
 */

import { useState, useEffect, useRef } from "react"
import {
    Link as LinkIcon,
    User,
    Calendar,
    Bookmark,
    Globe,
} from "lucide-react"
import { useProjectStore } from "../../stores/useProjectStore"
import { applySphereTheme } from "../../sphereTheme"
import { projectsApi } from "../../../../api/endpoints/projects"
import { collectionsApi } from "../../../../api/endpoints/collections"
import { CustomScrollArea } from "@/components/ui"
import { UnifiedImage } from "@/components/ui"
import { parseRichText } from "@/utils/string"

type TaxonChip = { id?: number | null; cached_name?: string | null }

const META_ICON = 18
const SPHERE_ICON = 17
const TITLE_LINK_ICON = 24

function hasDoiValue(doi: unknown): boolean {
    if (doi == null) return false
    return String(doi).trim() !== ""
}

function formatDoiDisplay(doi: unknown): string {
    if (!hasDoiValue(doi)) return ""
    const s = String(doi)
    return s.includes("/") ? s.split("/")[1] ?? s : s
}

function normalizeTaxonTags(tags?: unknown): TaxonChip[] {
    if (!Array.isArray(tags)) return []
    const normalized: TaxonChip[] = []
    tags.forEach((tag, index) => {
        const name = String(tag ?? "").trim()
        if (!name) return
        normalized.push({ id: index, cached_name: name })
    })
    return normalized
}

function normalizeCollectionViewData(data: any) {
    return {
        project: {
            id: data?.project_id,
            name: data?.project_name,
            picture_url: data?.project_picture_url,
            sphere: data?.sphere,
            externalUrl: data?.project_url,
            url: data?.project_url,
        },
        collection: {
            id: data?.collection_id,
            name: data?.collection_name,
            code: data?.collection_code,
            picture_url: data?.project_picture_url,
            sphere: data?.sphere,
            external_media_url: data?.external_media_url,
            project_url: data?.project_url,
            creator_name: data?.researcher_name,
            creation_date: data?.collection_creation_date,
            description: data?.description,
            taxons: normalizeTaxonTags(data?.taxon_tags),
        },
    }
}

function SphereBadge({ sphere }: { sphere?: string | null }) {
    const s = sphere?.trim()
    if (!s) return null
    return (
        <div className="desc-sphere-badge">
            <Globe size={SPHERE_ICON} strokeWidth={2.25} aria-hidden />
            <span>{s.toUpperCase()}</span>
        </div>
    )
}

function TaxonTagRow({ taxons }: { taxons?: TaxonChip[] | null }) {
    const items = Array.isArray(taxons)
        ? taxons.filter((t) => t?.cached_name != null && String(t.cached_name).trim() !== "")
        : []
    if (items.length === 0) return null
    return (
        <div className="desc-taxons-row">
            {items.map((t, i) => (
                <span key={t.id != null ? `t-${t.id}` : `t-${i}-${t.cached_name}`} className="desc-taxon-tag">
                    {t.cached_name}
                </span>
            ))}
        </div>
    )
}

export function DescriptionTab() {
    const currentProjectId = useProjectStore((s) => s.currentProjectId)
    const currentCollectionId = useProjectStore((s) => s.currentCollectionId)
    const isCollectionMode = !!currentCollectionId && currentCollectionId !== ""

    const [project, setProject] = useState<any>(null)
    const [collection, setCollection] = useState<any>(null)
    const [loading, setLoading] = useState(false)
    const [imageLoaded, setImageLoaded] = useState(false)
    const descImageRef = useRef<HTMLImageElement>(null)
    const prevSelectionRef = useRef<{
        projectId: number | string | null | undefined
        collectionId: number | string | null | undefined
        isCollectionMode: boolean
    } | null>(null)

    const [slideDirection, setSlideDirection] = useState<"left" | "right">("left")

    const rawImage =
        isCollectionMode && collection
            ? collection.picture_url || collection.image || project?.picture_url || project?.image
            : project?.picture_url || project?.image
    const imageUrl = typeof rawImage === "string" ? rawImage.trim() : ""
    const hasVisual = imageUrl.length > 0

    // 切换 URL 后先清空再检测缓存（避免 onLoad 不触发时一直透明）
    useEffect(() => {
        if (!hasVisual) {
            setImageLoaded(false)
            return
        }
        setImageLoaded(false)
        const el = descImageRef.current
        if (el?.complete && el.naturalWidth > 0) {
            setImageLoaded(true)
        }
    }, [hasVisual, imageUrl])

    useEffect(() => {
        const fetchData = async () => {
            if (!currentProjectId && !currentCollectionId) {
                setProject(null)
                setCollection(null)
                return
            }

            setLoading(true)
            try {
                if (isCollectionMode) {
                    if (!currentProjectId) {
                        setCollection(null)
                        return
                    }
                    const res = await collectionsApi.getCollectionView(currentProjectId, currentCollectionId, true)
                    if (res && (res.code === 0 || res.code === 200)) {
                        const normalized = normalizeCollectionViewData(res.data)
                        setProject(normalized.project)
                        setCollection(normalized.collection)
                    }
                } else {
                    const res = await projectsApi.getProject(Number(currentProjectId), true)
                    if (res && (res.code === 0 || res.code === 200)) {
                        setProject(res.data)
                    }
                    setCollection(null)
                }
            } catch (error) {
                console.error("Failed to fetch description data:", error)
            } finally {
                setLoading(false)
            }
        }

        fetchData()
    }, [currentProjectId, currentCollectionId, isCollectionMode])

    useEffect(() => {
        const prev = prevSelectionRef.current
        if (prev) {
            if (prev.isCollectionMode !== isCollectionMode) {
                setSlideDirection(isCollectionMode ? "left" : "right")
            } else if (String(prev.collectionId ?? "") !== String(currentCollectionId ?? "")) {
                setSlideDirection("left")
            } else if (String(prev.projectId ?? "") !== String(currentProjectId ?? "")) {
                setSlideDirection("right")
            }
        }

        prevSelectionRef.current = {
            projectId: currentProjectId,
            collectionId: currentCollectionId,
            isCollectionMode,
        }
    }, [currentProjectId, currentCollectionId, isCollectionMode])

    /** 与 Description 展示的 sphere 一致，同步到全局 --brand（ALL Collections 时用项目级 sphere） */
    useEffect(() => {
        const restoreThemeFromStore = () => {
            const { currentCollectionId: cid, collectionOptions } = useProjectStore.getState()
            const col = collectionOptions.find(
                (c: { id?: number | string }) => String(c.id) === String(cid ?? "")
            )
            applySphereTheme(col?.sphere ?? null)
        }

        if (isCollectionMode && collection) {
            applySphereTheme(collection.sphere || null)
        } else if (!isCollectionMode && project) {
            applySphereTheme(project.sphere || null)
        } else {
            restoreThemeFromStore()
        }

        return () => {
            restoreThemeFromStore()
        }
    }, [isCollectionMode, project, collection])

    if (!project && !collection && !loading) {
        // return <div className="tab-placeholder"><p>No Data</p></div>
        return null
    }

    const entity = isCollectionMode ? collection : project
    const displayName = entity?.name ?? "Loading..."

    const doiRaw = entity?.doi
    const showDoi = hasDoiValue(doiRaw)
    const doiDisplay = formatDoiDisplay(doiRaw)

    const creatorDisplay = isCollectionMode
        ? collection?.creator && typeof collection.creator === "object"
            ? collection.creator.name
            : collection?.creator_name || collection?.creator || "-"
        : project?.creator_name || project?.creator || "-"

    const externalHref = isCollectionMode
        ? collection?.project_url || collection?.external_media_url
        : project?.externalUrl || project?.url

    const coverAlt =
        typeof displayName === "string" && displayName.trim() !== "" && displayName !== "Loading..."
            ? displayName
            : "Cover"

    const layoutKey = isCollectionMode
        ? `collection-${collection?.id ?? currentCollectionId ?? "pending"}`
        : `project-${project?.id ?? currentProjectId ?? "pending"}`

    return (
        <div className="desc-layout-shell">
            <div
                key={layoutKey}
                className={`desc-layout-stage desc-layout-stage--slide-${slideDirection}`}
            >
                <div
                    className={`desc-layout${isCollectionMode ? " mode-collection" : ""}${!hasVisual ? " desc-layout--no-visual" : ""}`}
                >
                    {/* 左侧面板 - 项目描述 */}
                    <div className="panel-anim" id="panel-proj-desc">
                        {/* Header: 标题 + 元数据 */}
                        <div className="desc-header-section block-anim">
                            <SphereBadge sphere={entity?.sphere} />
                            <div className="title-row">
                                <h1 className="desc-title-text">{displayName}</h1>
                                {externalHref && (
                                    <a
                                        className="title-link-icon"
                                        href={externalHref}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        title={isCollectionMode ? "Open project link" : "Visit Project Website"}
                                    >
                                        <LinkIcon size={TITLE_LINK_ICON} />
                                    </a>
                                )}
                            </div>
                            <div className="meta-row">
                                <div className="meta-capsule-box">
                                    <div className="meta-item-btn" title="Creator">
                                        <div className="meta-item-icon">
                                            <User size={META_ICON} />
                                        </div>
                                        <span>{creatorDisplay}</span>
                                    </div>
                                    <div className="meta-divider" />
                                    <div className="meta-item-btn" title="Creation Date">
                                        <div className="meta-item-icon">
                                            <Calendar size={META_ICON} />
                                        </div>
                                        <span>{entity?.creation_date || entity?.date || "-"}</span>
                                    </div>
                                    {showDoi ? (
                                        <>
                                            <div className="meta-divider" />
                                            <div className="meta-item-btn" title="DOI">
                                                <div className="meta-item-icon">
                                                    <Bookmark size={META_ICON} />
                                                </div>
                                                <span>{doiDisplay}</span>
                                            </div>
                                        </>
                                    ) : null}
                                </div>
                            </div>
                            <TaxonTagRow taxons={entity?.taxons as TaxonChip[] | undefined} />
                        </div>

                        {/* 富文本描述区域 */}
                        <CustomScrollArea
                            className="desc-content-area block-anim"
                            bodyClassName="desc-content-area__body"
                            contentFingerprint={String(entity?.description || "")}
                            variant="fill"
                            allowHorizontal
                        >
                            <div
                                className="editor-tiptap-content"
                                dangerouslySetInnerHTML={{ __html: parseRichText(entity?.description) }}
                            />
                        </CustomScrollArea>
                    </div>

                    {/* 中间面板 - 项目图片（无图时不渲染，左右内容全宽） */}
                    {hasVisual ? (
                        <div className="panel-anim" id="panel-visual">
                            <div className="desc-image-container">
                                <UnifiedImage
                                    ref={descImageRef}
                                    key={imageUrl}
                                    alt={coverAlt}
                                    className={`desc-project-img ${imageLoaded ? "loaded" : ""}`}
                                    src={imageUrl}
                                    decoding="async"
                                    onLoad={() => setImageLoaded(true)}
                                    onError={() => setImageLoaded(true)}
                                />
                            </div>
                        </div>
                    ) : null}

                    {/* 右侧面板 - Collection 描述 */}
                    <div className="panel-anim" id="panel-col-desc">
                        {isCollectionMode && collection && (
                            <CollectionCard collection={collection} />
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}

/**
 * CollectionCard - Collection 卡片子组件
 */
function CollectionCard({ collection }: { collection: any }) {
    const colDoi = collection?.doi
    const showDoi = hasDoiValue(colDoi)
    const doiDisplay = formatDoiDisplay(colDoi)
    const descHtml = collection?.description != null ? String(collection.description) : ""

    return (
        <div className="collection-card block-anim">
            <div className="col-header-group">
                <SphereBadge sphere={collection?.sphere} />
                <div className="title-row">
                    <h2 className="col-title smooth-text">{collection?.name || "Loading..."}</h2>
                </div>
                <div className="col-meta-row smooth-text">
                    <div className="meta-capsule-box">
                        <div className="meta-item-btn">
                            <div className="meta-item-icon">
                                <User size={META_ICON} />
                            </div>
                            {(collection?.creator && typeof collection.creator === 'object') ? collection.creator.name : (collection?.creator_name || collection?.creator || "-")}
                        </div>
                        <div className="meta-divider" />
                        <div className="meta-item-btn">
                            <div className="meta-item-icon">
                                <Calendar size={META_ICON} />
                            </div>
                            {collection?.creation_date || collection?.date || "-"}
                        </div>
                        {showDoi ? (
                            <>
                                <div className="meta-divider" />
                                <div className="meta-item-btn">
                                    <div className="meta-item-icon">
                                        <Bookmark size={META_ICON} />
                                    </div>
                                    {doiDisplay}
                                </div>
                            </>
                        ) : null}
                    </div>
                </div>
                <TaxonTagRow taxons={collection?.taxons as TaxonChip[] | undefined} />
            </div>
            <CustomScrollArea
                className="col-rich-text smooth-text"
                bodyClassName="col-rich-text__body"
                contentFingerprint={descHtml}
                variant="fill"
                allowHorizontal
            >
                <div
                    className="editor-tiptap-content"
                    dangerouslySetInnerHTML={{ __html: parseRichText(descHtml) }}
                />
            </CustomScrollArea>
        </div>
    )
}
