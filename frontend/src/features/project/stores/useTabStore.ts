/**
 * Tab Store - 当前活跃 Tab 状态
 */

import { create } from "zustand"
import type { TabName } from "../types"

interface TabState {
    activeTab: TabName
    setActiveTab: (tab: TabName) => void
}

function getInitialTab(): TabName {
    if (typeof window !== "undefined") {
        if (window.location.pathname.includes("/media/")) {
            return "media"
        }
        const tab = new URLSearchParams(window.location.search).get("tab")
        if (
            tab === "desc" ||
            tab === "summary" ||
            tab === "media" ||
            tab === "map" ||
            tab === "timeline" ||
            tab === "data"
        ) {
            return tab as TabName
        }
    }
    return "desc"
}

export const useTabStore = create<TabState>()((set) => ({
    activeTab: getInitialTab(),
    setActiveTab: (tab) => set({ activeTab: tab }),
}))
