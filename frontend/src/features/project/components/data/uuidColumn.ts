import type { ColumnDef } from "./DataPageLayout"

/** Compact default width — full UUID remains available via hover title / expand. */
export const UUID_COLUMN_WIDTH_COLLAPSED = 108
/** Expanded width for copying / reading the full value. */
export const UUID_COLUMN_WIDTH_EXPANDED = 300

export const UUID_COLUMN_EXPANDED_STORAGE_KEY = "eco-signal.table.uuid-column-expanded"

export function readUuidColumnExpanded(): boolean {
    try {
        return sessionStorage.getItem(UUID_COLUMN_EXPANDED_STORAGE_KEY) === "1"
    } catch {
        return false
    }
}

export function writeUuidColumnExpanded(expanded: boolean) {
    try {
        sessionStorage.setItem(UUID_COLUMN_EXPANDED_STORAGE_KEY, expanded ? "1" : "0")
    } catch {
        // Private browsing or blocked storage must not break the table.
    }
}

/** Shared UUID column used across dashboard tables — starts compact. */
export function createUuidColumn(overrides?: Partial<ColumnDef>): ColumnDef {
    return {
        key: "uuid",
        label: "UUID",
        type: "text",
        width: UUID_COLUMN_WIDTH_COLLAPSED,
        maxWidth: UUID_COLUMN_WIDTH_COLLAPSED,
        ellipsis: true,
        sortable: true,
        filterable: true,
        tooltip: "Unique identifier. Expand the column when you need the full value.",
        ...overrides,
    }
}
