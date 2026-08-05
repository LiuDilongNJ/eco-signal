export type MediaTypeFilter = "all" | "audio" | "photo"

export function mediaTypeFilterParam(value: MediaTypeFilter): "audio" | "photo" | undefined {
    return value === "all" ? undefined : value
}
