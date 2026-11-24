(() => {
    const key = "vision-action-theme";
    const root = document.documentElement;
    const read = () => {
        try { return localStorage.getItem(key) === "dark" ? "dark" : "light"; }
        catch { return "light"; }
    };
    const apply = (theme) => {
        root.dataset.theme = theme;
        document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
            button.setAttribute("aria-pressed", String(theme === "dark"));
            button.hidden = false;
        });
    };

    // Set the root attribute before the browser renders the page.
    apply(read());
    document.addEventListener("DOMContentLoaded", () => apply(read()));
    document.addEventListener("click", (event) => {
        if (!event.target.closest("[data-theme-toggle]")) return;
        const next = root.dataset.theme === "dark" ? "light" : "dark";
        try { localStorage.setItem(key, next); } catch { /* Session-only toggle. */ }
        apply(next);
    });
    window.addEventListener("storage", (event) => {
        if (event.key === key || event.key === null) apply(read());
    });
})();
