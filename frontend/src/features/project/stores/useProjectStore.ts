/**
 * Project Store - 项目与 Collection 选择状态
 */

import { create } from "zustand"
import type { Collection } from "../types"
import { projectsApi } from "../../../api/endpoints/projects"
import { applySphereTheme } from "../sphereTheme"
import type { DataNavFilter } from "../components/data/DataPageLayout"

/** 统一项目 ID 类型，避免表格 Key（常为 string）与选项 id（常为 number）严格相等失败 */
function normalizeProjectId(id: number | string): number | string {
    if (typeof id === "number" && Number.isFinite(id)) return id
    if (typeof id === "string" && id.trim() !== "") {
        const n = Number(id)
        if (!Number.isNaN(n) && Number.isFinite(n)) return n
    }
    return id
}

interface ProjectOptionItem {
    id: number | string
    name: string
    can_manage?: boolean
}

interface ProjectState {
    /** 所有项目列表 */
    projects: ProjectOptionItem[]
    /** 当前选中的项目 ID */
    currentProjectId: number | string | null
    /** 当前选中的 Collection ID */
    currentCollectionId: number | string | null
    /** 项目搜索关键词 */
    projectSearchQuery: string
    /** Collection 搜索关键词 */
    collectionSearchQuery: string
    /** 数据加载状态 */
    loadingProjects: boolean
    loadingCollections: boolean

    /** 所选项目的 Collection 选项 */
    collectionOptions: any[]

    // ---- Derived ----
    /** 当前项目 */
    currentProject: () => ProjectOptionItem | undefined
    /** 当前 Collection */
    currentCollection: () => Collection | undefined
    /** 过滤后的项目列表 */
    filteredProjects: () => ProjectOptionItem[]
    /** 过滤后的 Collection 列表 */
    filteredCollections: () => Collection[]

    // ---- Actions ----
    selectProject: (id: number | string) => Promise<void>
    syncProjectFromRoute: (id: number | string) => Promise<void>
    selectCollection: (id: number | string) => void
    setProjectSearch: (query: string) => void
    setCollectionSearch: (query: string) => void
    fetchProjectOptions: (force?: boolean) => Promise<void>
    fetchCollectionOptions: (projectId: number | string) => Promise<void>
    /** 从表格等来源合并一条项目进 options，保证顶栏能显示名称 */
    upsertProjectOption: (p: { id: number | string; name: string }) => void
    /** 切换账号后清空本地项目/Collection 缓存 */
    resetProjectData: () => void

    /** 从 Timeline 等跳转到 Data → Audios 并打开指定媒体编辑 */
    dataTabTargetNavKey: string | null
    dataMenuRefreshVersion: number
    pendingAudioDetailMediaId: number | null
    dataPageNavFilters: Partial<Record<"project" | "collection" | "user", DataNavFilter>>
    navigateToAudioDetail: (mediaId: number) => void
    requestDataMenuRefresh: () => void
    setDataPageNavFilter: (key: "project" | "collection" | "user", value: DataNavFilter) => void
    clearDataTabTargetNavKey: () => void
    clearPendingAudioDetailMediaId: () => void
}

