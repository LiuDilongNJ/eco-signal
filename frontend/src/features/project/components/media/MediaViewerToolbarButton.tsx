import { Button as ESButton } from "@/components/ui"
import type { ButtonHTMLAttributes, ReactNode } from "react"

type MediaViewerToolbarButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children" | "title"> & {
    icon: ReactNode
    label: string
    active?: boolean
    variant?: "toolbar" | "zoom"
}

export function MediaViewerToolbarButton({
    icon,
    label,
    active,
    variant = "toolbar",
    className = "",
    ...buttonProps
}: MediaViewerToolbarButtonProps) {
    const baseClass = variant === "zoom" ? "zoom-control-btn" : "btn-toolbar"
    const classes = [baseClass, active ? "active" : "", className].filter(Boolean).join(" ")

    return (
        <ESButton appearance="unstyled"
            type="button"
            className={classes}
            title={label}
            aria-label={label}
            aria-pressed={active}
            {...buttonProps}
        >
            {icon}
        </ESButton>
    )
}
