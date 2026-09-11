import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi, beforeEach } from "vitest"

const mocks = vi.hoisted(() => ({
    getUserPermissionConfig: vi.fn(),
    listAccessRoles: vi.fn(),
    syncUserPermissions: vi.fn(),
}))

vi.mock("../../../../api/endpoints/permissions", () => ({
    permissionsApi: mocks,
}))

import { UserPermissionDrawer } from "./UserPermissionDrawer"

describe("UserPermissionDrawer", () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it("assigns annotation read-own permission at collection scope", async () => {
        mocks.getUserPermissionConfig.mockResolvedValue({
            data: {
                is_admin: false,
                can_manage_admin_role: false,
                projects: [{
                    project_id: 1,
                    project_name: "Project One",
                    can_manage_project: true,
                    stored_permissions: [],
                    effective_permissions: [],
                    assigned_role: "custom",
                    collections: [{
                        project_id: 1,
                        collection_id: 10,
                        collection_name: "Collection One",
                        can_manage_collection: true,
                        stored_permissions: [],
                        effective_permissions: [],
                        inherited_permissions: [],
                        assigned_role: "custom",
                    }],
                }],
            },
        })
        mocks.listAccessRoles.mockResolvedValue({ data: [{
            code: "custom",
            name: "Custom",
            kind: "access",
            display_order: 1,
            project_permissions: [],
            collection_permissions: [],
        }] })
        mocks.syncUserPermissions.mockResolvedValue({ code: 0, message: "success" })

        const user = userEvent.setup()
        render(
            <MemoryRouter>
                <UserPermissionDrawer open userId={2} onClose={vi.fn()} />
            </MemoryRouter>,
        )

        await screen.findByText("Project One")
        await user.click(screen.getByRole("button", { name: "Project One" }))
        const collectionRow = await screen.findByText("Collection One")
        const collectionElement = collectionRow.closest(".upd-collection-row")
        if (!collectionElement) throw new Error("Collection row is missing")
        const icons = collectionElement.querySelectorAll(".upd-icon-item")
        expect(icons).toHaveLength(4)
        const annotationIcon = icons.item(2)
        if (!annotationIcon) throw new Error("Annotation permission icon is missing")

        await user.click(annotationIcon)
        await user.click(screen.getByRole("button", { name: "Save" }))

        await waitFor(() => expect(mocks.syncUserPermissions).toHaveBeenCalledOnce())
        const payload = mocks.syncUserPermissions.mock.calls[0]?.[1]
        if (!payload) throw new Error("Permission payload is missing")
        expect(payload).toMatchObject({
            projects: [{
                project_id: 1,
                collections: [{
                    collection_id: 10,
                    stored_permissions: ["annotation:read_own"],
                    role: "custom",
                }],
            }],
        })
    })

    it("inherits named project role to all collections and omits redundant collection entries on save", async () => {
        mocks.getUserPermissionConfig.mockResolvedValue({
            data: {
                is_admin: false,
                can_manage_admin_role: false,
                projects: [{
                    project_id: 1,
                    project_name: "Project One",
                    can_manage_project: true,
                    stored_permissions: [],
                    effective_permissions: ["project:read", "media:read", "site:read", "annotation:read", "review:read"],
                    assigned_role: "viewer",
                    collections: [{
                        project_id: 1,
                        collection_id: 10,
                        collection_name: "Collection One",
                        can_manage_collection: true,
                        stored_permissions: [],
                        effective_permissions: ["collection:read", "media:read", "site:read", "annotation:read", "review:read"],
                        inherited_permissions: ["collection:read", "media:read", "site:read", "annotation:read", "review:read"],
                        assigned_role: null,
                    }],
                }],
            },
        })
        mocks.listAccessRoles.mockResolvedValue({
            data: [
                {
                    code: "viewer",
                    name: "Viewer",
                    kind: "access",
                    display_order: 1,
                    project_permissions: ["project:read", "media:read", "site:read", "annotation:read", "review:read"],
                    collection_permissions: ["collection:read", "media:read", "site:read", "annotation:read", "review:read"],
                },
                {
                    code: "custom",
                    name: "Custom",
                    kind: "access",
                    display_order: 2,
                    project_permissions: [],
                    collection_permissions: [],
                },
            ],
        })
        mocks.syncUserPermissions.mockResolvedValue({ code: 0, message: "success" })

        const user = userEvent.setup()
        render(
            <MemoryRouter>
                <UserPermissionDrawer open userId={2} onClose={vi.fn()} />
            </MemoryRouter>,
        )

        await screen.findByText("Project One")
        if (!screen.queryByText("Collection One")) {
            await user.click(screen.getByRole("button", { name: "Project One" }))
        }
        const collectionRow = await screen.findByText("Collection One")
        const collectionElement = collectionRow.closest(".upd-collection-row")
        if (!collectionElement) throw new Error("Collection row is missing")

        // Collection role select should be disabled and show Viewer
        const collectionSelect = collectionElement.querySelector(".ant-select-disabled")
        expect(collectionSelect).not.toBeNull()

        // Checkbox should be checked and disabled
        const disabledCheckbox = collectionElement.querySelector(".upd-checkbox--disabled")
        expect(disabledCheckbox).not.toBeNull()

        // Save and verify payload
        await user.click(screen.getByRole("button", { name: "Save" }))
        await waitFor(() => expect(mocks.syncUserPermissions).toHaveBeenCalledOnce())
        const payload = mocks.syncUserPermissions.mock.calls[0]?.[1]
        expect(payload).toEqual({
            projects: [{
                project_id: 1,
                role: "viewer",
                stored_permissions: [],
                collections: [],
            }],
        })
    })

    it("displays warning icon on custom role for project and collection", async () => {
        mocks.getUserPermissionConfig.mockResolvedValue({
            data: {
                is_admin: false,
                can_manage_admin_role: false,
                projects: [{
                    project_id: 1,
                    project_name: "Project One",
                    can_manage_project: true,
                    stored_permissions: [],
                    effective_permissions: [],
                    assigned_role: "custom",
                    collections: [{
                        project_id: 1,
                        collection_id: 10,
                        collection_name: "Collection One",
                        can_manage_collection: true,
                        stored_permissions: [],
                        effective_permissions: [],
                        inherited_permissions: [],
                        assigned_role: "custom",
                    }],
                }],
            },
        })
        mocks.listAccessRoles.mockResolvedValue({
            data: [
                { code: "custom", name: "Custom", kind: "access", display_order: 1, project_permissions: [], collection_permissions: [] },
            ],
        })

        const user = userEvent.setup()
        render(
            <MemoryRouter>
                <UserPermissionDrawer open userId={2} onClose={vi.fn()} />
            </MemoryRouter>,
        )

        await screen.findByText("Project One")
        await user.click(screen.getByRole("button", { name: "Project One" }))
        await screen.findByText("Collection One")

        const warnings = screen.getAllByLabelText("Custom role warning")
        expect(warnings).toHaveLength(2)
    })

    it("displays divergence indicator 'C' and dashed border when custom collection differs from project", async () => {
        mocks.getUserPermissionConfig.mockResolvedValue({
            data: {
                is_admin: false,
                can_manage_admin_role: false,
                projects: [{
                    project_id: 1,
                    project_name: "Project One",
                    can_manage_project: true,
                    stored_permissions: ["media:read"],
                    effective_permissions: ["media:read"],
                    assigned_role: "custom",
                    collections: [{
                        project_id: 1,
                        collection_id: 10,
                        collection_name: "Collection One",
                        can_manage_collection: true,
                        stored_permissions: ["media:write"],
                        effective_permissions: ["media:write"],
                        inherited_permissions: ["media:read"],
                        assigned_role: "custom",
                    }],
                }],
            },
        })
        mocks.listAccessRoles.mockResolvedValue({
            data: [
                { code: "custom", name: "Custom", kind: "access", display_order: 1, project_permissions: [], collection_permissions: [] },
            ],
        })

        const user = userEvent.setup()
        render(
            <MemoryRouter>
                <UserPermissionDrawer open userId={2} onClose={vi.fn()} />
            </MemoryRouter>,
        )

        await screen.findByText("Project One")
        if (!screen.queryByText("Collection One")) {
            await user.click(screen.getByRole("button", { name: "Project One" }))
        }
        await screen.findByText("Collection One")

        // Markers with 'C' text
        const markers = screen.getAllByText("C")
        expect(markers.length).toBeGreaterThanOrEqual(2)

        const divergentIcons = document.querySelectorAll(".upd-icon-item--divergent")
        expect(divergentIcons.length).toBeGreaterThanOrEqual(2)
    })

    it("allows switching project from named role to custom, making collections editable", async () => {
        mocks.getUserPermissionConfig.mockResolvedValue({
            data: {
                is_admin: false,
                can_manage_admin_role: false,
                projects: [{
                    project_id: 1,
                    project_name: "Project One",
                    can_manage_project: true,
                    stored_permissions: [],
                    effective_permissions: ["project:read", "media:read", "site:read", "annotation:read", "review:read"],
                    assigned_role: "viewer",
                    collections: [{
                        project_id: 1,
                        collection_id: 10,
                        collection_name: "Collection One",
                        can_manage_collection: true,
                        stored_permissions: [],
                        effective_permissions: ["collection:read", "media:read", "site:read", "annotation:read", "review:read"],
                        inherited_permissions: ["collection:read", "media:read", "site:read", "annotation:read", "review:read"],
                        assigned_role: null,
                    }],
                }],
            },
        })
        mocks.listAccessRoles.mockResolvedValue({
            data: [
                {
                    code: "viewer",
                    name: "Viewer",
                    kind: "access",
                    display_order: 1,
                    project_permissions: ["project:read", "media:read", "site:read", "annotation:read", "review:read"],
                    collection_permissions: ["collection:read", "media:read", "site:read", "annotation:read", "review:read"],
                },
                {
                    code: "custom",
                    name: "Custom",
                    kind: "access",
                    display_order: 2,
                    project_permissions: [],
                    collection_permissions: [],
                },
            ],
        })
        mocks.syncUserPermissions.mockResolvedValue({ code: 0, message: "success" })

        const user = userEvent.setup()
        render(
            <MemoryRouter>
                <UserPermissionDrawer open userId={2} onClose={vi.fn()} />
            </MemoryRouter>,
        )

        await screen.findByText("Project One")
        if (!screen.queryByText("Collection One")) {
            await user.click(screen.getByRole("button", { name: "Project One" }))
        }
        await screen.findByText("Collection One")

        // Switch project role to Custom
        const projectSelect = screen.getByRole("combobox", { name: "Project role for Project One" })
        await user.click(projectSelect)
        const customOption = await screen.findByText("Custom")
        await user.click(customOption)

        // Now collection role select should be enabled
        const collectionSelect = screen.getByRole("combobox", { name: "Collection role for Collection One" })
        expect(collectionSelect).not.toHaveProperty("disabled", true)

        // Save
        await user.click(screen.getByRole("button", { name: "Save" }))
        await waitFor(() => expect(mocks.syncUserPermissions).toHaveBeenCalledOnce())
        const payload = mocks.syncUserPermissions.mock.calls[0]?.[1]
        expect(payload).toEqual({
            projects: [{
                project_id: 1,
                role: "custom",
                stored_permissions: [],
                collections: [{
                    project_id: 1,
                    collection_id: 10,
                    role: "custom",
                    stored_permissions: [],
                }],
            }],
        })
    })

    it("normalizes null assigned_role to custom and displays Custom on project select", async () => {
        mocks.getUserPermissionConfig.mockResolvedValue({
            data: {
                is_admin: false,
                can_manage_admin_role: false,
                projects: [{
                    project_id: 1,
                    project_name: "Project One",
                    can_manage_project: true,
                    stored_permissions: ["media:read"],
                    effective_permissions: ["media:read"],
                    assigned_role: null,
                    collections: [{
                        project_id: 1,
                        collection_id: 10,
                        collection_name: "Collection One",
                        can_manage_collection: true,
                        stored_permissions: [],
                        effective_permissions: ["media:read"],
                        inherited_permissions: ["media:read"],
                        assigned_role: null,
                    }],
                }],
            },
        })
        mocks.listAccessRoles.mockResolvedValue({
            data: [
                { code: "viewer", name: "Viewer", kind: "access", display_order: 1, project_permissions: [], collection_permissions: [] },
                { code: "custom", name: "Custom", kind: "access", display_order: 2, project_permissions: [], collection_permissions: [] },
            ],
        })

        render(
            <MemoryRouter>
                <UserPermissionDrawer open userId={2} onClose={vi.fn()} />
            </MemoryRouter>,
        )

        await screen.findByText("Project One")
        const projectSelect = screen.getByRole("combobox", { name: "Project role for Project One" })
        const selectContainer = projectSelect.closest(".ant-select")
        expect(selectContainer).toHaveTextContent("Custom")
    })

    it("displays read-all-write-own state and sight badge for annotator role on both annotation and review", async () => {
        mocks.getUserPermissionConfig.mockResolvedValue({
            data: {
                is_admin: false,
                can_manage_admin_role: false,
                projects: [{
                    project_id: 1,
                    project_name: "Project One",
                    can_manage_project: true,
                    stored_permissions: [],
                    effective_permissions: ["project:read", "media:read", "site:read", "annotation:read", "annotation:write_own", "review:read", "review:write_own"],
                    assigned_role: "annotator",
                    collections: [],
                }],
            },
        })
        mocks.listAccessRoles.mockResolvedValue({
            data: [{
                code: "annotator",
                name: "Annotator",
                kind: "access",
                display_order: 20,
                project_permissions: ["project:read", "media:read", "site:read", "annotation:read", "annotation:write_own", "review:read", "review:write_own"],
                collection_permissions: ["collection:read", "media:read", "site:read", "annotation:read", "annotation:write_own", "review:read", "review:write_own"],
            }],
        })

        render(
            <MemoryRouter>
                <UserPermissionDrawer open userId={2} onClose={vi.fn()} />
            </MemoryRouter>,
        )

        await screen.findByText("Project One")
        const markers = document.querySelectorAll('[data-state="read_all_write_own"]')
        expect(markers.length).toBeGreaterThanOrEqual(2)

        const sightBadges = screen.getAllByLabelText("Sight: Read all")
        expect(sightBadges.length).toBeGreaterThanOrEqual(2)
    })

    it("clears collection divergence when project permission icon is clicked", async () => {
        mocks.getUserPermissionConfig.mockResolvedValue({
            data: {
                is_admin: false,
                can_manage_admin_role: false,
                projects: [{
                    project_id: 1,
                    project_name: "Project One",
                    can_manage_project: true,
                    stored_permissions: ["media:read"],
                    effective_permissions: ["media:read"],
                    assigned_role: "custom",
                    collections: [{
                        project_id: 1,
                        collection_id: 10,
                        collection_name: "Collection One",
                        can_manage_collection: true,
                        stored_permissions: ["media:write"],
                        effective_permissions: ["media:write"],
                        inherited_permissions: ["media:read"],
                        assigned_role: "custom",
                    }],
                }],
            },
        })
        mocks.listAccessRoles.mockResolvedValue({
            data: [
                { code: "custom", name: "Custom", kind: "access", display_order: 1, project_permissions: [], collection_permissions: [] },
            ],
        })

        const user = userEvent.setup()
        render(
            <MemoryRouter>
                <UserPermissionDrawer open userId={2} onClose={vi.fn()} />
            </MemoryRouter>,
        )

        await screen.findByText("Project One")
        if (!screen.queryByText("Collection One")) {
            await user.click(screen.getByRole("button", { name: "Project One" }))
        }
        await screen.findByText("Collection One")

        // Initially there are divergence "C" markers
        expect(screen.getAllByText("C").length).toBeGreaterThanOrEqual(2)

        // Click the project's media icon (first icon in project row)
        const projectRow = screen.getByText("Project One").closest(".upd-project-row")
        if (!projectRow) throw new Error("Project row missing")
        const mediaIcon = projectRow.querySelector(".upd-icon-item")
        if (!mediaIcon) throw new Error("Media icon missing")

        await user.click(mediaIcon)

        // Now the collection override was cleared and divergence C markers are removed
        expect(screen.queryByText("C")).toBeNull()
    })

    it("cycles through Model 2 permission states on click in Custom mode", async () => {
        mocks.getUserPermissionConfig.mockResolvedValue({
            data: {
                is_admin: false,
                can_manage_admin_role: false,
                projects: [{
                    project_id: 1,
                    project_name: "Project One",
                    can_manage_project: true,
                    stored_permissions: [],
                    effective_permissions: [],
                    assigned_role: "custom",
                    collections: [],
                }],
            },
        })
        mocks.listAccessRoles.mockResolvedValue({
            data: [
                { code: "custom", name: "Custom", kind: "access", display_order: 1, project_permissions: [], collection_permissions: [] },
            ],
        })

        const user = userEvent.setup()
        render(
            <MemoryRouter>
                <UserPermissionDrawer open userId={2} onClose={vi.fn()} />
            </MemoryRouter>,
        )

        await screen.findByText("Project One")
        const projectRow = screen.getByText("Project One").closest(".upd-project-row")
        if (!projectRow) throw new Error("Project row missing")

        const icons = projectRow.querySelectorAll(".upd-icon-item")
        const annotationIcon = icons[2]
        if (!annotationIcon) throw new Error("Annotation icon missing")

        // 1. Initial State: none
        expect(annotationIcon).toHaveAttribute("data-state", "none")
        expect(annotationIcon).toHaveAttribute("aria-label", "Annotation: None")

        // 2. Click -> Read own
        await user.click(annotationIcon)
        expect(annotationIcon).toHaveAttribute("data-state", "read_own")
        expect(annotationIcon.querySelector(".upd-icon-badge-br")).not.toBeNull()

        // 3. Click -> Write own
        await user.click(annotationIcon)
        expect(annotationIcon).toHaveAttribute("data-state", "write_own")
        expect(annotationIcon).toHaveClass("upd-icon-item--write")

        // 4. Click -> Read all
        await user.click(annotationIcon)
        expect(annotationIcon).toHaveAttribute("data-state", "read_all")
        expect(annotationIcon).not.toHaveClass("upd-icon-item--write")

        // 5. Click -> Read all, write own (State 4)
        await user.click(annotationIcon)
        expect(annotationIcon).toHaveAttribute("data-state", "read_all_write_own")
        expect(annotationIcon.querySelector(".upd-icon-badge-tl")).not.toBeNull()
        expect(annotationIcon.querySelector(".upd-icon-badge-br")).not.toBeNull()

        // 6. Click -> Write all (State 5)
        await user.click(annotationIcon)
        expect(annotationIcon).toHaveAttribute("data-state", "write_all")
        expect(annotationIcon.querySelector(".upd-icon-badge-tl")).toBeNull()
        expect(annotationIcon.querySelector(".upd-icon-badge-br")).not.toBeNull()

        // 7. Click -> resets to None
        await user.click(annotationIcon)
        expect(annotationIcon).toHaveAttribute("data-state", "none")
    })

    it("preserves module identity on all 4 modules regardless of configured permissions", async () => {
        mocks.getUserPermissionConfig.mockResolvedValue({
            data: {
                is_admin: false,
                can_manage_admin_role: false,
                projects: [{
                    project_id: 1,
                    project_name: "Project One",
                    can_manage_project: true,
                    stored_permissions: [
                        "media:read",
                        "site:write",
                        "annotation:read",
                        "annotation:write_own",
                        "review:write",
                    ],
                    effective_permissions: [
                        "media:read",
                        "site:write",
                        "annotation:read",
                        "annotation:write_own",
                        "review:write",
                    ],
                    assigned_role: "custom",
                    collections: [],
                }],
            },
        })
        mocks.listAccessRoles.mockResolvedValue({
            data: [{ code: "custom", name: "Custom", kind: "access", display_order: 1, project_permissions: [], collection_permissions: [] }],
        })

        render(
            <MemoryRouter>
                <UserPermissionDrawer open userId={2} onClose={vi.fn()} />
            </MemoryRouter>,
        )

        await screen.findByText("Project One")
        const projectRow = screen.getByText("Project One").closest(".upd-project-row")
        if (!projectRow) throw new Error("Project row missing")

        const mediaItem = projectRow.querySelector('[data-resource="media"]')
        const siteItem = projectRow.querySelector('[data-resource="site"]')
        const annotItem = projectRow.querySelector('[data-resource="annotation"]')
        const reviewItem = projectRow.querySelector('[data-resource="review"]')

        expect(mediaItem).toHaveAttribute("data-state", "read_all")
        expect(siteItem).toHaveAttribute("data-state", "write_all")
        expect(annotItem).toHaveAttribute("data-state", "read_all_write_own")
        expect(reviewItem).toHaveAttribute("data-state", "write_all")
    })
})
