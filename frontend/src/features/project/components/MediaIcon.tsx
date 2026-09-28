import { forwardRef } from "react"
import type { LucideProps } from "lucide-react"

export const MediaIcon = forwardRef<SVGSVGElement, LucideProps>(function MediaIcon(
    { size = 24, strokeWidth = 2, ...props },
    ref,
) {
    const lineWidth = Number(strokeWidth) * 13

    return (
        <svg
            ref={ref}
            width={size}
            height={size}
            viewBox="88 88 336 336"
            fill="none"
            stroke="currentColor"
            strokeLinecap="round"
            strokeLinejoin="round"
            focusable="false"
            {...props}
        >
            <rect x="136" y="136" width="240" height="240" rx="28" strokeWidth={lineWidth} />
            <circle cx="196" cy="196" r="30" fill="currentColor" stroke="none" />
            <path d="M136 310h33l27-53 27 72 26-112 27 133 27-67 34 27h39" strokeWidth={lineWidth} />
        </svg>
    )
})
