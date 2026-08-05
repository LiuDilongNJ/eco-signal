import type { HTMLAttributes, ReactNode } from "react"
import { cn } from "@/lib/utils"

export function PageContainer({ className, ...props }: HTMLAttributes<HTMLElement>) {
    return <main className={cn("es-page", className)} {...props} />
}

export interface PageHeaderProps extends Omit<HTMLAttributes<HTMLElement>, "title"> {
    title: ReactNode
    description?: ReactNode
    actions?: ReactNode
}

export function PageHeader({ title, description, actions, className, ...props }: PageHeaderProps) {
    return (
        <header className={cn("es-page-header", className)} {...props}>
            <div className="es-page-header__copy">
                <h1 className="es-page-header__title">{title}</h1>
                {description ? <div className="es-page-header__description">{description}</div> : null}
            </div>
            {actions ? <div className="es-page-header__actions">{actions}</div> : null}
        </header>
    )
}

export function PageContent({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
    return <div className={cn("es-page-content", className)} {...props} />
}

export function Section({ className, ...props }: HTMLAttributes<HTMLElement>) {
    return <section className={cn("es-section", className)} {...props} />
}

export interface StackProps extends HTMLAttributes<HTMLDivElement> {
    gap?: "xs" | "sm" | "md" | "lg" | "xl"
    direction?: "row" | "column"
}

export function Stack({ gap = "md", direction = "column", className, ...props }: StackProps) {
    return <div className={cn("es-stack", `es-stack--${direction}`, `es-stack--${gap}`, className)} {...props} />
}
