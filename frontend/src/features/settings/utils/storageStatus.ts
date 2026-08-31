export type StorageHealth = "healthy" | "warning" | "critical"

export function formatStorageBytes(bytes: number): string {
    if (!Number.isFinite(bytes) || bytes < 0) return "-"

    const units = ["B", "KB", "MB", "GB", "TB"]
    let value = bytes
    let unitIndex = 0

    while (value >= 1024 && unitIndex < units.length - 1) {
        value /= 1024
        unitIndex += 1
    }

    return `${value.toFixed(1)} ${units[unitIndex]}`
}

export function storageHealthLabel(status: StorageHealth): string {
    return {
        healthy: "Normal",
        warning: "Warning",
        critical: "Critical",
    }[status]
}
