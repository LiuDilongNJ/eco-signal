import { QueryClient } from "@tanstack/react-query"

/** Shared cache so authentication changes can invalidate account-scoped data. */
export const appQueryClient = new QueryClient({
    defaultOptions: {
        queries: {
            staleTime: 5 * 60 * 1000,
            gcTime: 10 * 60 * 1000,
            retry: 1,
            refetchOnWindowFocus: false,
        },
        mutations: {
            retry: 0,
        },
    },
})
