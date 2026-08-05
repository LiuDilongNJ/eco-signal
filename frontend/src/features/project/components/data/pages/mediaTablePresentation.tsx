export function openMediaDetailTab(projectId: number, mediaId: number) {
    window.open(
        `/dashboard/${projectId}/media/${mediaId}`,
        `eco-media-view-${mediaId}`,
        "noopener,noreferrer",
    )
}

export function renderLabelPills(value: unknown) {
    const labels = Array.isArray(value)
        ? value
        : typeof value === "string"
            ? value.split(",")
            : []
    const names = labels
        .map((label) => String(label ?? "").trim())
        .filter(Boolean)

    if (names.length === 0) return null

    return (
        <span className="collection-taxon-pills" title={names.join(", ")}>
            {names.map((name, index) => (
                <span className="collection-taxon-pill" key={`${name}-${index}`}>
                    {name}
                </span>
            ))}
        </span>
    )
}

export function selectedMediaIds(selectedRows: Set<unknown>): number[] {
    return Array.from(selectedRows)
        .map((id) => Number(id))
        .filter((id) => Number.isFinite(id) && id > 0)
}
