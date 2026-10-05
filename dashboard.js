const API_BASE = "http://127.0.0.1:5000";

const firstName = document.getElementById("firstName");
const sidebarName = document.getElementById("sidebarName");
const sidebarEmail = document.getElementById("sidebarEmail");
const sidebarAvatar = document.getElementById("sidebarAvatar");
const logoutButton = document.getElementById("logoutButton");
const adminDashboardButton = document.getElementById("adminDashboardButton");

function initials(name) {
    return name
        .trim()
        .split(/\s+/)
        .slice(0, 2)
        .map((part) => part[0])
        .join("")
        .toUpperCase();
}

function formatLearningTime(seconds) {
    const totalMinutes = Math.floor((Number(seconds) || 0) / 60);
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    if (hours && minutes) return `${hours}h ${minutes}m`;
    if (hours) return `${hours}h`;
    return `${minutes}m`;
}

function showConnectionError(message) {
    document.querySelector(".content").innerHTML = `
        <section class="panel" style="max-width:560px;margin:70px auto;padding:32px;text-align:center">
            <div class="empty-illustration" style="margin:0 auto 14px" aria-hidden="true">!</div>
            <h1 style="font-size:23px">We couldn’t load your dashboard</h1>
            <p class="subtitle">${message}</p>
            <a class="text-link" href="login.html">Return to sign in →</a>
        </section>`;
}

async function loadDashboard() {
    try {
        const response = await fetch(`${API_BASE}/api/dashboard`, {
            method: "GET",
            credentials: "include",
            headers: { "Accept": "application/json" }
        });

        if (response.status === 401) {
            window.location.replace("login.html");
            return;
        }
        if (!response.ok) throw new Error("The server returned an error. Please try again.");

        const result = await response.json();
        if (!result.success || !result.user) throw new Error("Your account details could not be found.");
        if (result.role === "teacher") {
            window.location.replace("teacher-dashboard.html");
            return;
        }
        adminDashboardButton.hidden = result.role !== "admin";

        const summary = result.summary || {};
        document.getElementById("activeCourseCount").textContent = summary.active_courses ?? 0;
        document.getElementById("learningTimeValue").textContent = formatLearningTime(summary.study_seconds);
        document.getElementById("completedLessonCount").textContent = summary.completed_lessons ?? 0;

        const { full_name: fullName, email } = result.user;
        const name = fullName || "Learner";
        firstName.textContent = name.trim().split(/\s+/)[0];
        sidebarName.textContent = name;
        sidebarEmail.textContent = email || "Signed in";
        sidebarAvatar.textContent = initials(name) || "L";
    } catch (error) {
        console.error("Dashboard error:", error);
        showConnectionError("Make sure the Flask server is running, then sign in again.");
    }
}

logoutButton.addEventListener("click", async () => {
    logoutButton.disabled = true;
    try {
        await fetch(`${API_BASE}/api/logout`, {
            method: "POST",
            credentials: "include",
            headers: { "Accept": "application/json" }
        });
    } catch (error) {
        console.error("Sign out error:", error);
    } finally {
        window.location.replace("login.html");
    }
});

const now = new Date();
document.getElementById("todayLabel").textContent = new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric" }).format(now);
document.getElementById("fullDate").textContent = new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" }).format(now);

loadDashboard();
