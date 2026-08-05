import type { ReactNode } from "react"

interface NoDataIconProps {
    className?: string
    width?: number
    height?: number
}

export function NoDataIcon({ className, width = 64, height = 41 }: NoDataIconProps) {
    return (
        <svg
            className={className ? `no-data-icon ${className}` : "no-data-icon"}
            width={width}
            height={height}
            viewBox="0 0 64 41"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
            focusable="false"
        >
            <title>No Data</title>
            <g transform="translate(0 1)" fill="none" fillRule="evenodd">
                <ellipse fill="var(--no-data-shadow, #f5f5f5)" cx="32" cy="33" rx="32" ry="7" />
                <g fillRule="nonzero" stroke="var(--no-data-stroke, #d9d9d9)">
                    <path d="M55 12.8 44.9 1.3Q44 0 42.9 0H21.1q-1.2 0-2 1.3L9 12.8V22h46z" />
                    <path
                        d="M41.6 16c0-1.7 1-3 2.2-3H55v18.1c0 2.2-1.3 3.9-3 3.9H12c-1.7 0-3-1.7-3-3.9V13h11.2c1.2 0 2.2 1.3 2.2 3s1 2.9 2.2 2.9h14.8c1.2 0 2.2-1.4 2.2-3"
                        fill="var(--no-data-fill, #fafafa)"
                    />
                </g>
            </g>
        </svg>
    )
}

interface NoDataEmptyStateProps {
    description?: ReactNode
    className?: string
}

/** 统一空状态：图标 + 文案（Select / Table / Cascader 等） */
export function NoDataEmptyState({
    description = "No Data",
    className = "antd-no-data-empty",
}: NoDataEmptyStateProps) {
    return (
        <div className={className}>
            <NoDataIcon className="media-state__icon" />
            <span>{description}</span>
        </div>
    )
}

/** ConfigProvider.renderEmpty：替换 antd 默认黑色 Empty 图标 */
export function renderAntdEmpty(): ReactNode {
    return <NoDataEmptyState />
}
