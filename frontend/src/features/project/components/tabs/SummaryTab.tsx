/**
 * SummaryTab - 统计汇总页
 *
 * 包含统计卡片网格 + 贡献者列表
 */

import { useEffect, useRef, useState } from "react"
import {
    Users,
    Library,
    Mic,
    Image,
    ScanLine,
    MapPin,
    FolderKanban,
    Mail,
    IdCard,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { EmptyState } from "@/components/ui"
import { LoadingState } from "@/components/ui"
import { useProjectStore } from "../../stores/useProjectStore"
import { projectsApi } from "../../../../api/endpoints/projects"
import type { ProjectOverviewParams } from "../../../../api/endpoints/projects"
import type { ProjectStats, Contributor } from "../../types"

/** 统计项图标映射 */
const STAT_ICONS: Record<string, LucideIcon> = {
    users: Users,
    collections_or_projects: Library,
    audios: Mic,
    photos: Image,
    annotations: ScanLine,
    sites: MapPin,
}

/** 统计项显示名 */
const STAT_LABELS: Record<string, string> = {
    users: "Users",
    collections_or_projects: "Collections",
    audios: "Audios",
    photos: "Photos",
    annotations: "Annotations",
    sites: "Sites",
}

/** 统计项显示顺序 */
const STAT_ORDER = ["users", "collections_or_projects", "audios", "photos", "annotations", "sites"]
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function getDisplayEmail(value: string | null | undefined) {
    const email = value?.trim()
    return email && EMAIL_PATTERN.test(email) ? email : ""
}

export function SummaryTab() {
    const currentProjectId = useProjectStore((s) => s.currentProjectId)
    const currentCollectionId = useProjectStore((s) => s.currentCollectionId)
    const requestSeqRef = useRef(0)

    const project = useProjectStore((s) => {
        if (!s.currentProjectId) return undefined
        return s.projects.find(p => String(p.id) === String(s.currentProjectId))
    })
    const collection = useProjectStore((s) => {
        if (!s.currentCollectionId) return undefined
        return s.collectionOptions.find(c => String(c.id) === String(s.currentCollectionId))
    })
    const isCollectionMode = !!collection && collection.id !== ""

    const [summaryData, setSummaryData] = useState<{ stats: ProjectStats; contributors: Contributor[] } | null>(null)
    const [loading, setLoading] = useState(false)

    useEffect(() => {
        if (!currentProjectId) {
            setSummaryData(null)
            return
        }
        const requestSeq = ++requestSeqRef.current

        const fetchSummary = async () => {
            setLoading(true)
            try {
                const params: ProjectOverviewParams = { project_id: currentProjectId }
                if (isCollectionMode && currentCollectionId) {
                    params.collection_id = currentCollectionId
                }
                const res = await projectsApi.getSummary(params, true)
                if (requestSeq === requestSeqRef.current && res?.data) {
                    setSummaryData(res.data)
                }
            } catch (error) {
                if (requestSeq === requestSeqRef.current) {
                    console.error("Failed to fetch summary:", error)
                }
            } finally {
                if (requestSeq === requestSeqRef.current) {
                    setLoading(false)
                }
            }
        }

        fetchSummary()
    }, [currentProjectId, currentCollectionId, isCollectionMode])

    if (!project) {
        // return <div className="tab-placeholder"><p>No project selected</p></div>
        return null
    }

    const entityType = isCollectionMode ? "Collection" : "Project"

    const stats: ProjectStats | undefined = summaryData?.stats
    const contributors: Contributor[] = summaryData?.contributors || []

    return (
        <div className="summary-layout">
            {/* 统计卡片网格 */}
            <div className={`summary-stats-container block-anim ${loading ? 'loading' : ''}`}>
                {STAT_ORDER.map((key) => {
                    const value = stats ? (stats[key as keyof ProjectStats] ?? 0) : "-"
                    const Icon =
                        key === "collections_or_projects"
                            ? (isCollectionMode ? FolderKanban : Library)
                            : (STAT_ICONS[key] ?? MapPin)
                    const label =
                        key === "collections_or_projects"
                            ? (isCollectionMode ? "Projects" : "Collections")
                            : (STAT_LABELS[key] ?? key)

                    return (
                        <div className="summary-stat-card" key={key}>
                            <div className="stat-content-left">
                                <div className={`summary-stat-val ${key === "users" ? "highlight" : ""}`}>
                                    {value}
                                </div>
                                <div className="summary-stat-label">{label}</div>
                            </div>
                            <Icon className="bg-icon" />
                        </div>
                    )
                })}
            </div>

            {/* 贡献者卡片 */}
            <div className="summary-contributors-card block-anim">
                <div className="card-header">
                    <div className="card-title">
                        {isCollectionMode ? <Library /> : <FolderKanban />}
                        {entityType} Contributors
                    </div>
                </div>
                <div className="card-body">
                    <div className="contributors-list">
                        {contributors.map((person, index) => (
                            <ContributorItem
                                key={person.user_id ?? `${person.name}-${index}`}
                                contributor={person}
                                isCreator={index === 0}
                                entityType={entityType}
                            />
                        ))}
                        {loading && contributors.length === 0 && (
                            <LoadingState label="Loading contributors..." variant="inline" size="sm" />
                        )}
                        {!loading && contributors.length === 0 && (
                            <EmptyState className="summary-empty-state" title="No contributors yet" />
                        )}
                    </div>
                </div>
                <FolderKanban className="bg-icon-contrib" />
            </div>
        </div>
    )
}

/** 贡献者条目 */
function ContributorItem({
    contributor,
    isCreator,
    entityType,
}: {
    contributor: Contributor
    isCreator: boolean
    entityType: string
}) {
    const displayRole = isCreator
        ? `${entityType} Creator`
        : contributor.contribution_role?.trim() || contributor.role?.trim() || "Contributor"
    const email = getDisplayEmail(contributor.email)
    const orcid = contributor.orcid?.trim()

    return (
        <div className="contrib-item">
            <div className="contrib-info-block">
                <span className="contrib-name">{contributor.name}</span>
                {(email || orcid) && (
                    <div className="contrib-sub">
                        {email && (
                            <a href={`mailto:${email}`} className="contrib-email">
                                <Mail size={14} />
                                {email}
                            </a>
                        )}
                        {orcid && (
                            <>
                                {email && <span className="contrib-divider">•</span>}
                                <a
                                    href={`https://orcid.org/${orcid}`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="orcid-link"
                                    title={`ORCID: ${orcid}`}
                                >
                                    <IdCard size={14} />
                                    <span className="cid">{orcid}</span>
                                </a>
                            </>
                        )}
                    </div>
                )}
            </div>
            <span className={`contrib-role-text ${isCreator ? "creator-role" : ""}`}>
                {displayRole}
            </span>
        </div>
    )
}
