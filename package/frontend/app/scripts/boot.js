let currentModule = null;
let currentHash = null;

const routes = {
    home: { html: "player.html", module: "player.js" },
    sketchpad: { html: "sketchpad.html", module: "sketchpad.js" },
    dashboard: { html: "dashboard.html", module: "dashboard.js" }
};

const common_resources = [
    { type: "text/javascript", url: "tiling.js" },
    { type: "text/javascript", url: "utils.js" }
];


async function loadHeadResources(resources) {
    for (const res of resources) {
        try {
            if (res.type === "css") {
                // Fetch CSS
                const response = await fetch(res.url);
                if (!response.ok) throw new Error(`Failed to fetch ${res.url}`);
                const cssText = await response.text();

                const style = document.createElement("style");
                style.textContent = cssText;
                document.head.appendChild(style);

            } else if (res.type === "text/javascript") {
                // Load normal JS via <script src> for global functions
                await new Promise((resolve, reject) => {
                    const script = document.createElement("script");
                    script.src = res.url;
                    script.type = "text/javascript";
                    script.async = false; // ensures sequential execution
                    script.onload = resolve;
                    script.onerror = () => reject(new Error(`Failed to load ${res.url}`));
                    document.head.appendChild(script);
                });

            } else if (res.type === "module") {
                // Load module JS
                await new Promise((resolve, reject) => {
                    const script = document.createElement("script");
                    script.src = res.url;
                    script.type = "module";
                    script.onload = resolve;
                    script.onerror = () => reject(new Error(`Failed to load ${res.url}`));
                    document.head.appendChild(script);
                });

            } else {
                console.warn(`Unknown resource type: ${res.type}`);
            }

        } catch (err) {
            console.error(err);
        }
    }
}

async function loadPage() {
    const hash = location.hash.replace("#", "") || "home";

    if (hash === currentHash) return; // already loaded

    if (routes[currentHash])
        document.getElementById(`subpage-nav-${currentHash}`).classList.remove("active");
    currentHash = hash;

    const route = routes[hash];
    if (!route) return;

    if (currentModule && currentModule.cleanup)
        currentModule.cleanup();

    try {
        const res = await fetch(route.html);
        if (!res.ok) throw new Error(`Failed to load ${route.html}`);
        document.getElementById("subpage-content").innerHTML = await res.text();
        document.getElementById(`subpage-nav-${hash}`).classList.add("active");

        currentModule = await import(`./${route.module}`);
        currentModule.main();
    } catch (err) {
        console.error(err);
        document.body.innerHTML = `<p>Failed to load ${hash}</p>`;
    }
}

loadHeadResources(common_resources);
window.addEventListener("hashchange", loadPage);
window.addEventListener("load", loadPage);
