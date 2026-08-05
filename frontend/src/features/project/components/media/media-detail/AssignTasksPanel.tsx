import type { ComponentProps } from "react"
import type { AssignableUserPublic } from "../../../../../api/endpoints/tasks"
import {
    Button,
    Button as ESButton,
    Checkbox,
    ConfigProvider,
    CustomScrollArea,
    LoadingState,
    EmptyState,
} from "@/components/ui"
import { ArrowLeft } from "lucide-react"

type ThemeContract = ComponentProps<typeof ConfigProvider>["theme"]

export interface AssignTasksSelectionContract {
    users: AssignableUserPublic[]
    selectedUserIds: number[]
    annotationCount: number
    loading: boolean
    submitting: boolean
    onToggleUser: (userId: number, checked: boolean) => void
}

export interface AssignTasksPanelProps {
    theme: ThemeContract
    selection: AssignTasksSelectionContract
    onClose: () => void
    onSubmit: () => void | Promise<void>
}

export function AssignTasksPanel({ theme, selection, onClose, onSubmit }: AssignTasksPanelProps) {
    const {
        users,
        selectedUserIds,
        annotationCount,
        loading,
        submitting,
        onToggleUser,
    } = selection

    return (
        <ConfigProvider theme={theme}>
            <div className="studio-analysis-embed">
                <div className="studio-analysis-embed-top">
                    <ESButton
                        appearance="unstyled"
                        type="button"
                        className="header-back"
                        title="Back"
                        aria-label="Back to media information"
                        onClick={onClose}
                    >
                        <ArrowLeft size={18} strokeWidth={2.25} />
                    </ESButton>
                    <span className="header-title studio-analysis-embed-heading">Assign Tasks</span>
                </div>

                <div className="studio-analysis-embed-body">
                    <CustomScrollArea variant="fill">
                        <div className="studio-assign-task-body">
                            {loading ? (
                                <LoadingState label="Loading users..." variant="inline" />
                            ) : (
                                <div className="assign-tasks-content studio-assign-task-content">
                                    <div className="assign-tasks-list">
                                        {users.length === 0 ? (
                                            <EmptyState className="studio-assign-task-empty" title="No assignable users found." />
                                        ) : (
                                            users.map((user, index) => {
                                                const checked = selectedUserIds.includes(user.user_id)
                                                return (
                                                    <div
                                                        key={user.user_id}
                                                        className={`assign-tasks-item studio-assign-task-item${checked ? " is-selected" : ""}`}
                                                        data-last={index === users.length - 1 ? "true" : undefined}
                                                    >
                                                        <Checkbox
                                                            checked={checked}
                                                            onChange={(event) =>
                                                                onToggleUser(user.user_id, event.target.checked)
                                                            }
                                                            className="studio-assign-task-checkbox"
                                                        >
                                                            {user.name?.trim() || user.username}
                                                        </Checkbox>
                                                    </div>
                                                )
                                            })
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>
                    </CustomScrollArea>
                </div>

                <div className="studio-analysis-embed-foot">
                    <div className="assign-tasks-footer">
                        <Button
                            onClick={onClose}
                            disabled={submitting}
                            className="assign-tasks-btn-cancel"
                        >
                            Cancel
                        </Button>
                        <Button
                            type="primary"
                            loading={submitting}
                            disabled={loading || selectedUserIds.length === 0 || annotationCount === 0}
                            onClick={() => void onSubmit()}
                            className="assign-tasks-btn-save"
                        >
                            Save
                        </Button>
                    </div>
                </div>
            </div>
        </ConfigProvider>
    )
}
