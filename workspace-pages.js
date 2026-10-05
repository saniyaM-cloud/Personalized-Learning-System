"use strict";

const WORKSPACE_API = "http://127.0.0.1:5000";

async function initializeWorkspacePage() {
    try {
        const response = await fetch(`${WORKSPACE_API}/api/dashboard`, {
            credentials: "include",
            headers: { Accept: "application/json" }
        });
        if (response.status === 401) return window.location.replace("login.html");
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error(result.message || "Could not load your account.");
        if (result.role === "teacher") return window.location.replace("teacher-dashboard.html");
        if (result.role === "admin") return window.location.replace("admin.html");
        const name = result.user?.full_name || "Learner";
        const nameTarget = document.getElementById("sidebarName");
        const emailTarget = document.getElementById("sidebarEmail");
        if (nameTarget) nameTarget.textContent = name;
        if (emailTarget) emailTarget.textContent = result.user?.email || "Signed in";
    } catch (error) {
        console.error("Workspace page error:", error);
        const target = document.querySelector("[data-page-message]");
        if (target) {
            target.textContent = "Could not connect to your account. Check that the Flask server is running.";
            target.classList.add("error");
        }
    }
}

document.getElementById("workspaceLogout")?.addEventListener("click", async () => {
    try {
        await fetch(`${WORKSPACE_API}/api/logout`, { method: "POST", credentials: "include" });
    } catch (error) {
        console.error("Sign out error:", error);
    } finally {
        window.location.replace("login.html");
    }
});

initializeWorkspacePage();
