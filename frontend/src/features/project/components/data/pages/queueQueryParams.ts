export const QUEUE_STATUS_OPTIONS = ["pending", "running", "completed", "error"]

export function resolveQueueOrderBy(sortKey: string | null): string | null {
    if (!sortKey) return null
    return sortKey === "id" ? "queue_id" : sortKey
}

export function applyQueueFilters(
    params: Record<string, unknown>,
    filters: Record<string, unknown>,
) {
    Object.entries(filters).forEach(([key, value]) => {
        if (value === "" || value === null || value === undefined) return

        if (key === "queue_id" || key === "id") {
            params.queue_id = Number(value)
        } else if (key === "user") {
            params.username = String(value).trim()
        } else if (key === "start_time" || key === "stop_time") {
            const [start, end] = String(value).split(",")
            if (start) params[`${key}_from`] = start
            if (end) params[`${key}_to`] = end
        } else {
            params[key] = String(value)
        }
    })
}
