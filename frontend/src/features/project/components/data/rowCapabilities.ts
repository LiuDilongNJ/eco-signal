import type { RowCapabilities } from "@/api/capabilities"
import type { Key } from "react"
import type { RowData } from "./DataPageLayout"

export type RowCapability = keyof RowCapabilities

export function rowCan(record: RowData, capability: RowCapability): boolean {
    const capabilities = record.capabilities as Partial<RowCapabilities> | undefined
    return capabilities?.[capability] === true
}

export function selectionCan(
    selectedKeys: Set<Key>,
    rows: RowData[],
    idField: string,
    capability: RowCapability,
): boolean {
    if (selectedKeys.size === 0) return false
    const selected = rows.filter((row) => selectedKeys.has(row[idField] as Key))
    return selected.length === selectedKeys.size && selected.every((row) => rowCan(row, capability))
}
