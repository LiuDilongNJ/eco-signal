import type { DownloadResponse } from "@/api/client"

export function downloadFile(response: DownloadResponse, fallbackFilename?: string): void {
    const url = window.URL.createObjectURL(response.blob)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = response.filename || fallbackFilename || "download"
    anchor.rel = "noopener"
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    window.URL.revokeObjectURL(url)
}
