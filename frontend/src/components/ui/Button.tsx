import { forwardRef, type ButtonHTMLAttributes, type ForwardedRef, type ReactElement, type ReactNode, type RefAttributes } from "react"
import { Button as AntButton, type ButtonProps as AntButtonProps } from "antd"
import { cn } from "@/lib/utils"
import { getTooltipText } from "./tooltipText"

type NativeButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
    appearance: "unstyled"
}

export type ButtonProps = AntButtonProps

interface ButtonComponent {
    (props: NativeButtonProps & RefAttributes<HTMLButtonElement>): ReactElement
    (props: AntButtonProps & RefAttributes<HTMLButtonElement>): ReactElement
}

function ButtonAdapter(props: AntButtonProps | NativeButtonProps, ref: ForwardedRef<HTMLButtonElement>) {
    if ("appearance" in props && props.appearance === "unstyled") {
        const { appearance: _appearance, className, title, ...nativeProps } = props
        void _appearance
        return <button ref={ref} className={cn("es-button-unstyled", className)} title={getTooltipText(title)} {...nativeProps} />
    }

    const { className, title, ...antProps } = props as AntButtonProps
    return <AntButton ref={ref} className={cn("es-button", className)} title={getTooltipText(title)} {...antProps} />
}

export const Button = forwardRef(ButtonAdapter) as ButtonComponent

export interface IconButtonProps extends Omit<AntButtonProps, "children" | "icon" | "aria-label"> {
    icon: ReactNode
    label: string
    tooltip?: string
    pressed?: boolean
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
    { icon, label, tooltip, pressed, className, title, ...props },
    ref,
) {
    return (
        <AntButton
            ref={ref}
            className={cn("es-button", "es-icon-button", className)}
            type="text"
            icon={icon}
            aria-label={label}
            title={getTooltipText(tooltip ?? title ?? label)}
            aria-pressed={pressed}
            {...props}
        />
    )
})

export interface ToolbarButtonProps extends IconButtonProps {
    active?: boolean
}

export const ToolbarButton = forwardRef<HTMLButtonElement, ToolbarButtonProps>(function ToolbarButton(
    { active, className, ...props },
    ref,
) {
    return (
        <IconButton
            ref={ref}
            className={cn("es-toolbar-button", active && "is-active", className)}
            pressed={active}
            {...props}
        />
    )
})
