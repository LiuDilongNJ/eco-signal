import { Link } from "react-router-dom"

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
                        页面不存在
                    </h1>
                    <p className="not-found-page__description">您访问的页面不存在或已被移除</p>
                    <Link to="/dashboard" className="not-found-page__home-link">
                        返回首页
                    </Link>
                </div>
            </section>
        </main>
    )
}
