import type { ReactNode } from "react"
import { Space } from "@/components/ui"
import { Button, LoadingState, type DrawerProps } from "@/components/ui"

export const SETTINGS_DRAWER_WIDTH_COMPACT = 480
export const SETTINGS_DRAWER_WIDTH_STANDARD = 480
export const SETTINGS_DRAWER_ROOT_CLASS = "settings-stage-drawer"

export function getSettingsStageDrawerStyles(
    isDark: boolean,
    width: number,
): NonNullable<DrawerProps["styles"]> {
    return {
        wrapper: { width },
        header: {
            background: isDark ? "var(--bg-surface)" : undefined,
            borderBottomColor: isDark ? "var(--border-color)" : undefined,
            color: "var(--text-main)",
        },
        body: {
            background: isDark ? "var(--bg-surface)" : undefined,
            padding: 0,
            overflow: "hidden",
        },
        footer: {
            background: isDark ? "var(--bg-surface)" : undefined,
        },
        mask: {
            backdropFilter: "blur(4px)",
        },
    }
}

export function SettingsDrawerTitle({ children }: { children: ReactNode }) {
    return <span className="settings-drawer-title">{children}</span>
}

export function SettingsDrawerCancelExtra({
    onClose,
    disabled,
}: {
    onClose: () => void
    disabled?: boolean
}) {
    return (
        <Space>
            <Button onClick={onClose} disabled={disabled}>
                Cancel
            </Button>
        </Space>
    )
}

export function SettingsDrawerFormExtra({
    onClose,
    onSave,
    saving,
}: {
    onClose: () => void
    onSave: () => void
    saving?: boolean
}) {
    return (
        <Space>
            <Button onClick={onClose} disabled={saving}>
                Cancel
            </Button>
            <Button type="primary" onClick={onSave} loading={saving}>
                Save
            </Button>
        </Space>
    )
}

export function SettingsDetailLoading() {
    return <LoadingState label="Loading settings..." variant="inline" size="sm" className="camera-settings__muted" />
}

export const SETTINGS_DRAWER_BODY_PADDING = 24
