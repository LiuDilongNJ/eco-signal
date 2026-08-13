import { Button } from "@/components/ui"

import "./NotFoundPage.css"

export default function NotFoundPage() {
    return (
        <main className="not-found-page">
            <section className="not-found-page__panel" aria-labelledby="not-found-title">
                <div className="not-found-page__content">
                    <div className="not-found-page__code" aria-hidden="true">
                        404
                    </div>
                    <h1 id="not-found-title" className="not-found-page__title">
                        Page Not Found
                    </h1>
                    <p className="not-found-page__description">
                        The page you are looking for does not exist or has been removed.
                    </p>
                    <Button type="primary" href="/dashboard" className="not-found-page__home-link">
                        Back to Dashboard
                    </Button>
                </div>
            </section>
        </main>
    )
}
