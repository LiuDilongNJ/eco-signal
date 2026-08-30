import { Button, Typography } from "@/components/ui"
import { Eye, List as ListIcon, Trash2 } from "lucide-react"
import type { ReactNode } from "react"

const { Title } = Typography

export interface SettingsRelationDetailItem {
    id: number
    name?: string | null
    notes?: string | null
}

interface SettingsRelationDetailListProps {
    title: string
    items: SettingsRelationDetailItem[]
    fallbackLabel: string
    emptyMessage: string
    isDark: boolean
    action?: ReactNode
    onView?: (id: number) => void
    viewingId?: number | null
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
    onView,
    viewingId,
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
                                {onView && (
                                    <Button
                                        className="settings-relation-action settings-relation-action--view"
                                        type="text"
                                        size="small"
                                        icon={<Eye size={14} />}
                                        loading={viewingId === item.id}
                                        aria-label={`View ${item.name || `${fallbackLabel} #${item.id}`}`}
                                        title={`View ${item.name || `${fallbackLabel} #${item.id}`}`}
                                        onClick={() => onView(item.id)}
                                    />
                                )}
                                {onRemove && (
                                    <Button
                                        className="settings-relation-action settings-relation-action--remove"
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
