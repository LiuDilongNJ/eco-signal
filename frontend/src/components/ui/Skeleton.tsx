import type { CSSProperties, HTMLAttributes } from "react"
import { cn } from "@/lib/utils"

export interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
    width?: CSSProperties["width"]
    height?: CSSProperties["height"]
    lines?: number
}

export function Skeleton({ className, width = "100%", height = 16, lines = 1, style, ...props }: SkeletonProps) {
    return (
        <div className={cn("es-skeleton-group", className)} aria-hidden="true" {...props}>
            {Array.from({ length: lines }, (_, index) => (
                <div
                    className="es-skeleton"
                    key={index}
                    style={{ width: index === lines - 1 && lines > 1 ? "72%" : width, height, ...style }}
                />
            ))}
        </div>
    )
}
