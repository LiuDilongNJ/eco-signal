export function renderSettingsRelationPills(value: unknown) {
    const count = Number(value ?? 0)
    const label = Number.isFinite(count) ? String(count) : ""
    if (!label) return null

    return (
        <span className="collection-taxon-pills" title={label}>
            <span className="collection-taxon-pill" title={label}>
                {label}
            </span>
        </span>
    )
}
