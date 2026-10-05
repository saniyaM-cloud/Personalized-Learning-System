const API_BASE = "http://127.0.0.1:5000";
const courseList = document.getElementById("courseList");
const learnerTable = document.getElementById("learnerTable");
const pageMessage = document.getElementById("pageMessage");
let coursesData = [];
let learnersData = [];

function makeCell(row, value) {
    const td = document.createElement("td");
    td.textContent = value == null || value === "" ? "—" : String(value);
    row.append(td);
    return td;
}

async function request(url, options = {}) {
    const response = await fetch(`${API_BASE}${url}`, {
        credentials: "include",
        headers: { Accept: "application/json", ...(options.body && !(options.body instanceof FormData) ? { "Content-Type": "application/json" } : {}) },
        ...options
    });
    const result = await response.json().catch(() => ({}));
    if (response.status === 401) {
        window.location.replace("login.html");
        throw new Error("Please sign in to continue.");
    }
    if (response.status === 403) {
        window.location.replace("login.html");
        throw new Error("This page is available to teacher accounts.");
    }
    if (!response.ok || result.success === false) throw new Error(result.message || "Could not load the teacher dashboard.");
    return result;
}

function formatFileSize(size) {
    const bytes = Number(size) || 0;
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function loadMaterials() {
    const container = document.getElementById("materialsList");
    try {
        const result = await request("/api/teacher/materials");
        container.replaceChildren();
        if (!result.materials.length) {
            const empty = document.createElement("div");
            empty.className = "message";
            empty.textContent = "No materials uploaded yet.";
            container.append(empty);
            return;
        }
        result.materials.forEach((material) => {
            const row = document.createElement("article");
            row.className = "material-row";
            const name = document.createElement("div");
            name.className = "material-name";
            const title = document.createElement("strong");
            title.textContent = `${material.title} · ${material.material_type === "video" ? "Video" : "Notes"}`;
            const meta = document.createElement("span");
            meta.textContent = `${material.course_title} · ${material.original_filename} · ${formatFileSize(material.file_size)}`;
            name.append(title, meta);
            const actions = document.createElement("div");
            actions.className = "material-actions";
            const view = document.createElement("a");
            view.className = "material-link";
            view.href = `${API_BASE}${material.download_url}`;
            view.target = "_blank";
            view.rel = "noopener";
            view.textContent = material.material_type === "video" ? "Preview video" : "Download notes";
            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "remove-material";
            remove.textContent = "Remove";
            remove.addEventListener("click", () => removeMaterial(material, remove));
            actions.append(view, remove);
            row.append(name, actions);
            container.append(row);
        });
    } catch (error) {
        container.replaceChildren();
        const message = document.createElement("div");
        message.className = "message error";
        message.textContent = error.message || "Unable to load course materials.";
        container.append(message);
    }
}

async function removeMaterial(material, button) {
    if (!window.confirm(`Remove “${material.title}” from ${material.course_title}? Students will no longer be able to access it.`)) return;
    button.disabled = true;
    try {
        const result = await request(`/api/teacher/materials/${material.material_id}`, { method: "DELETE" });
        const message = document.getElementById("uploadMessage");
        message.classList.remove("error");
        message.textContent = result.message;
        await loadMaterials();
    } catch (error) {
        button.disabled = false;
        const message = document.getElementById("uploadMessage");
        message.classList.add("error");
        message.textContent = error.message || "Unable to remove this material.";
    }
}

function renderCourses() {
    courseList.replaceChildren();
    const filter = document.getElementById("courseFilter");
    const selectedCourse = filter.value;
    filter.replaceChildren(new Option("All your courses", "all"));
    coursesData.forEach((course) => filter.add(new Option(course.title, String(course.course_id))));
    filter.value = coursesData.some((course) => String(course.course_id) === selectedCourse) ? selectedCourse : "all";

    if (!coursesData.length) {
        const empty = document.createElement("div");
        empty.className = "message";
        empty.textContent = "No courses are assigned to your account yet. Ask an administrator to assign you to a course.";
        courseList.append(empty);
        return;
    }

    coursesData.forEach((course) => {
        const card = document.createElement("article");
        card.className = "course-card";
        const title = document.createElement("h3");
        title.textContent = course.title;
        const subject = document.createElement("p");
        subject.textContent = `${course.subject || "General subject"} · ${course.difficulty || "Level not set"}`;
        const meta = document.createElement("div");
        meta.className = "course-meta";
        const students = document.createElement("span");
        students.className = "tag";
        students.textContent = `${course.student_count} active ${Number(course.student_count) === 1 ? "student" : "students"}`;
        const quizzes = document.createElement("span");
        quizzes.className = "tag green";
        quizzes.textContent = `${course.quiz_count} ${Number(course.quiz_count) === 1 ? "quiz" : "quizzes"}`;
        meta.append(students, quizzes);
        card.append(title, subject, meta);
        courseList.append(card);
    });
}

function renderQuizAttempts(learner) {
    const container = document.createElement("div");
    const attempts = learner.quiz_attempts || [];
    const summary = document.createElement("summary");
    summary.className = "quiz-summary";
    summary.textContent = `${learner.quizzes_taken} submitted · ${learner.graded_quizzes} graded · View marks`;
    container.append(summary);

    const list = document.createElement("div");
    list.className = "quiz-list";
    if (!attempts.length) {
        const none = document.createElement("p");
        none.textContent = "No quiz attempts for this course yet.";
        list.append(none);
    } else {
        attempts.forEach((attempt) => {
            const line = document.createElement("p");
            const mark = attempt.score == null ? `Not marked (${attempt.status})` : `${Number(attempt.score)}% · ${attempt.status}`;
            line.textContent = `${attempt.quiz_title} · Attempt ${attempt.attempt_number} · ${mark}`;
            list.append(line);
        });
    }
    container.append(list);
    return container;
}

function renderLearners() {
    const query = document.getElementById("studentSearch").value.trim().toLowerCase();
    const selectedCourse = document.getElementById("courseFilter").value;
    const filtered = learnersData.filter((learner) => {
        const matchesSearch = !query || `${learner.full_name} ${learner.email} ${learner.course_title}`.toLowerCase().includes(query);
        return matchesSearch && (selectedCourse === "all" || String(learner.course_id) === selectedCourse);
    });
    document.getElementById("learnerCount").textContent = `Showing ${filtered.length} course enrollment${filtered.length === 1 ? "" : "s"}`;
    learnerTable.replaceChildren();
    if (!filtered.length) {
        const empty = document.createElement("div");
        empty.className = "message";
        empty.textContent = learnersData.length ? "No student enrollments match these filters." : "Students enrolled in your courses will appear here.";
        learnerTable.append(empty);
        return;
    }

    const table = document.createElement("table");
    const head = document.createElement("thead");
    const heading = document.createElement("tr");
    ["Student", "Course", "Enrollment", "Lesson progress", "Quiz attempts and marks"].forEach((label) => {
        const th = document.createElement("th");
        th.textContent = label;
        heading.append(th);
    });
    head.append(heading);
    const body = document.createElement("tbody");
    filtered.forEach((learner) => {
        const row = document.createElement("tr");
        const person = document.createElement("td");
        person.className = "person";
        const name = document.createElement("strong");
        name.textContent = learner.full_name;
        const email = document.createElement("span");
        email.textContent = learner.email;
        person.append(name, email);
        row.append(person);
        makeCell(row, learner.course_title);

        const statusCell = document.createElement("td");
        const status = document.createElement("span");
        status.className = learner.enrollment_status === "active" ? "status" : "status inactive";
        status.textContent = learner.enrollment_status;
        statusCell.append(status);
        row.append(statusCell);

        const progressCell = document.createElement("td");
        const percentage = Math.max(0, Math.min(100, Number(learner.lesson_completion) || 0));
        const progressValue = document.createElement("div");
        progressValue.className = "progress-value";
        const lessonCount = document.createElement("span");
        lessonCount.textContent = `${learner.completed_lessons}/${learner.total_lessons} lessons`;
        const percent = document.createElement("strong");
        percent.textContent = `${percentage}%`;
        progressValue.append(lessonCount, percent);
        const track = document.createElement("div");
        track.className = "progress-track";
        const fill = document.createElement("div");
        fill.className = "progress-fill";
        fill.style.width = `${percentage}%`;
        track.append(fill);
        progressCell.append(progressValue, track);
        row.append(progressCell);

        const quizCell = document.createElement("td");
        const quizDetails = document.createElement("details");
        quizDetails.append(renderQuizAttempts(learner));
        quizCell.append(quizDetails);
        row.append(quizCell);
        body.append(row);
    });
    table.append(head, body);
    learnerTable.append(table);
}

async function loadTeacherDashboard() {
    try {
        const result = await request("/api/teacher/dashboard");
        coursesData = result.courses || [];
        learnersData = result.learners || [];
        document.getElementById("teacherIdentity").textContent = result.teacher?.full_name || "Teacher";
        document.getElementById("courseCount").textContent = coursesData.length;
        document.getElementById("enrollmentCount").textContent = coursesData.reduce((total, course) => total + Number(course.student_count || 0), 0);
        document.getElementById("quizCount").textContent = learnersData.reduce((total, learner) => total + Number(learner.quizzes_taken || 0), 0);
        const materialCourse = document.getElementById("materialCourse");
        materialCourse.replaceChildren(new Option(coursesData.length ? "Choose a course" : "No assigned courses", ""));
        coursesData.forEach((course) => materialCourse.add(new Option(course.title, String(course.course_id))));
        materialCourse.disabled = !coursesData.length;
        renderCourses();
        renderLearners();
        await loadMaterials();
    } catch (error) {
        pageMessage.classList.add("error");
        pageMessage.textContent = error.message || "Unable to load your teaching dashboard.";
    }
}

document.getElementById("studentSearch").addEventListener("input", renderLearners);
document.getElementById("courseFilter").addEventListener("change", renderLearners);
const materialType = document.getElementById("materialType");
const materialFile = document.getElementById("materialFile");
const fileHint = document.getElementById("fileHint");
function updateAcceptedFiles() {
    if (materialType.value === "video") {
        materialFile.accept = ".mp4,.webm,.mov,.m4v";
        fileHint.textContent = "Videos: MP4, WebM, MOV, or M4V. Maximum file size: 512 MB.";
    } else {
        materialFile.accept = ".pdf,.doc,.docx,.ppt,.pptx,.txt,.md";
        fileHint.textContent = "Notes: PDF, DOC, DOCX, PPT, PPTX, TXT, or MD. Maximum file size: 512 MB.";
    }
    materialFile.value = "";
}
materialType.addEventListener("change", updateAcceptedFiles);
document.getElementById("uploadForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = document.getElementById("uploadButton");
    const message = document.getElementById("uploadMessage");
    const file = materialFile.files[0];
    if (!file) return;
    if (file.size > 512 * 1024 * 1024) {
        message.classList.add("error");
        message.textContent = "Choose a file smaller than 512 MB.";
        return;
    }
    button.disabled = true;
    button.textContent = "Uploading…";
    message.classList.remove("error");
    message.textContent = "Uploading course material…";
    try {
        const result = await request("/api/teacher/materials", { method: "POST", body: new FormData(form) });
        message.textContent = result.message;
        form.reset();
        updateAcceptedFiles();
        await loadMaterials();
    } catch (error) {
        message.classList.add("error");
        message.textContent = error.message || "Unable to upload this file.";
    } finally {
        button.disabled = false;
        button.textContent = "Upload material";
    }
});
document.getElementById("logoutButton").addEventListener("click", async () => {
    const button = document.getElementById("logoutButton");
    button.disabled = true;
    try {
        await request("/api/logout", { method: "POST" });
    } catch (error) {
        console.error("Sign out error:", error);
    }
    window.location.replace("login.html");
});

loadTeacherDashboard();
