/**
 * Sphere Theme Configuration
 * Each sphere maps to a unique brand color palette.
 */

import type { CSSProperties } from "react"
import { SPHERE_COLORS } from "./data/constants"

/** 内部辅助：安全地进行字符串规范化，防止非字符串输入导致 .trim() 崩溃 */
function normalizeKey(val: unknown): string {
    if (typeof val !== "string") return ""
    return val.trim().toLowerCase()
}

export interface SphereTheme {
    brand: string
    brandRgb: string
    brandHover: string
}

export const SPHERE_THEMES: Record<string, SphereTheme> = {
    hydrosphere: {
        brand: "#3b82f6",       // blue (Freshwater)
        brandRgb: "59, 130, 246",
        brandHover: "#2563eb",
    },
    marinesphere: {
        brand: "#06b6d4",       // cyan (Marine)
        brandRgb: "6, 182, 212",
        brandHover: "#0891b2",
    },
    lithosphere: {
        brand: "#a855f7",       // purple (Subterranean)
        brandRgb: "168, 85, 247",
        brandHover: "#9333ea",
    },
    atmosphere: {
        brand: "#f97316",       // orange (Atmospheric)
        brandRgb: "249, 115, 22",
        brandHover: "#ea580c",
    },
    biosphere: {
        brand: "#22c55e",       // green (Terrestrial)
        brandRgb: "34, 197, 94",
        brandHover: "#16a34a",
    },
    anthroposphere: {
        brand: "#ec4899",       // pink (Anthroposphere)
        brandRgb: "236, 72, 153",
        brandHover: "#db2777",
    },
    "terrestrial-freshwater": {
        brand: "#14b8a6",
        brandRgb: "20, 184, 166",
        brandHover: "#0d9488",
    },
    "freshwater-marine": {
        brand: "#0ea5e9",
        brandRgb: "14, 165, 233",
        brandHover: "#0284c7",
    },
    "marine-terrestrial": {
        brand: "#84cc16",
        brandRgb: "132, 204, 22",
        brandHover: "#65a30d",
    },
    "marine-freshwater-terrestrial": {
        brand: "#10b981",
        brandRgb: "16, 185, 129",
        brandHover: "#059669",
    },
    "subterranean-freshwater": {
        brand: "#6366f1",
        brandRgb: "99, 102, 241",
        brandHover: "#4f46e5",
    },
    "subterranean-marine": {
        brand: "#4f46e5",
        brandRgb: "79, 70, 229",
        brandHover: "#4338ca",
    },
    // Primary Realm aliases
    terrestrial: {
        brand: "#22c55e",
        brandRgb: "34, 197, 94",
        brandHover: "#16a34a",
    },
    subterranean: {
        brand: "#a855f7",
        brandRgb: "168, 85, 247",
        brandHover: "#9333ea",
    },
    freshwater: {
        brand: "#3b82f6",
        brandRgb: "59, 130, 246",
        brandHover: "#2563eb",
    },
    marine: {
        brand: "#06b6d4",
        brandRgb: "6, 182, 212",
        brandHover: "#0891b2",
    },
}

/** Default brand (no sphere selected) */
export const DEFAULT_SPHERE_THEME: SphereTheme = {
    brand: "#83CD20",
    brandRgb: "131, 205, 32",
    brandHover: "#72b51b",
}

/**
 * Apply sphere brand colors to the document root.
 * Pass undefined / null to reset to defaults.
 */
/**
 * 媒体标签 pill：颜色仅由「该条数据的 sphere」决定，不使用全局导航上的主题色 `--brand`。
 * 无 sphere 或未知枚举时用中性描边样式。
 */
export function getSphereTagPillStyle(sphere: unknown): CSSProperties {
    const key = normalizeKey(sphere)
    // Realm -> Sphere mapping
    const sphereKey = ({
        terrestrial: 'biosphere',
        freshwater: 'hydrosphere',
        marine: 'marinesphere',
        atmospheric: 'atmosphere',
        anthroposphere: 'anthroposphere',
        subterranean: 'lithosphere',
    } as Record<string, string>)[key] || key

    const t = sphereKey ? SPHERE_THEMES[sphereKey] : undefined
    if (t) {
        return {
            background: t.brand,
            color: "var(--text-invert)",
            border: "1px solid transparent",
            boxShadow: `0 2px 5px rgba(${t.brandRgb}, 0.25)`,
        }
    }
    return {
        background: "var(--bg-surface-secondary)",
        color: "var(--text-main)",
        border: "1px solid var(--border-color)",
        boxShadow: "none",
    }
}

