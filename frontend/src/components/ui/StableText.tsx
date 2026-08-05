interface StableTextProps {
    children: string | number | null | undefined
    className?: string
}

function escapeHtml(value: string): string {
    return value
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;")
}

export function StableText({ children, className }: StableTextProps) {
    const text = children == null ? "" : String(children)

    return (
        <span
            className={className}
            data-translate-stable=""
            dangerouslySetInnerHTML={{ __html: escapeHtml(text) }}
        />
    )
}
