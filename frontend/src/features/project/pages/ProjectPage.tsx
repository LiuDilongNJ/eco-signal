/**
 * ProjectPage - 项目主页面
 *
 * 包含导航栏和 Tab 内容区的完整页面布局
 */

import { ProjectNavBar } from "../components/nav/ProjectNavBar"
import { DescriptionTab } from "../components/tabs/DescriptionTab"
import { SummaryTab } from "../components/tabs/SummaryTab"
import { MediaTab } from "../components/tabs/MediaTab"
import { MapTab } from "../components/tabs/MapTab"
import { TimelineTab } from "../components/tabs/TimelineTab"
import { DataTab } from "../components/tabs/DataTab"
import { useTabStore } from "../stores/useTabStore"
import { useProjectStore } from "../stores/useProjectStore"
import { useEffect, useLayoutEffect, useRef } from "react"
import { useNavigate, useParams, useSearchParams } from "react-router-dom"
import { MediaDetailView } from "../components/media/MediaDetailView"
import type { TabName } from "../types"
import {
    collectionToSearchParam,
    parseCollectionParamForRestore,
    parseTabParam,
} from "../utils/dashboardSearchParams"
import "../project.css"
import "../data-timeline.css"
import "../modals.css"
import "../ai-panels.css"
import "../media-detail.css"

const TAB_COMPONENTS: Record<TabName, React.ComponentType> = {
    desc: DescriptionTab,
    summary: SummaryTab,
    media: MediaTab,
    map: MapTab,
    timeline: TimelineTab,
    data: DataTab,
}

