import { useEffect, useState } from "react"
import { usersApi, type UserOption } from "../../../../../api/endpoints/users"

type ScopeId = string | number | null | undefined

function hasProjectScope(projectId: ScopeId): boolean {
    return Boolean(projectId)
}

export function useCreatorOptions(projectId: ScopeId, collectionId: ScopeId) {
    const [creatorOptions, setCreatorOptions] = useState<UserOption[]>([])
    const [currentUser, setCurrentUser] = useState<UserOption | null>(null)

    useEffect(() => {
        let cancelled = false
        usersApi.getMe().then((response) => {
            if (cancelled || !response.data) return
            setCurrentUser({
                user_id: response.data.user_id,
                name: response.data.name || response.data.username || String(response.data.user_id),
                username: response.data.username,
            })
        }).catch(() => {
            if (!cancelled) setCurrentUser(null)
        })
        return () => { cancelled = true }
    }, [])

    useEffect(() => {
        let cancelled = false

        const load = async () => {
            try {
                if (!hasProjectScope(projectId)) {
                    setCreatorOptions([])
                    return
                }

                const response = await usersApi.getCreatorOptions({
                    project_id: Number(projectId),
                    ...(collectionId && collectionId !== "all"
                        ? { collection_id: Number(collectionId) }
                        : {}),
                })
                if (cancelled) return

                const options: UserOption[] = (response.data ?? []).map((user) => ({
                    user_id: user.user_id,
                    name: user.name || user.username || String(user.user_id),
                    username: user.username,
                }))
                if (currentUser && !options.some((user) => user.user_id === currentUser.user_id)) {
                    options.unshift({
                        ...currentUser,
                    })
                }
                setCreatorOptions(options)
            } catch (error) {
                if (cancelled) return
                console.error("Failed to fetch creator options:", error)
                setCreatorOptions([])
            }
        }

        void load()
        return () => {
            cancelled = true
        }
    }, [collectionId, currentUser, projectId])

    return { creatorOptions, currentUserId: currentUser?.user_id ?? null }
}
