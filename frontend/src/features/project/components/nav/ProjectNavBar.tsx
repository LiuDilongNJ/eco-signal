import { Button as ESButton } from "@/components/ui"
/**
 * ProjectNavBar - 项目页顶部导航栏
 *
 * 包含: Logo + 面包屑选择器 | Tab 切换器 | 主题切换 + 用户菜单
 */

import { Link, useParams, useNavigate, useSearchParams } from "react-router-dom"
import { useState, useEffect, useMemo, useRef, useCallback } from "react"
import { Moon, Sun, Info, ChevronDown } from "lucide-react"
import { SearchableDropdown } from "./SearchableDropdown"
import { TabSwitcher } from "./TabSwitcher"
import { UserMenu } from "./UserMenu"
import { StableText } from "@/components/ui"
import { NAV_BAR_ICON_SIZE } from "./navBarIconSize"
import { useProjectStore } from "../../stores/useProjectStore"
import { useTabStore } from "../../stores/useTabStore"
import { useAppStore } from "@/store/useAppStore"
import { usersApi } from "../../../../api/endpoints/users"
import { mediaApi } from "../../../../api/endpoints/media"
import { authUtils } from "@/utils/auth"
import {
    buildMediaNavItems,
    pickPreferredMedia,
    type MediaNavItem,
} from "./mediaNavigation"

