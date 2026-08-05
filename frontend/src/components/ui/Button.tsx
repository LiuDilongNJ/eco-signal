import { forwardRef, type ButtonHTMLAttributes, type ForwardedRef, type ReactElement, type ReactNode, type RefAttributes } from "react"
import { Button as AntButton, type ButtonProps as AntButtonProps } from "antd"
import { cn } from "@/lib/utils"

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
        const { appearance: _appearance, className, ...nativeProps } = props
        void _appearance
        return <button ref={ref} className={cn("es-button-unstyled", className)} {...nativeProps} />
    }

    const { className, ...antProps } = props as AntButtonProps
    return <AntButton ref={ref} className={cn("es-button", className)} {...antProps} />
}

export const Button = forwardRef(ButtonAdapter) as ButtonComponent

export interface IconButtonProps extends Omit<AntButtonProps, "children" | "icon" | "aria-label"> {
    icon: ReactNode
    label: string
    pressed?: boolean
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
    { icon, label, pressed, className, ...props },
    ref,
) {
    return (
        <AntButton
            ref={ref}
            className={cn("es-button", "es-icon-button", className)}
            type="text"
            icon={icon}
            aria-label={label}
            title={label}
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
