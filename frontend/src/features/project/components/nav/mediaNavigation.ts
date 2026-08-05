import type { MediaOption } from "../../../../api/endpoints/media"

export type MediaNavItem = {
    id: number
    label: string
    mediaType: string
}

type NavigableMedia = Pick<MediaOption, "media_id" | "name" | "media_type" | "is_metadata" | "filename">

function normalizedMediaType(value: unknown): string {
    return String(value ?? "").trim().toLowerCase()
}

export function isMediaDetailNavigable(row: NavigableMedia): boolean {
    if (row.is_metadata === true) return false
    if (normalizedMediaType(row.media_type) === "metadata") return false
    return !/\.(csv|json|xml)$/i.test(String(row.filename ?? "").trim())
}

export function buildMediaNavItems(rows: NavigableMedia[]): MediaNavItem[] {
    return rows
        .filter(isMediaDetailNavigable)
        .map((row) => ({
            id: row.media_id,
            label: (row.name && String(row.name).trim()) || `Media ${row.media_id}`,
            mediaType: normalizedMediaType(row.media_type) || "audio",
        }))
}

export function pickPreferredMedia(
    items: MediaNavItem[],
    preferredMediaType: string | null | undefined,
): MediaNavItem | undefined {
    const preferred = normalizedMediaType(preferredMediaType)
    return (preferred ? items.find((item) => item.mediaType === preferred) : undefined) ?? items[0]
}
