import { Button, Typography } from "@/components/ui"
import { List as ListIcon, Trash2 } from "lucide-react"
import type { ReactNode } from "react"

const { Title } = Typography

export interface SettingsRelationDetailItem {
    id: number
    name?: string | null
    isDefault?: boolean | null
    notes?: string | null
}

interface SettingsRelationDetailListProps {
    title: string
    items: SettingsRelationDetailItem[]
    fallbackLabel: string
    emptyMessage: string
    isDark: boolean
    action?: ReactNode
    onRemove?: (id: number) => void
    removingId?: number | null
}

export function SettingsRelationDetailList({
    title,
    items,
    fallbackLabel,
    emptyMessage,
    isDark,
    action,
    onRemove,
    removingId,
}: SettingsRelationDetailListProps) {
    return (
        <div>
            <div style={{ marginBottom: 12, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                <Title level={5} style={{ margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
                    <ListIcon size={16} /> {title}
                </Title>
                {action}
            </div>
            {items.length > 0 ? (
                <div
                    style={{
                        background: isDark ? "rgba(255, 255, 255, 0.02)" : "var(--bg-surface-secondary)",
                        borderRadius: 8,
                        border: `1px solid ${isDark ? "var(--border-color)" : "var(--border-light)"}`,
                        overflow: "hidden",
                    }}
                >
                    {items.map((item, index) => (
                        <div
                            key={item.id}
                            style={{
                                padding: "12px 16px",
                                borderBottom:
                                    index === items.length - 1
                                        ? "none"
                                        : `1px solid ${isDark ? "var(--border-color)" : "var(--border-light)"}`,
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "center",
                            }}
                        >
                            <div>
                                <div style={{ fontWeight: 500, color: "var(--text-main)" }}>
                                    {item.name || `${fallbackLabel} #${item.id}`}
                                </div>
                                {item.notes && (
                                    <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
                                        {item.notes}
                                    </div>
                                )}
                            </div>
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                {item.isDefault && (
                                    <span
                                        style={{
                                            fontSize: 10,
                                            background: "var(--brand)",
                                            color: "var(--text-invert)",
                                            padding: "2px 6px",
                                            borderRadius: 4,
                                            fontWeight: 600,
                                        }}
                                    >
                                        DEFAULT
                                    </span>
                                )}
                                {onRemove && (
                                    <Button
                                        type="text"
                                        size="small"
                                        danger
                                        icon={<Trash2 size={14} />}
                                        loading={removingId === item.id}
                                        aria-label={`Remove ${item.name || `${fallbackLabel} #${item.id}`}`}
                                        onClick={() => onRemove(item.id)}
                                    />
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            ) : (
                <p style={{ color: "var(--text-muted)", fontSize: 13, textAlign: "center", padding: "24px 0" }}>
                    {emptyMessage}
                </p>
            )}
        </div>
    )
}
