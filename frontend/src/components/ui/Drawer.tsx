import type { DrawerProps } from "antd"
import { cn } from "@/lib/utils"
import { StageDrawer } from "./StageDrawer"

export type { DrawerProps }

export function Drawer({ rootClassName, ...props }: DrawerProps) {
    return <StageDrawer rootClassName={cn("es-drawer", rootClassName)} {...props} />
}

export function FormDrawer({ rootClassName, ...props }: DrawerProps) {
    return <Drawer rootClassName={cn("es-form-drawer", rootClassName)} {...props} />
}

export function DetailDrawer({ rootClassName, ...props }: DrawerProps) {
    return <Drawer rootClassName={cn("es-detail-drawer", rootClassName)} {...props} />
}
