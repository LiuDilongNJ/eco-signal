import { Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"

type LoadingStateVariant = "inline" | "page" | "overlay"
type LoadingStateSize = "sm" | "md" | "lg"

interface LoadingStateProps {
    label?: string
    variant?: LoadingStateVariant
    size?: LoadingStateSize
    className?: string
    showLabel?: boolean
}

const iconSizeBySize: Record<LoadingStateSize, number> = {
    sm: 16,
    md: 22,
    lg: 28,
}

export function LoadingState({
    label = "Loading...",
    variant = "inline",
    size = "md",
    className,
    showLabel = true,
}: LoadingStateProps) {
    return (
        <div
            className={cn(
                "ui-state ui-state--loading",
                variant === "inline" && "ui-state--inline",
                variant === "page" && "ui-state--page",
                variant === "overlay" && "ui-state--overlay",
                className,
            )}
            role="status"
            aria-live="polite"
            aria-busy="true"
            aria-label={label}
        >
            <Loader2 className="ui-state__spinner" size={iconSizeBySize[size]} aria-hidden />
            {showLabel ? <span>{label}</span> : null}
        </div>
    )
}
