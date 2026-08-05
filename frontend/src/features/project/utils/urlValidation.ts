import type { RuleObject } from "@/components/ui"

function normalizeUrlInput(value: unknown): string {
    return String(value ?? "").trim()
}

function extractInputHostname(candidate: string): string {
    const authority = candidate.replace(/^https?:\/\//i, "").split(/[/?#]/, 1)[0] ?? ""
    const hostPort = authority.split("@").at(-1) ?? ""
    if (hostPort.startsWith("[")) {
        return hostPort.slice(1, hostPort.indexOf("]"))
    }
    return hostPort.split(":", 1)[0] ?? ""
}

function isValidIpv4(hostname: string): boolean {
    const parts = hostname.split(".")
    return (
        parts.length === 4 &&
        parts.every((part) => /^\d{1,3}$/.test(part) && Number(part) <= 255)
    )
}

function parseHttpUrl(raw: string): URL | null {
    if (!raw) return null
    try {
        const candidate = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`
        const parsed = new URL(candidate)
        if (!/^https?:$/i.test(parsed.protocol)) return null

        const inputHostname = extractInputHostname(candidate).toLowerCase()
        const isLocalhost = inputHostname === "localhost" || inputHostname.endsWith(".localhost")
        const isIpv6 = candidate.includes("://[")
        const hasDomainSuffix = inputHostname.includes(".")

        return isLocalhost || isIpv6 || isValidIpv4(inputHostname) || hasDomainSuffix ? parsed : null
    } catch {
        return null
    }
}

export function validateOptionalHttpUrl(value: unknown, label = "URL"): string | null {
    const raw = normalizeUrlInput(value)
    if (!raw) return null
    if (!parseHttpUrl(raw)) {
        return `${label} must be a valid URL`
    }
    return null
}

export function httpUrlRule(label = "URL"): RuleObject {
    return {
        validator: async (_, value) => {
            const error = validateOptionalHttpUrl(value, label)
            if (error) throw new Error(error)
        },
    }
}

export function isUrlLikeField(key: string, label?: string): boolean {
    const normalizedKey = key.toLowerCase()
    const normalizedLabel = String(label ?? "").toLowerCase()
    return normalizedKey.includes("url") || normalizedKey === "link" || normalizedLabel.includes("url")
}
