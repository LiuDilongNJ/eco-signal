/**
 * Dashboard URL 查询参数：刷新后恢复 Tab / Collection / Data 子菜单
 */

import { TAB_ITEMS } from "../data/constants"
import type { TabName } from "../types"

const TAB_SET = new Set<string>(TAB_ITEMS.map((t) => t.key))

export function parseTabParam(raw: string | null): TabName | null {
    if (raw == null || raw.trim() === "") return null
    return TAB_SET.has(raw) ? (raw as TabName) : null
}

/**
 * @returns undefined — URL 未带 collection，沿用接口加载后的默认；
 *   "" | number — 合法时再调用 selectCollection
 */
export function parseCollectionParamForRestore(
    raw: string | null,
    collectionOptions: { id: number | string }[],
): number | "" | undefined {
    if (raw === null) return undefined
    const trimmed = raw.trim()
    if (trimmed === "" || trimmed.toLowerCase() === "all") return ""
    const n = Number(trimmed)
    if (!Number.isFinite(n)) return undefined
    const exists = collectionOptions.some((c) => String(c.id) === String(n))
    return exists ? n : undefined
}

export function collectionToSearchParam(collectionId: number | string | null): string | null {
    if (collectionId === null || collectionId === undefined) return null
    return collectionId === "" ? "all" : String(collectionId)
}
