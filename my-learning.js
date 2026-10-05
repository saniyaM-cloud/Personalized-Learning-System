"use strict";

const LEARNING_API = "http://127.0.0.1:5000";
const results = document.getElementById("myLearningResults");

function addResourceLink(container, label, url) {
    const link = document.createElement("a");
    link.href = url;
    link.textContent = label;
    container.append(link);
}

function createCourseCard(course) {
    const card = document.createElement("article");
    card.className = "course-card";
    const title = document.createElement("h3");
    title.textContent = course.title;
    const status = document.createElement("span");
    status.className = "status";
    status.textContent = course.enrollment_status === "completed" ? "Completed" : "Enrolled";
    const description = document.createElement("p");
    description.textContent = course.description || "Your learning materials and quizzes are here.";
    const meta = document.createElement("div");
    meta.className = "course-meta";
    meta.textContent = `${course.subject || "Subject"} · ${course.difficulty || "All levels"}`;
    card.append(title, status, description, meta);

    const materials = course.materials || [];
    const materialSection = document.createElement("div");
    materialSection.className = "resource";
    const materialHeading = document.createElement("strong");
    materialHeading.textContent = `Materials (${materials.length})`;
    materialSection.append(materialHeading);
    materials.forEach((material) => {
        const item = document.createElement("div");
        item.className = "resource";
        const label = document.createElement("strong");
        label.textContent = `${material.title} · ${material.material_type === "video" ? "Video" : "Notes"}`;
        item.append(label);
        const url = `${LEARNING_API}${material.download_url}`;
        if (material.material_type === "video") {
            const video = document.createElement("video");
            video.controls = true;
            video.preload = "metadata";
            video.src = url;
            video.setAttribute("aria-label", material.title);
            item.append(video);
        } else {
            addResourceLink(item, `Download ${material.original_filename}`, url);
        }
        materialSection.append(item);
    });
    if (!materials.length) {
        const empty = document.createElement("p");
        empty.textContent = "No course materials have been added yet.";
        materialSection.append(empty);
    }
    card.append(materialSection);

    const quizzes = course.quizzes || [];
    const quizSection = document.createElement("div");
    quizSection.className = "resource";
    const quizHeading = document.createElement("strong");
    quizHeading.textContent = `Quizzes (${quizzes.length})`;
    quizSection.append(quizHeading);
    if (!quizzes.length) {
        const empty = document.createElement("p");
        empty.textContent = "No quizzes have been added yet.";
        quizSection.append(empty);
    }
    quizzes.forEach((quiz) => {
        const item = document.createElement("div");
        item.className = "resource";
        const heading = document.createElement("strong");
        heading.textContent = quiz.title;
        item.append(heading);
        if (quiz.description) {
            const descriptionText = document.createElement("p");
            descriptionText.textContent = quiz.description;
            item.append(descriptionText);
        }
        const attempts = quiz.attempts || [];
        const summary = document.createElement("p");
        summary.textContent = attempts.length
            ? `${attempts.length} attempt${attempts.length === 1 ? "" : "s"}`
            : "Not attempted yet";
        item.append(summary);
        attempts.forEach((attempt) => {
            const score = attempt.score == null ? attempt.status : `${Number(attempt.score)}% · ${attempt.status}`;
            const attemptLine = document.createElement("p");
            attemptLine.textContent = `Attempt ${attempt.attempt_number}: ${score}`;
            item.append(attemptLine);
        });
        quizSection.append(item);
    });
    card.append(quizSection);
    return card;
}

async function loadMyLearning() {
    try {
        const response = await fetch(`${LEARNING_API}/api/courses`, { credentials: "include", headers: { Accept: "application/json" } });
        if (response.status === 401) return window.location.replace("login.html");
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error(result.message || "Could not load your courses.");
        const enrolled = (result.courses || []).filter((course) => ["active", "completed"].includes(course.enrollment_status));
        results.replaceChildren();
        if (!enrolled.length) {
            const empty = document.createElement("p");
            empty.className = "message";
            empty.textContent = "You have not enrolled in a course yet. Explore domains to find a subject.";
            results.append(empty);
            return;
        }
        enrolled.forEach((course) => results.append(createCourseCard(course)));
    } catch (error) {
        results.replaceChildren();
        const message = document.createElement("p");
        message.className = "message error";
        message.textContent = error.message || "Could not load your courses.";
        results.append(message);
    }
}

loadMyLearning();
