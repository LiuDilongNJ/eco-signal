import { useLayoutEffect, useMemo, useState } from "react"
import { theme as antdTheme } from "@/components/ui"
import { createEcoSignalAntdTheme } from "@/styles/antdTheme"

import { useProjectStore } from "../stores/useProjectStore"
import { getRealmTheme } from "../sphereTheme"

/** Default ecoSignal brand used when a surface intentionally opts out of project theming. */
export const APP_DEFAULT_BRAND = "#83cd20"

export function createAntdBrandTheme(isDark: boolean, brandPrimary: string) {
    const baseTheme = createEcoSignalAntdTheme(isDark, brandPrimary)
    return {
        ...baseTheme,
        algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        token: {
            ...baseTheme.token,
            colorPrimary: brandPrimary,
            colorLink: brandPrimary,
            colorInfo: brandPrimary,
            colorBorder: "var(--border-color)",
            colorBgElevated: "var(--bg-surface)",
            colorBgContainer: "var(--bg-surface)",
            controlOutline: "transparent",
            controlOutlineWidth: 0,
        },
        components: {
            ...baseTheme.components,
            Select: {
                selectorBg: "var(--bg-surface-secondary)",
                colorBgContainer: "var(--bg-surface-secondary)",
                activeBorderColor: brandPrimary,
                hoverBorderColor: brandPrimary,
                activeOutlineColor: "var(--brand-tint)",
                optionActiveBg: isDark ? "rgba(255, 255, 255, 0.08)" : "var(--brand-tint)",
                optionSelectedBg: "rgba(var(--brand-rgb), 0.18)",
                optionSelectedColor: "var(--text-main)",
            },
            Input: {
                colorBgContainer: "var(--bg-surface-secondary)",
                activeBorderColor: brandPrimary,
                hoverBorderColor: brandPrimary,
                activeShadow: "0 0 0 2px var(--brand-tint)",
            },
            DatePicker: {
                colorBgContainer: "var(--bg-surface-secondary)",
                activeBorderColor: brandPrimary,
                hoverBorderColor: brandPrimary,
                activeShadow: "0 0 0 2px var(--brand-tint)",
            },
            Table: {
                headerBg: "var(--es-color-bg-subtle)",
                headerColor: "var(--es-color-text)",
                borderColor: "var(--es-color-border)",
                rowHoverBg: "var(--es-color-brand-soft)",
                stickyScrollBarBg: brandPrimary,
            },
            Button: {
                ...baseTheme.components?.Button,
                borderRadius: 6,
                borderRadiusLG: 8,
                borderRadiusSM: 4,
            },
            InputNumber: {
                colorBgContainer: "var(--bg-surface-secondary)",
                activeBorderColor: brandPrimary,
                hoverBorderColor: brandPrimary,
                activeShadow: "0 0 0 2px var(--brand-tint)",
            },
            Checkbox: {
                colorPrimary: brandPrimary,
                colorPrimaryHover: brandPrimary,
            },
            Radio: {
                colorPrimary: brandPrimary,
                colorPrimaryHover: brandPrimary,
            },
            Switch: {
                colorPrimary: brandPrimary,
                colorPrimaryHover: "var(--brand-hover)",
                handleShadow: "none",
            },
            Drawer: {
                colorBgElevated: "var(--bg-surface)",
            },
        },
    }
}

/** Fixed-brand Ant Design theme for surfaces that do not inherit the active project theme. */
export function useAppDefaultAntdBrandConfig(isDark: boolean) {
    return useMemo(() => createAntdBrandTheme(isDark, APP_DEFAULT_BRAND), [isDark])
}

/**
 * Ant Design ConfigProvider theme aligned with CSS `--brand` (select/checkbox/switch tokens).
 * Re-reads `--brand` when project/collection changes (applySphereTheme updates the root), not only on dark-mode toggle.
 */
export function useAntdBrandConfig(isDark: boolean, brandSource?: unknown) {
    const [brandPrimary, setBrandPrimary] = useState("var(--brand)")
    const currentProjectId = useProjectStore((s) => s.currentProjectId)
    const currentCollectionId = useProjectStore((s) => s.currentCollectionId)

    useLayoutEffect(() => {
        if (brandSource !== undefined) {
            setBrandPrimary(getRealmTheme(brandSource).brand)
            return
        }

        const raw = getComputedStyle(document.documentElement).getPropertyValue("--brand").trim()
        if (!raw) return
        if (raw.startsWith("#")) {
            setBrandPrimary(raw)
            return
        }
        const m = raw.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/)
        if (m) {
            const [r, g, b] = [Number(m[1]), Number(m[2]), Number(m[3])]
            const hex = `#${[r, g, b].map((x) => x.toString(16).padStart(2, "0")).join("")}`
            setBrandPrimary(hex)
        }
    }, [isDark, currentProjectId, currentCollectionId, brandSource])

    return useMemo(() => createAntdBrandTheme(isDark, brandPrimary), [isDark, brandPrimary])
}
