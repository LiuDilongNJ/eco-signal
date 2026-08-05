import { Button as ESButton } from "@/components/ui"
import type { MediaTypeFilter } from "./mediaTypeFilter"

const MEDIA_TYPE_OPTIONS: { value: MediaTypeFilter; label: string }[] = [
    { value: "all", label: "All" },
    { value: "audio", label: "Audio" },
    { value: "photo", label: "Photo" },
]

interface MediaTypeSegmentProps {
    value: MediaTypeFilter
    onChange: (value: MediaTypeFilter) => void
    className?: string
}

export function MediaTypeSegment({ value, onChange, className }: MediaTypeSegmentProps) {
    return (
        <div className={`nav-center media-type-segment${className ? ` ${className}` : ""}`}>
            {MEDIA_TYPE_OPTIONS.map((option) => (
                <ESButton appearance="unstyled"
                    key={option.value}
                    type="button"
                    className={`nav-center-btn${value === option.value ? " active" : ""}`}
                    onClick={() => onChange(option.value)}
                >
                    {option.label}
                </ESButton>
            ))}
        </div>
    )
}
