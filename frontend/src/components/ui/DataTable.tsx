import { Pagination, Table, type PaginationProps, type TableProps } from "antd"
import type { HTMLAttributes, ReactNode, Ref } from "react"
import { cn } from "@/lib/utils"
import { LoadingState } from "./LoadingState"

export type { PaginationProps, TableProps }
export { INTERNAL_COL_DEFINE } from "@rc-component/table"

export interface DataTableProps<RecordType extends object = Record<string, unknown>> extends Omit<TableProps<RecordType>, "pagination"> {
    toolbar?: ReactNode
    emptyState?: ReactNode
    pagination?: false | PaginationProps
    paginationContainerRef?: Ref<HTMLDivElement>
}

export function DataTable<RecordType extends object = Record<string, unknown>>({
    className,
    toolbar,
    emptyState,
    locale,
    pagination,
    paginationContainerRef,
    loading,
    ...props
}: DataTableProps<RecordType>) {
    const isLoading = loading === true || (typeof loading === "object" && loading !== null)
    return (
        <div className="es-data-table">
            {toolbar}
            <div className="es-data-table__surface">
                {isLoading ? <LoadingState label="Loading data..." variant="overlay" size="md" /> : null}
                <Table<RecordType>
                    className={cn("es-data-table__table", className)}
                    locale={{ emptyText: emptyState, ...locale }}
                    loading={false}
                    pagination={false}
                    {...props}
                />
            </div>
            {pagination !== false ? (
                <div ref={paginationContainerRef} className="es-data-table__pagination data-table-pagination">
                    <Pagination showSizeChanger {...pagination} />
                </div>
            ) : null}
        </div>
    )
}

export function TableToolbar({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
    return <div className={cn("es-table-toolbar", className)} {...props} />
}

export function RowActions({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
    return <div className={cn("es-row-actions", className)} {...props} />
}
