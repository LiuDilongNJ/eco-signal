import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import {
    Checkbox,
    DataTable,
    EmptyState,
    Form,
    FormField,
    Input,
    LoadingState,
    Popover,
    Select,
    Skeleton,
    Switch,
    Textarea,
    Tooltip,
} from "./index"

describe("UI adapter contracts", () => {
    it("applies controlled form classes and error semantics", () => {
        const { container } = render(
            <Form>
                <FormField label="Name" error="Name is required">
                    <Input aria-label="Name" />
                </FormField>
                <Textarea aria-label="Notes" />
                <Checkbox>Public</Checkbox>
                <Switch aria-label="Active" />
            </Form>,
        )

        expect(container.querySelector(".es-form")).toBeInTheDocument()
        expect(container.querySelector(".es-form-field")).toBeInTheDocument()
        expect(screen.getByLabelText("Name")).toHaveClass("es-input")
        expect(screen.getByLabelText("Notes")).toHaveClass("es-textarea")
        expect(screen.getByRole("checkbox", { name: "Public" }).closest(".es-checkbox")).toBeInTheDocument()
        expect(screen.getByRole("switch", { name: "Active" }).closest(".es-switch")).toBeInTheDocument()
        expect(screen.getByText("Name is required")).toBeInTheDocument()
    })

    it("exposes consistent empty, loading, and skeleton states", () => {
        const { container } = render(
            <>
                <EmptyState title="Nothing here" description="Try another filter" />
                <LoadingState label="Loading records" />
                <Skeleton lines={3} />
            </>,
        )

        expect(screen.getByRole("status", { name: "Loading records" })).toHaveAttribute("aria-busy", "true")
        expect(screen.getByText("Nothing here").closest(".es-empty-state")).toBeInTheDocument()
        expect(container.querySelectorAll(".es-skeleton")).toHaveLength(3)
    })

    it("keeps pagination inside the DataTable contract", () => {
        const { container } = render(
            <DataTable
                rowKey="id"
                columns={[{ key: "name", dataIndex: "name", title: "Name" }]}
                dataSource={[{ id: 1, name: "One" }]}
                pagination={{ current: 1, pageSize: 10, total: 11, onChange: () => undefined }}
            />,
        )

        expect(container.querySelector(".es-data-table__table")).toBeInTheDocument()
        expect(container.querySelector(".es-data-table__pagination .ant-pagination")).toBeInTheDocument()
    })

    it("renders loading through the shared loading contract", () => {
        render(
            <DataTable
                loading
                rowKey="id"
                columns={[{ key: "name", dataIndex: "name", title: "Name" }]}
                dataSource={[]}
            />,
        )

        expect(screen.getByRole("status", { name: "Loading data..." })).toHaveAttribute("aria-busy", "true")
    })

    it("protects Select internals from browser translation DOM mutations", () => {
        render(<Select aria-label="Species" options={[{ value: "owl", label: "Owl" }]} value="owl" />)

        expect(screen.getByRole("combobox", { name: "Species" }).closest(".es-select")).toHaveAttribute(
            "translate",
            "no",
        )
    })

    it("applies the shared floating surface contract to Tooltip and Popover roots", () => {
        render(
            <>
                <Tooltip open title="Tooltip content">
                    <button type="button">Tooltip trigger</button>
                </Tooltip>
                <Popover open content="Popover content">
                    <button type="button">Popover trigger</button>
                </Popover>
            </>,
        )

        expect(document.querySelector(".es-tooltip.ant-tooltip")).toBeInTheDocument()
        expect(document.querySelector(".es-popover.ant-popover")).toBeInTheDocument()
    })
})