export function getSphereAccentVars(sphere: unknown): CSSProperties {
    const key = normalizeKey(sphere)
    const sphereKey = ({
        terrestrial: 'biosphere',
        freshwater: 'hydrosphere',
        marine: 'marinesphere',
        atmospheric: 'atmosphere',
        anthroposphere: 'anthroposphere',
        subterranean: 'lithosphere',
    } as Record<string, string>)[key] || key

    const t = sphereKey ? SPHERE_THEMES[sphereKey] : undefined
    const theme = t ?? DEFAULT_SPHERE_THEME

    return {
        "--media-accent": theme.brand,
        "--media-accent-rgb": theme.brandRgb,
        "--media-accent-hover": theme.brandHover,
        "--media-accent-tint": `rgba(${theme.brandRgb}, 0.12)`,
    } as CSSProperties
}

export function applySphereTheme(sphere?: unknown) {
    const key = normalizeKey(sphere)
    const sphereKey = ({
        terrestrial: 'biosphere',
        freshwater: 'hydrosphere',
        marine: 'marinesphere',
        atmospheric: 'atmosphere',
        anthroposphere: 'anthroposphere',
        subterranean: 'lithosphere',
    } as Record<string, string>)[key] || key

    const theme = (sphereKey && SPHERE_THEMES[sphereKey]) || DEFAULT_SPHERE_THEME
    const root = document.documentElement
    root.style.setProperty("--es-color-brand", theme.brand)
    root.style.setProperty("--es-color-brand-rgb", theme.brandRgb)
    root.style.setProperty("--es-color-brand-hover", theme.brandHover)
    root.style.setProperty("--es-color-brand-soft", `rgba(${theme.brandRgb}, 0.08)`)
    root.style.setProperty("--brand", theme.brand)
    root.style.setProperty("--brand-rgb", theme.brandRgb)
    root.style.setProperty("--brand-hover", theme.brandHover)
    root.style.setProperty("--brand-tint", `rgba(${theme.brandRgb}, 0.08)`)
    if (sphereKey) {
        root.setAttribute("data-sphere", sphereKey)
    } else {
        root.removeAttribute("data-sphere")
    }
}

/**
 * Realm-specific theme utilities.
 * These skip the "Sphere" mapping and use the realm name directly to find the color from SPHERE_COLORS.
 */
export function getRealmTheme(realm: unknown): SphereTheme {
    const name = String(realm ?? "").trim()
    if (!name) return DEFAULT_SPHERE_THEME

    // Case-insensitive lookup in SPHERE_COLORS
    const foundKey = Object.keys(SPHERE_COLORS).find(
        (k) => k.toLowerCase() === name.toLowerCase()
    )
    
    // If found in SPHERE_COLORS, use it
    if (foundKey) {
        const color = SPHERE_COLORS[foundKey] ?? DEFAULT_SPHERE_THEME.brand
        // Try to find a pre-defined theme for RGB/Hover consistency
        const t = SPHERE_THEMES[foundKey.toLowerCase()]
        if (t) return t
        
        // Otherwise return a basic theme (fallback RGB is 128,128,128 for shadow if unknown)
        return {
            brand: color,
            brandRgb: "128, 128, 128", // Generic shadow
            brandHover: color,
        }
    }

    // Fallback to Sphere mapping if not in SPHERE_COLORS
    const key = normalizeKey(realm)
    return SPHERE_THEMES[key] ?? DEFAULT_SPHERE_THEME
}

export function getRealmTagPillStyle(realm: unknown): CSSProperties {
    const t = getRealmTheme(realm)
    return {
        background: t.brand,
        color: "var(--text-invert)",
        border: "1px solid transparent",
        boxShadow: `0 2px 5px rgba(${t.brandRgb}, 0.25)`,
    }
}

export function getRealmAccentVars(realm: unknown): CSSProperties {
    const t = getRealmTheme(realm)

    return {
        "--media-accent": t.brand,
        "--media-accent-rgb": t.brandRgb,
        "--media-accent-hover": t.brandHover,
        "--media-accent-tint": `rgba(${t.brandRgb}, 0.12)`,
    } as CSSProperties
}
