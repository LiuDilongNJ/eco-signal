import { Dropdown as AntDropdown, type DropdownProps, type MenuProps } from "antd"
import type { ReactElement } from "react"
import { cn } from "@/lib/utils"

export type { DropdownProps, MenuProps }

export interface DropdownMenuProps extends Omit<DropdownProps, "menu" | "children"> {
    items: MenuProps["items"]
    children: ReactElement
    onItemClick?: MenuProps["onClick"]
}

export function DropdownMenu({ items, onItemClick, children, overlayClassName, rootClassName, ...props }: DropdownMenuProps) {
    return (
        <AntDropdown
            menu={{ items, onClick: onItemClick }}
            trigger={["click"]}
            rootClassName={cn(rootClassName, overlayClassName)}
            {...props}
        >
            {children}
        </AntDropdown>
    )
}

export interface DropdownMenuButtonProps extends Omit<React.ComponentProps<typeof AntDropdown.Button>, "menu"> {
    items: MenuProps["items"]
    onItemClick?: MenuProps["onClick"]
    selectedKeys?: string[]
    selectable?: boolean
}

export function DropdownMenuButton({
    items,
    onItemClick,
    selectedKeys,
    selectable,
    ...props
}: DropdownMenuButtonProps) {
    return (
        <AntDropdown.Button
            menu={{ items, onClick: onItemClick, selectedKeys, selectable }}
            trigger={["click"]}
            {...props}
        />
    )
}
