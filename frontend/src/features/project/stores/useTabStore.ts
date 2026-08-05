/**
 * Tab Store - 当前活跃 Tab 状态
 */

import { create } from "zustand"
import type { TabName } from "../types"

interface TabState {
    activeTab: TabName
    setActiveTab: (tab: TabName) => void
}

export const useTabStore = create<TabState>()((set) => ({
    activeTab: "desc",
    setActiveTab: (tab) => set({ activeTab: tab }),
}))