export const useProjectStore = create<ProjectState>()((set, get) => ({
    projects: [],
    currentProjectId: null,
    currentCollectionId: null,
    projectSearchQuery: "",
    collectionSearchQuery: "",
    loadingProjects: false,
    loadingCollections: false,
    collectionOptions: [],
    dataTabTargetNavKey: null,
    dataMenuRefreshVersion: 0,
    pendingAudioDetailMediaId: null,
    dataPageNavFilters: {},

    navigateToAudioDetail: (mediaId: number) => {
        set({ dataTabTargetNavKey: "audio", pendingAudioDetailMediaId: mediaId })
    },

    requestDataMenuRefresh: () => set((state) => ({ dataMenuRefreshVersion: state.dataMenuRefreshVersion + 1 })),

    setDataPageNavFilter: (key, value) => set((state) => ({
        dataPageNavFilters: { ...state.dataPageNavFilters, [key]: value },
    })),

    clearDataTabTargetNavKey: () => set({ dataTabTargetNavKey: null }),

    clearPendingAudioDetailMediaId: () => set({ pendingAudioDetailMediaId: null }),

    currentProject: () => {
        const { projects, currentProjectId } = get()
        if (currentProjectId === null || currentProjectId === undefined) return undefined
        return projects.find((p) => String(p.id) === String(currentProjectId))
    },

    currentCollection: () => {
        const { collectionOptions, currentCollectionId } = get()
        // currentCollectionId==="" 表示 ALL Collections（有效值），不应被当成未选择
        if (currentCollectionId == null) return undefined
        return collectionOptions.find((c) => String(c.id) === String(currentCollectionId))
    },

    filteredProjects: () => {
        const { projects, projectSearchQuery } = get()
        if (!projectSearchQuery) return projects
        const q = projectSearchQuery.toLowerCase()
        return projects.filter((p) => p.name.toLowerCase().includes(q))
    },

    filteredCollections: () => {
        const { collectionOptions, collectionSearchQuery } = get()
        if (!collectionSearchQuery) return collectionOptions
        const q = collectionSearchQuery.toLowerCase()
        return collectionOptions.filter((c) => c.name.toLowerCase().includes(q))
    },

    selectProject: async (id) => {
        const pid = normalizeProjectId(id)
        set({
            currentProjectId: pid,
            currentCollectionId: null,
            collectionSearchQuery: "",
            collectionOptions: [],
            pendingAudioDetailMediaId: null,
            dataTabTargetNavKey: null,
            dataMenuRefreshVersion: 0,
            dataPageNavFilters: {},
        })
        // Reset sphere theme when changing project
        applySphereTheme(null)
        await get().fetchCollectionOptions(pid)
    },

    syncProjectFromRoute: async (id) => {
        const pid = normalizeProjectId(id)
        const { currentProjectId } = get()
        if (String(currentProjectId ?? "") === String(pid)) return
        set({
            currentProjectId: pid,
            currentCollectionId: null,
            collectionSearchQuery: "",
            collectionOptions: [],
            pendingAudioDetailMediaId: null,
            dataTabTargetNavKey: null,
            dataMenuRefreshVersion: 0,
            dataPageNavFilters: {},
        })
        applySphereTheme(null)
        await get().fetchCollectionOptions(pid)
    },

    upsertProjectOption: (p) => {
        const pid = normalizeProjectId(p.id)
        set((state) => {
            const idx = state.projects.findIndex((x) => String(x.id) === String(pid))
            if (idx >= 0) {
                const prev = state.projects[idx]
                if (!prev) {
                    return { projects: state.projects }
                }
                const merged: ProjectOptionItem = {
                    id: prev.id,
                    name: p.name,
                    can_manage: prev.can_manage,
                }
                return {
                    projects: state.projects.map((x, i) => (i === idx ? merged : x)),
                }
            }
            const created: ProjectOptionItem = {
                id: pid,
                name: p.name,
            }
            return { projects: [...state.projects, created] }
        })
    },

    selectCollection: (id) => {
        set({ currentCollectionId: id })
        // Apply sphere theme for the selected collection
        const { collectionOptions } = get()
        const col = collectionOptions.find((c: any) => c.id === id || String(c.id) === String(id))
        applySphereTheme(col?.sphere || null)
    },

    setProjectSearch: (query) => set({ projectSearchQuery: query }),

    setCollectionSearch: (query) => set({ collectionSearchQuery: query }),

    resetProjectData: () => {
        applySphereTheme(null)
        set({
            projects: [],
            currentProjectId: null,
            currentCollectionId: null,
            collectionOptions: [],
            projectSearchQuery: "",
            collectionSearchQuery: "",
            dataMenuRefreshVersion: 0,
            dataPageNavFilters: {},
        })
    },

    fetchProjectOptions: async (force = false) => {
        if (get().loadingProjects) return
        if (!force && get().projects.length > 0) return

        set({ loadingProjects: true })
        try {
            const res = await projectsApi.getProjectOptions(true)
            if (res.code === 0 || res.code === 200) {
                const mappedProjects: ProjectOptionItem[] = (res.data || []).map((opt: any, idx: number) => ({
                    id: opt.project_id ?? opt.id ?? idx,
                    name: opt.name,
                    can_manage: opt.can_manage,
                }))

                set({ projects: mappedProjects })

                // Only fall back to the first option when the route has not already
                // established a project context.
                const { currentProjectId, fetchCollectionOptions } = get()
                if (!currentProjectId && mappedProjects.length > 0) {
                    const firstId = mappedProjects[0]?.id
                    if (firstId !== undefined) {
                        set({ currentProjectId: firstId })
                        fetchCollectionOptions(firstId)
                    }
                }
            }
        } catch (error) {
            console.error("Failed to fetch project options:", error)
        } finally {
            set({ loadingProjects: false })
        }
    },

    fetchCollectionOptions: async (projectId: number | string) => {
        set({ loadingCollections: true })
        try {
            const { collectionsApi } = await import("../../../api/endpoints/collections")
            const res = await collectionsApi.getCollectionOptions(projectId, true)
            if (res.code === 0 || res.code === 200) {
                const options = (res.data || []).map((opt: any, idx: number) => ({
                    id: opt.id ?? opt.collection_id ?? idx,
                    name: opt.name,
                    ...opt
                }))

                // ADD "ALL Collections" at the beginning
                options.unshift({ id: "", name: "ALL Collections" })
                set({ collectionOptions: options })

                const { currentCollectionId } = get()
                // 只在「完全未选择」时设置默认值；不要因为 currentCollectionId==="" 而反复覆写触发跳转
                if (currentCollectionId == null && options.length > 0) {
                    set({ currentCollectionId: options[0].id }) // Defaults to ""
                } else if (currentCollectionId != null) {
                    // 如果当前选中的 collection 不在新 options 内（比如项目切换/权限变化），回退到 ALL
                    const exists = options.some((c: any) => String(c.id) === String(currentCollectionId))
                    if (!exists && options.length > 0) {
                        set({ currentCollectionId: options[0].id })
                    }
                }
            }
        } catch (error) {
            console.error("Failed to fetch collection options:", error)
        } finally {
            set({ loadingCollections: false })
        }
    },
}))