export function ProjectNavBar() {
    const { id: routeProjectId, mediaId: routeMediaId } = useParams<{ id?: string; mediaId?: string }>()
    const navigate = useNavigate()
    const [searchParams] = useSearchParams()
    const isMediaDetailRoute = routeMediaId != null && String(routeMediaId).trim() !== ""
    const setActiveTab = useTabStore((s) => s.setActiveTab)

    const {
        currentProjectId,
        currentCollectionId,
        projectSearchQuery,
        collectionSearchQuery,
        filteredProjects,
        filteredCollections,
        selectProject,
        selectCollection,
        setProjectSearch,
        setCollectionSearch,
        collectionOptions,
    } = useProjectStore()

    const currentProjectFn = useProjectStore((s) => s.currentProject)

    const { effectiveTheme, toggleTheme } = useAppStore()

    const [meIsAdmin, setMeIsAdmin] = useState(false)
    const [meFetchGen, setMeFetchGen] = useState(0)

    /** 媒体详情顶栏：当前项目和集合下的媒体列表（GET /v1/media-options） */
    const [mediaNavItems, setMediaNavItems] = useState<MediaNavItem[]>([])
    const [mediaNavSearch, setMediaNavSearch] = useState("")
    const preferredMediaTypeRef = useRef<string | null>(null)
    const pendingNavCollectionIdRef = useRef<number | null>(null)
    const mediaNavItemsCollectionIdRef = useRef<number | null>(null)
    const [mobileCrumbOpen, setMobileCrumbOpen] = useState(false)
    const leftCapsuleRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const onAuth = () => setMeFetchGen((n) => n + 1)
        window.addEventListener("eco-auth-change", onAuth)
        return () => window.removeEventListener("eco-auth-change", onAuth)
    }, [])

    useEffect(() => {
        const token = authUtils.getToken()
        if (!token) {
            setMeIsAdmin(false)
            return
        }
        let cancelled = false
        ;(async () => {
            try {
                const res = await usersApi.getMe({ ignoreUnauthorized: true })
                if (cancelled) return
                if ((res.code === 0 || res.code === 200) && res.data) {
                    setMeIsAdmin(!!res.data.is_admin)
                } else {
                    setMeIsAdmin(false)
                }
            } catch {
                if (!cancelled) setMeIsAdmin(false)
            }
        })()
        return () => {
            cancelled = true
        }
    }, [meFetchGen])

    const proj = currentProjectFn()
    const isProjectManagerContext = !!proj?.can_manage && !meIsAdmin

    const suppressProjectRowTags = meIsAdmin
    const suppressCollectionRowTags = meIsAdmin || isProjectManagerContext

    const projectRoleBanner = meIsAdmin ? "Administrator" : null
    const collectionRoleBanner = meIsAdmin
        ? "Administrator"
        : isProjectManagerContext
          ? "Project manage"
          : null

    const projectItems = filteredProjects().map((p: any) => ({
        id: p.id,
        label: p.name,
        tag: !suppressProjectRowTags && p.can_manage ? "MANAGE" : undefined,
    }))
    const collectionItems = filteredCollections()
        .filter((c: any) => !(isMediaDetailRoute && c.id === ""))
        .map((c: any) => ({
            id: c.id,
            label: c.name,
            tag: !suppressCollectionRowTags && c.can_manage ? "MANAGE" : undefined,
        }))
    
    const hasCollections = collectionOptions.length > 1

    const projectIdForMediaOptions = useMemo(() => {
        if (routeProjectId != null && String(routeProjectId).trim() !== "") {
            const n = Number(routeProjectId)
            return Number.isFinite(n) ? n : NaN
        }
        if (currentProjectId != null && currentProjectId !== "") {
            const n = Number(currentProjectId)
            return Number.isFinite(n) ? n : NaN
        }
        return NaN
    }, [routeProjectId, currentProjectId])

    const collectionIdForMediaOptions = useMemo(() => {
        const c = currentCollectionId
        if (c == null || c === "") return undefined
        const n = Number(c)
        return Number.isFinite(n) ? n : undefined
    }, [currentCollectionId])

    useEffect(() => {
        if (!isMediaDetailRoute || !Number.isFinite(projectIdForMediaOptions)) {
            setMediaNavItems([])
            mediaNavItemsCollectionIdRef.current = null
            return
        }
        let cancelled = false
        ;(async () => {
            try {
                const rows = await mediaApi.getMediaOptions({
                    project_id: projectIdForMediaOptions,
                    collection_id: collectionIdForMediaOptions,
                }, true)
                if (cancelled) return
                const items = buildMediaNavItems(rows)
                const currentItem = items.find((item) => Number(item.id) === Number(routeMediaId))
                if (currentItem) preferredMediaTypeRef.current = currentItem.mediaType
                setMediaNavItems(items)
                mediaNavItemsCollectionIdRef.current = collectionIdForMediaOptions ?? null
            } catch {
                if (!cancelled) {
                    setMediaNavItems([])
                    mediaNavItemsCollectionIdRef.current = collectionIdForMediaOptions ?? null
                }
            }
        })()
        return () => {
            cancelled = true
        }
    }, [isMediaDetailRoute, projectIdForMediaOptions, collectionIdForMediaOptions, routeMediaId])

    useEffect(() => {
        if (!isMediaDetailRoute) setMediaNavSearch("")
    }, [isMediaDetailRoute])

    useEffect(() => {
        const onDocClick = (e: MouseEvent) => {
            const target = e.target as Node | null
            if (!target) return
            if (leftCapsuleRef.current?.contains(target)) return
            setMobileCrumbOpen(false)
        }
        document.addEventListener("click", onDocClick)
        return () => document.removeEventListener("click", onDocClick)
    }, [])

    const currentMediaNavType = useMemo(() => {
        const current = mediaNavItems.find((item) => Number(item.id) === Number(routeMediaId))
        return current?.mediaType ?? preferredMediaTypeRef.current ?? null
    }, [mediaNavItems, routeMediaId])

    const filteredMediaNavItems = useMemo(() => {
        const q = mediaNavSearch.trim().toLowerCase()
        const sameTypeItems = currentMediaNavType
            ? mediaNavItems.filter((item) => item.mediaType === currentMediaNavType)
            : mediaNavItems
        if (!q) return sameTypeItems.map((i) => ({ id: i.id, label: i.label }))
        return sameTypeItems
            .filter((i) => i.label.toLowerCase().includes(q))
            .map((i) => ({ id: i.id, label: i.label }))
    }, [currentMediaNavType, mediaNavItems, mediaNavSearch])

    const selectedMediaNavId =
        routeMediaId != null && String(routeMediaId).trim() !== ""
            ? Number(routeMediaId)
            : null

    const projectSegmentForNavigate =
        routeProjectId != null && String(routeProjectId).trim() !== ""
            ? String(routeProjectId)
            : currentProjectId != null && currentProjectId !== ""
              ? String(currentProjectId)
              : null

    const selectedProjectLabel =
        projectItems.find((p) => String(p.id) === String(currentProjectId))?.label ?? "Project"
    const selectedCollectionLabel =
        collectionItems.find((c) => String(c.id) === String(currentCollectionId))?.label ?? "Collection"

    const goToDashboardMedia = useCallback(() => {
        setActiveTab("media")
        navigate("/dashboard", { replace: true })
    }, [navigate, setActiveTab])

    /** 媒体详情顶栏：切换项目后进入首个集合，并优先保持当前媒体类型。 */
    const handleProjectSelectFromMediaDetail = useCallback(
        async (id: number | string) => {
            const pid = Number(id)
            if (!Number.isFinite(pid)) return
            const preferredMediaType = preferredMediaTypeRef.current

            pendingNavCollectionIdRef.current = null
            mediaNavItemsCollectionIdRef.current = null
            setMediaNavItems([])

            navigate(`/dashboard/${pid}`, { replace: true })

            await selectProject(id)
            const opts = useProjectStore.getState().collectionOptions
            const concrete = opts.filter((c: { id: unknown }) => String(c.id) !== "")
            if (concrete.length === 0) {
                goToDashboardMedia()
                return
            }
            const firstCol = concrete[0] as { id: number | string }
            selectCollection(firstCol.id)
            try {
                const rows = await mediaApi.getMediaOptions({
                    project_id: pid,
                    collection_id: Number(firstCol.id),
                }, true)
                const target = pickPreferredMedia(buildMediaNavItems(rows), preferredMediaType)
                if (!target) {
                    goToDashboardMedia()
                    return
                }
                preferredMediaTypeRef.current = target.mediaType
                navigate(`/dashboard/${pid}/media/${target.id}`, { replace: true })
            } catch {
                goToDashboardMedia()
            }
        },
        [goToDashboardMedia, navigate, selectCollection, selectProject],
    )

    // 用户手动切换 Collection 后，等待新列表返回，再优先跳到同类型媒体。
    useEffect(() => {
        if (!isMediaDetailRoute || !projectSegmentForNavigate) return
        const pendingCid = pendingNavCollectionIdRef.current
        if (pendingCid == null) return

        // 等列表确实按该 collection 拉回来了，避免竞态
        if (mediaNavItemsCollectionIdRef.current !== pendingCid) return
        if (mediaNavItems.length === 0) {
            pendingNavCollectionIdRef.current = null
            goToDashboardMedia()
            return
        }

        const target = pickPreferredMedia(mediaNavItems, preferredMediaTypeRef.current)
        if (!target) return
        pendingNavCollectionIdRef.current = null
        preferredMediaTypeRef.current = target.mediaType

        if (selectedMediaNavId != null && String(selectedMediaNavId) === String(target.id)) return
        navigate(`/dashboard/${projectSegmentForNavigate}/media/${target.id}`)
    }, [
        goToDashboardMedia,
        isMediaDetailRoute,
        mediaNavItems,
        navigate,
        projectSegmentForNavigate,
        selectedMediaNavId,
    ])

    useEffect(() => {
        if (!isMediaDetailRoute || !projectSegmentForNavigate) return
        if (pendingNavCollectionIdRef.current != null) return
        // 列表还没切到当前 collection 的结果时不要兜底跳转，否则会用“旧集合列表”把路由跳回去
        if (mediaNavItemsCollectionIdRef.current !== collectionIdForMediaOptions) return
        if (mediaNavItems.length === 0) {
            goToDashboardMedia()
            return
        }

        const hasCurrentMedia =
            selectedMediaNavId != null &&
            mediaNavItems.some((item) => String(item.id) === String(selectedMediaNavId))

        if (hasCurrentMedia) return

        const target = pickPreferredMedia(mediaNavItems, preferredMediaTypeRef.current)
        if (!target) return

        preferredMediaTypeRef.current = target.mediaType
        navigate(`/dashboard/${projectSegmentForNavigate}/media/${target.id}`, { replace: true })
    }, [
        collectionIdForMediaOptions,
        goToDashboardMedia,
        isMediaDetailRoute,
        mediaNavItems,
        navigate,
        projectSegmentForNavigate,
        selectedMediaNavId,
    ])


    return (
        <nav className="project-nav-bar">
            {/* 左侧: Logo + 面包屑 */}
            <div className="nav-left">
                <div className="nav-capsule-box" ref={leftCapsuleRef}>
                    <Link className="nav-logo" to="/">
                        <div className="logo-icon-box">
                            <img src="/images/biosounds_logo_small.png" alt="" aria-hidden="true" />
                        </div>
                        <StableText className="nav-logo-text">ecoSound-web</StableText>
                    </Link>
                    <div className="nav-divider" />
                    <ESButton appearance="unstyled"
                        type="button"
                        className="nav-mobile-crumb-toggle"
                        onClick={() => setMobileCrumbOpen((v) => !v)}
                    >
                        <StableText className="nav-mobile-crumb-label">
                            {`${selectedProjectLabel} / ${selectedCollectionLabel}`}
                        </StableText>
                        <ChevronDown size={14} />
                    </ESButton>
                    <div className={`breadcrumb-group ${mobileCrumbOpen ? "mobile-open" : ""}`}>
                        <SearchableDropdown
                            items={projectItems}
                            selectedId={currentProjectId}
                            onSelect={(id) => {
                                if (isMediaDetailRoute) {
                                    void handleProjectSelectFromMediaDetail(id)
                                } else {
                                    const pid = Number(id)
                                    if (!Number.isFinite(pid)) return
                                    navigate(`/dashboard/${pid}?${searchParams.toString()}`, {
                                        replace: true,
                                    })
                                }
                            }}
                            onSearch={setProjectSearch}
                            searchQuery={projectSearchQuery}
                            label="Project"
                            roleBanner={projectRoleBanner}
                        />
                        <span className="crumb-separator">/</span>
                        <SearchableDropdown
                            items={collectionItems}
                            selectedId={currentCollectionId}
                            onSelect={(id) => {
                                selectCollection(id)
                                setMobileCrumbOpen(false)
                                if (!isMediaDetailRoute) return
                                setMediaNavItems([])
                                mediaNavItemsCollectionIdRef.current = null
                                const cidNum = id != null && id !== "" ? Number(id) : NaN
                                pendingNavCollectionIdRef.current = Number.isFinite(cidNum) ? cidNum : null
                            }}
                            onSearch={setCollectionSearch}
                            searchQuery={collectionSearchQuery}
                            label="Collection"
                            roleBanner={collectionRoleBanner}
                            disabled={!hasCollections}
                            customLabel={!hasCollections ? "No Data" : undefined}
                        />
                        {isMediaDetailRoute ? (
                            <>
                                <span className="crumb-separator">/</span>
                                <SearchableDropdown
                                    items={filteredMediaNavItems}
                                    selectedId={selectedMediaNavId}
                                    onSelect={(id) => {
                                        const mid = Number(id)
                                        if (!Number.isFinite(mid) || !projectSegmentForNavigate) return
                                        const selected = mediaNavItems.find((item) => item.id === mid)
                                        if (selected) preferredMediaTypeRef.current = selected.mediaType
                                        setMobileCrumbOpen(false)
                                        navigate(`/dashboard/${projectSegmentForNavigate}/media/${mid}`)
                                    }}
                                    onSearch={setMediaNavSearch}
                                    searchQuery={mediaNavSearch}
                                    label="Media"
                                    roleBanner={null}
                                />
                            </>
                        ) : null}
                    </div>
                </div>
            </div>

            {/* 中间: Tab 切换 */}
            {isMediaDetailRoute ? null : <TabSwitcher />}

            {/* 右侧: 工具栏 */}
            <div className="nav-right">
                <div className="nav-capsule-box">
                    <ESButton appearance="unstyled"
                        className="nav-btn-simple"
                        onClick={toggleTheme}
                        title="Switch Theme"
                    >
                        {effectiveTheme === "dark" ? <Sun size={NAV_BAR_ICON_SIZE} /> : <Moon size={NAV_BAR_ICON_SIZE} />}
                    </ESButton>
                    <div className="nav-divider" />
                    <ESButton appearance="unstyled" className="nav-btn-simple" title="Information">
                        <Info size={NAV_BAR_ICON_SIZE} />
                    </ESButton>
                    <div className="nav-divider" />
                    <UserMenu />
                </div>
            </div>
        </nav>
    )
}
