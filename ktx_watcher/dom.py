"""Read-only DOM snapshots. Each call reads live state in one browser round trip.

Selectors passed here must be native CSS, not Playwright text selectors.
Actions stay in Playwright so visibility checks and trusted input are preserved.
"""

from .browser import Page


def read_page_state(page: Page, *, inputs: dict[str, str] | None = None,
                    tab: str | None = None, include_text: bool = True,
                    texts: dict[str, str] | None = None) -> dict:
    return page.evaluate(
        """({inputs, tab, includeText, texts}) => {
            const visible = el => {
                const style = getComputedStyle(el);
                return style.visibility !== 'hidden' &&
                    style.visibility !== 'collapse' && el.getClientRects().length > 0;
            };
            const modals = includeText ? [...document.querySelectorAll(
                '.ReactModal__Content, [role=dialog]')].filter(visible) : [];
            const activeTab = tab ? document.querySelector(tab) : null;
            return {
                url: location.href,
                body: includeText ? (document.body?.innerText || '') : '',
                modals: modals.map(el => el.innerText || ''),
                inputs: Object.fromEntries(Object.entries(inputs).map(
                    ([key, sel]) => [key, document.querySelector(sel)?.value ?? null])),
                texts: Object.fromEntries(Object.entries(texts).map(
                    ([key, sel]) => [key, document.querySelector(sel)?.textContent?.trim() ?? null])),
                tab: activeTab ? {
                    active: /active|current/i.test(activeTab.className) ||
                        activeTab.getAttribute('aria-selected') === 'true'
                } : null
            };
        }""",
        {"inputs": inputs or {}, "tab": tab, "includeText": include_text, "texts": texts or {}},
    )


def first_visible(page: Page, selector: str):
    """Select before probing: avoid count + nth + visibility round trips."""
    return page.locator(selector).filter(visible=True).first
