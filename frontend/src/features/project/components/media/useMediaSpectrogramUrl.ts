import { useEffect, useRef, useState } from "react"

import { getAuthToken } from "../../../../api/client"

const FALLBACK_SPECTROGRAM =
    ""


async function fetchBlobWithAuth(path: string): Promise<Blob> {
    const token = getAuthToken()
    const res = await fetch(`${window.location.origin}${path}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!res.ok) throw new Error(`preview ${res.status}`)
    return res.blob()
}

function withProjectId(path: string, projectId: number | null | undefined): string {
    if (projectId == null || !Number.isFinite(Number(projectId))) return path
    const url = new URL(path, window.location.origin)
    url.searchParams.set("project_id", String(projectId))
    return `${url.pathname}${url.search}`
}

/**
 * Gallery/List 频谱缩略图：
 * - 外链 http(s) 直接用
 * - `/api/v1/media/.../previews/...` 需 Bearer，用 fetch + blob
 * - 其他路径直接 fallback（列表页不按 mediaId 逐条拉详情，避免 N+1 请求）
 */
export function useMediaSpectrogramUrl(
    raw: string | undefined | null,
    mediaId: number | null | undefined,
    projectId?: number | null,
): string {
    const [url, setUrl] = useState<string>(FALLBACK_SPECTROGRAM)
    const blobRef = useRef<string | null>(null)

    useEffect(() => {
        const revoke = () => {
            if (blobRef.current) {
                URL.revokeObjectURL(blobRef.current)
                blobRef.current = null
            }
        }

        const s = raw == null ? "" : String(raw).trim()
        const mid =
            mediaId != null && Number.isFinite(Number(mediaId)) ? Math.trunc(Number(mediaId)) : null

        if (s === "" && mid == null) {
            revoke()
            setUrl(FALLBACK_SPECTROGRAM)
            return
        }

        if (s.startsWith("http://") || s.startsWith("https://")) {
            revoke()
            setUrl(s)
            return
        }

        let cancelled = false

        if (s.startsWith("/api/")) {
            ;(async () => {
                try {
                    const blob = await fetchBlobWithAuth(withProjectId(s, projectId))
                    if (cancelled) return
                    revoke()
                    const objectUrl = URL.createObjectURL(blob)
                    blobRef.current = objectUrl
                    setUrl(objectUrl)
                } catch {
                    if (!cancelled) {
                        revoke()
                        setUrl(FALLBACK_SPECTROGRAM)
                    }
                }
            })()
            return () => {
                cancelled = true
                revoke()
            }
        }

        // 不在列表页按 mediaId 逐条拉取详情接口，直接 fallback
        // （详情请求留给进入媒体详情页后按需加载）

        revoke()
        setUrl(FALLBACK_SPECTROGRAM)
        return () => {
            revoke()
        }
    }, [raw, mediaId, projectId])

    return url
}

export { FALLBACK_SPECTROGRAM }