export default function ProjectPage() {
    const activeTab = useTabStore((s) => s.activeTab)
    const setActiveTab = useTabStore((s) => s.setActiveTab)
    const fetchProjectOptions = useProjectStore((s) => s.fetchProjectOptions)
    const syncProjectFromRoute = useProjectStore((s) => s.syncProjectFromRoute)
    const currentProjectId = useProjectStore((s) => s.currentProjectId)
    const currentCollectionId = useProjectStore((s) => s.currentCollectionId)
    const collectionOptions = useProjectStore((s) => s.collectionOptions)
    const selectCollection = useProjectStore((s) => s.selectCollection)
    const navigate = useNavigate()
    const [searchParams, setSearchParams] = useSearchParams()
    const { id: projectRouteId, mediaId: mediaIdParam } = useParams<{
        id?: string
        mediaId?: string
    }>()
    const projectIdFromRoute =
        projectRouteId !== undefined && projectRouteId !== ""
            ? Number(projectRouteId)
            : NaN

    const mediaIdFromRoute =
        mediaIdParam !== undefined && mediaIdParam !== ""
            ? Number(mediaIdParam)
            : NaN
    const hasMediaDetailInUrl = Number.isFinite(mediaIdFromRoute)
    /** 仅在 Media Tab 时全屏详情；切到其他 Tab 时改为主内容区，避免顶栏 Tab 看似无效 */
    const showMediaDetail = hasMediaDetailInUrl && activeTab === "media"

    useEffect(() => {
        if (!Number.isFinite(projectIdFromRoute)) return
        if (String(currentProjectId ?? "") === String(projectIdFromRoute)) return
        void syncProjectFromRoute(projectIdFromRoute)
    }, [currentProjectId, projectIdFromRoute, syncProjectFromRoute])

    useEffect(() => {
        // Dashboard can be entered after login while the store still contains
        // an anonymous-session cache from an earlier visit. Refresh options on
        // page entry so the list reflects the current account's permissions.
        void fetchProjectOptions(true)
    }, [fetchProjectOptions])

    useEffect(() => {
        const onAuthChange = () => {
            const s = useProjectStore.getState()
            s.resetProjectData()
            void s.fetchProjectOptions(true)
        }
        window.addEventListener("eco-auth-change", onAuthChange)
        return () => window.removeEventListener("eco-auth-change", onAuthChange)
    }, [])

    /** 拆解查询串，避免整份 searchParams 引用变化导致 effect 无意义地重跑 */
    const tabParam = searchParams.get("tab")
    const collectionParam = searchParams.get("collection")
    const dataNavParam = searchParams.get("dataNav")

    const stripMediaUrlOnceReadyRef = useRef(false)
    /** 每个 projectId 仅做一次 URL → Tab（刷新 / 换项目）；同一项目内勿反复用旧 tabParam 覆盖用户点击 */
    const tabUrlHydratedForProjectRef = useRef<number | null>(null)
    /** URL → store 的 Tab 已 dispatch，等待 activeTab 跟上后再写回 URL */
    const tabPendingFromUrlRef = useRef<TabName | null>(null)
    /** 每个项目仅做一次「URL → store」的 collection 还原（刷新），避免与 persist / 用户切换打架 */
    const collectionHydratedForProjectRef = useRef<Record<number, boolean>>({})
    /** URL → store 的 collection 已 dispatch，等待 currentCollectionId 跟上后再写回 URL */
    const collectionPendingFromUrlRef = useRef<number | "" | null>(null)

    /** 录音详情路径强制 Media Tab */
    useLayoutEffect(() => {
        if (!hasMediaDetailInUrl) return
        if (activeTab !== "media") setActiveTab("media")
    }, [hasMediaDetailInUrl, activeTab, setActiveTab])

    /**
     * 仅从 URL 恢复 Tab：在「进入某个 projectId」时做一次（含刷新、面包屑换项目）。
     * 同一项目内后续 Tab 由用户 / persist 驱动；切勿在每次 tabParam 未跟上时用旧 URL 覆盖 activeTab，
     * 否则 useLayoutEffect 早于 persist 执行会把刚点的 Tab 立刻改回去。
     */
    useLayoutEffect(() => {
        if (hasMediaDetailInUrl) return
        if (!Number.isFinite(projectIdFromRoute)) return

        if (tabUrlHydratedForProjectRef.current === projectIdFromRoute) return

        tabUrlHydratedForProjectRef.current = projectIdFromRoute
        const fromUrl = parseTabParam(tabParam)
        if (fromUrl) {
            tabPendingFromUrlRef.current = fromUrl
            setActiveTab(fromUrl)
        }
        /** 不把 tabParam 放进依赖：persist 更新查询串时不应再次触发本 effect */
    }, [hasMediaDetailInUrl, projectIdFromRoute, setActiveTab, tabParam])

    /**
     * 集合 options 就绪后，仅从地址栏恢复一次 collection（刷新场景）。
     * 放在 persist 的 useEffect 之前声明：React 会先执行全部 useLayoutEffect，再执行 useEffect。
     */
    useLayoutEffect(() => {
        if (!Number.isFinite(projectIdFromRoute)) return
        if (collectionOptions.length === 0) return
        if (collectionHydratedForProjectRef.current[projectIdFromRoute]) return

        const raw = new URLSearchParams(window.location.search).get("collection")
        if (raw !== null) {
            const resolved = parseCollectionParamForRestore(raw, collectionOptions)
            if (resolved !== undefined) {
                collectionPendingFromUrlRef.current = resolved
                selectCollection(resolved)
            }
        }
        collectionHydratedForProjectRef.current[projectIdFromRoute] = true
    }, [projectIdFromRoute, collectionOptions, selectCollection])

    useEffect(() => {
        if (!mediaIdParam) stripMediaUrlOnceReadyRef.current = false
    }, [mediaIdParam])

    /** 用户从详情顶栏切换到其他 Tab 时，去掉 URL 中的 /media/:id，保留查询参数 */
    useEffect(() => {
        if (!projectRouteId || !mediaIdParam) return
        if (activeTab === "media") {
            stripMediaUrlOnceReadyRef.current = true
            return
        }
        if (!stripMediaUrlOnceReadyRef.current) return
        const leaveSearch = new URLSearchParams(window.location.search)
        leaveSearch.set("tab", activeTab)
        if (collectionParam) leaveSearch.set("collection", collectionParam)
        else leaveSearch.delete("collection")
        if (activeTab === "data" && dataNavParam) leaveSearch.set("dataNav", dataNavParam)
        else leaveSearch.delete("dataNav")
        navigate(
            {
                pathname: `/dashboard/${projectRouteId}`,
                search: leaveSearch.toString(),
            },
            { replace: true },
        )
    }, [activeTab, projectRouteId, mediaIdParam, navigate, collectionParam, dataNavParam])

    /** /dashboard 无项目 id 时，在 store 就绪后带上查询串跳到 /dashboard/:id（刷新保留 tab 等） */
    useEffect(() => {
        if (Number.isFinite(projectIdFromRoute)) return
        const pid = currentProjectId
        if (pid == null || pid === "") return
        const search = window.location.search
        navigate(`/dashboard/${pid}${search}`, { replace: true })
    }, [projectIdFromRoute, currentProjectId, navigate])

    /** 集合列表未就绪时不写 URL，避免 collection 缺失与 ?collection=all 无限交替 */
    useEffect(() => {
        if (!Number.isFinite(projectIdFromRoute)) return
        if (collectionOptions.length === 0) return

        if (tabPendingFromUrlRef.current != null) {
            if (activeTab !== tabPendingFromUrlRef.current) return
            tabPendingFromUrlRef.current = null
        }

        if (collectionPendingFromUrlRef.current !== null) {
            if (String(currentCollectionId ?? "") !== String(collectionPendingFromUrlRef.current)) return
            collectionPendingFromUrlRef.current = null
        }

        const tabWant = hasMediaDetailInUrl ? "media" : activeTab
        const dataNavKeep =
            !hasMediaDetailInUrl && activeTab === "data" ? dataNavParam : null

        const next = new URLSearchParams(window.location.search)
        next.set("tab", tabWant)
        const colStr = collectionToSearchParam(currentCollectionId) ?? "all"
        next.set("collection", colStr)
        if (dataNavKeep) {
            next.set("dataNav", dataNavKeep)
        } else {
            next.delete("dataNav")
        }

        const same = next.toString() === new URLSearchParams(window.location.search).toString()
        if (same) return

        setSearchParams(next, { replace: true })
    }, [
        activeTab,
        currentCollectionId,
        projectIdFromRoute,
        hasMediaDetailInUrl,
        dataNavParam,
        tabParam,
        collectionParam,
        setSearchParams,
        collectionOptions.length,
    ])

    const ActiveComponent = TAB_COMPONENTS[activeTab] ?? DescriptionTab

    return (
        <div className="project-page">
            <ProjectNavBar />
            <div
                className={
                    showMediaDetail
                        ? "content-wrapper content-wrapper--media-detail"
                        : "content-wrapper"
                }
            >
                <div id={activeTab === "map" ? "tab-map" : undefined} className="tab-page active" key={activeTab}>
                    {showMediaDetail ? (
                        <div className="dashboard-card" style={{ height: "100%" }}>
                            <MediaDetailView mediaId={mediaIdFromRoute} />
                        </div>
                    ) : (
                        <ActiveComponent />
                    )}
                </div>
            </div>
        </div>
    )
}
