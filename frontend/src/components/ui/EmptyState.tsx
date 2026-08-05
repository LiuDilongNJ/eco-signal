import type { ReactNode } from "react"
import { Button } from "./Button"
import { NoDataIcon } from "./NoDataIcon"
import { cn } from "@/lib/utils"

export interface EmptyStateProps {
    title?: ReactNode
    description?: ReactNode
    action?: ReactNode
    className?: string
}

export function EmptyState({ title = "No data", description, action, className }: EmptyStateProps) {
    return (
        <div className={cn("ui-state es-empty-state", className)} role="status">
            <NoDataIcon />
            <strong className="es-empty-state__title">{title}</strong>
            {description ? <div className="es-empty-state__description">{description}</div> : null}
            {action ? <div className="es-empty-state__action">{action}</div> : null}
        </div>
    )
}

export { Button as EmptyStateAction }
