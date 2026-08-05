/**
 * String utilities for rich text processing and HTML handling
 */

const ABSOLUTE_OR_EMBEDDED_URL_RE = /^(?:[a-z][a-z0-9+.-]*:)?\/\//i

export function normalizeRichTextImageSrc(src: string): string {
    const raw = String(src || "").trim()
    if (!raw) return ""
    if (
        ABSOLUTE_OR_EMBEDDED_URL_RE.test(raw) ||
        raw.startsWith("data:") ||
        raw.startsWith("blob:") ||
        raw.startsWith("#")
    ) {
        return raw
    }

    const normalized = raw.replace(/^\/+/, "")
    if (normalized.startsWith("sounds/")) {
        return `/${normalized}`
    }
    return `/sounds/${normalized}`
}

export function normalizeRichTextHtml(html: string): string {
    if (!html || typeof DOMParser === "undefined" || !/<img\b/i.test(html)) {
        return html
    }

    const doc = new DOMParser().parseFromString(html, "text/html")
    let changed = false

    doc.querySelectorAll("img").forEach((img) => {
        const src = img.getAttribute("src")
        if (!src) return
        const normalized = normalizeRichTextImageSrc(src)
        if (normalized !== src) {
            img.setAttribute("src", normalized)
            changed = true
        }
    })

    return changed ? doc.body.innerHTML : html
}

/**
 * Decodes common HTML entities back into their respective characters.
 * This is useful when data has been escaped but needs to be rendered as HTML.
 */
export function decodeHTMLEntities(text: string): string {
    if (!text || typeof text !== "string") return ""
    if (!text.includes("&")) return text

    return text
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/&amp;/g, "&")
        .replace(/&quot;/g, "\"")
        .replace(/&#39;/g, "'")
        .replace(/&lsquo;/g, "‘")
        .replace(/&rsquo;/g, "’")
        .replace(/&ldquo;/g, "“")
        .replace(/&rdquo;/g, "”")
        .replace(/&nbsp;/g, " ")
}

/**
 * Prepares a string for dangerouslySetInnerHTML by ensuring it is a string
 * and decoding any HTML entities if present.
 */
export function parseRichText(text: any): string {
    if (text == null) return ""
    const s = String(text)

    // If the text looks like it has escaped tags (e.g. &lt;div), decode it
    if (s.includes("&lt;") || s.includes("&gt;")) {
        return normalizeRichTextHtml(decodeHTMLEntities(s))
    }

    return normalizeRichTextHtml(s)
}
