type IconProps = { size?: number; strokeWidth?: number }

/** Zoom spectrogram/photo to the current annotation or selection. */
export function AnnotationZoomIcon({ size = 20, strokeWidth = 2 }: IconProps) {
    return (
        <svg
            width={size}
            height={size}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
        >
            <rect x="1.5" y="1.5" width="21" height="21" rx="2.5" strokeDasharray="4 3" />
            <circle cx="13" cy="13" r="5.75" />
            <path d="m17.1 17.1 4.15 4.15" />
        </svg>
    )
}

/** Previous annotation — arrow combined with annotation box (distinct from media pan). */
export function AnnotationPrevIcon({ size = 20, strokeWidth = 2 }: IconProps) {
    return (
        <svg
            width={size}
            height={size}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
        >
            <rect x="1.5" y="1.5" width="21" height="21" rx="2.5" strokeDasharray="4 3" />
            <path d="M15 12H7.5" />
            <path d="M10.5 8.5 7 12l3.5 3.5" />
        </svg>
    )
}

/** Next annotation — arrow combined with annotation box (distinct from media pan). */
export function AnnotationNextIcon({ size = 20, strokeWidth = 2 }: IconProps) {
    return (
        <svg
            width={size}
            height={size}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
        >
            <rect x="1.5" y="1.5" width="21" height="21" rx="2.5" strokeDasharray="4 3" />
            <path d="M9 12h7.5" />
            <path d="M13.5 8.5 17 12l-3.5 3.5" />
        </svg>
    )
}

/**
 * Toggle: previous/next also auto-zooms to each annotation.
 * Magnifier with bidirectional arrows (not a plain zoom/search glass).
 */
export function AnnotationNavAutoZoomIcon({ size = 20, strokeWidth = 2 }: IconProps) {
    return (
        <svg
            width={size}
            height={size}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
        >
            <circle cx="10.75" cy="10.75" r="7.5" />
            <path d="m16.25 16.25 4.5 4.5" />
            <path d="M7 10.75h7.5" />
            <path d="M9.25 8.25 6.75 10.75l2.5 2.5" />
            <path d="M12.25 8.25 14.75 10.75l-2.5 2.5" />
        </svg>
    )
}
