import type { CapabilityName, CapabilityValues } from "@/api/capabilities"
import type { Key } from "react"
import type { RowData } from "./DataPageLayout"

export function rowCan(record: RowData, capability: CapabilityName): boolean {
    const capabilities = record.capabilities as CapabilityValues | undefined
    return capabilities?.[capability] === true
}

export function selectionCan(
    selectedKeys: Set<Key>,
    rows: RowData[],
    idField: string,
    capability: CapabilityName,
): boolean {
    if (selectedKeys.size === 0) return false
    const selected = rows.filter((row) => selectedKeys.has(row[idField] as Key))
    return selected.length === selectedKeys.size && selected.every((row) => rowCan(row, capability))
}
