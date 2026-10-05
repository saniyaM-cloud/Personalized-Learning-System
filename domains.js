"use strict";

const DOMAIN_API = "http://127.0.0.1:5000";
const domainOptions = [
    { name: "Programming", examples: "C, C++, Java, Python", keywords: ["programming", "python", "java", "c++", "c programming"] },
    { name: "Data Structures & Algorithms", examples: "DSA, Algorithms", keywords: ["data structures", "algorithm", "dsa"] },
    { name: "Database Management", examples: "DBMS, SQL, MySQL, MongoDB", keywords: ["database", "dbms", "sql", "mysql", "mongodb"] },
    { name: "Web Development", examples: "HTML, CSS, JS, React, Node", keywords: ["web development", "html", "css", "javascript", "react", "node"] },
    { name: "AI & Machine Learning", examples: "ML, DL, NLP, CV", keywords: ["artificial intelligence", "machine learning", "deep learning", "nlp", "computer vision"] },
    { name: "Data Science & Analytics", examples: "Statistics, Pandas, NumPy", keywords: ["data science", "analytics", "statistics", "pandas", "numpy"] },
    { name: "Cloud Computing", examples: "AWS, Azure, GCP", keywords: ["cloud computing", "aws", "azure", "gcp"] },
    { name: "Cybersecurity", examples: "Security, Cryptography, Ethical Hacking", keywords: ["cybersecurity", "security", "cryptography", "ethical hacking"] },
    { name: "Computer Networks", examples: "TCP/IP, Networking", keywords: ["computer networks", "networking", "tcp/ip"] },
    { name: "Operating Systems", examples: "Linux, OS concepts", keywords: ["operating systems", "linux", "os concepts"] },
    { name: "Software Engineering & DevOps", examples: "SDLC, Testing, Git, Docker", keywords: ["software engineering", "devops", "sdlc", "testing", "git", "docker"] }
];
const domainSelect = document.getElementById("domainSelect");
const results = document.getElementById("domainResults");
const examples = document.getElementById("domainExamples");
const resultCount = document.getElementById("domainResultsCount");
const domainMessage = document.getElementById("domainMessage");
let courses = [];

domainOptions.forEach((domain, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = domain.name;
    domainSelect.append(option);
});

function matchesDomain(course, domain) {
    const searchableText = `${course.title || ""} ${course.subject || ""} ${course.description || ""}`.toLowerCase();
    return domain.keywords.some((keyword) => {
        if (/^[a-z]+$/.test(keyword) && keyword.length <= 4) return new RegExp(`\\b${keyword}\\b`).test(searchableText);
        return searchableText.includes(keyword);
    });
}

function createCourseCard(course) {
    const card = document.createElement("article");
    card.className = "course-card";
    const title = document.createElement("h2");
    title.textContent = course.title;
    const description = document.createElement("p");
    description.textContent = course.description || "Explore this course and build a new skill.";
    const meta = document.createElement("div");
    meta.className = "course-meta";
    meta.textContent = `${course.subject || "Subject"} · ${course.difficulty || "All levels"}`;
    card.append(title, description, meta);
    if (["active", "completed"].includes(course.enrollment_status)) {
        const status = document.createElement("span");
        status.className = "status";
        status.textContent = course.enrollment_status === "completed" ? "Completed" : "Enrolled";
        card.append(status);
    } else {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "course-action";
        button.textContent = "Enroll in course";
        button.addEventListener("click", () => enroll(course.course_id, button));
        card.append(button);
    }
    return card;
}

function renderDomainResults() {
    const selected = domainSelect.value === "all" ? null : domainOptions[Number(domainSelect.value)];
    const matching = selected ? courses.filter((course) => matchesDomain(course, selected)) : courses;
    examples.textContent = selected ? `Examples: ${selected.examples}.` : "Browse courses from all domains.";
    resultCount.textContent = `${matching.length} course${matching.length === 1 ? "" : "s"} found`;
    results.replaceChildren();
    if (!matching.length) {
        const empty = document.createElement("p");
        empty.className = "message";
        empty.textContent = selected ? `No courses are available in ${selected.name} yet.` : "No courses are available right now.";
        results.append(empty);
        return;
    }
    matching.forEach((course) => results.append(createCourseCard(course)));
}

async function loadDomainCourses() {
    try {
        const response = await fetch(`${DOMAIN_API}/api/courses`, { credentials: "include", headers: { Accept: "application/json" } });
        if (response.status === 401) return window.location.replace("login.html");
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error(result.message || "Could not load the course catalog.");
        courses = result.courses || [];
        renderDomainResults();
    } catch (error) {
        results.replaceChildren();
        const message = document.createElement("p");
        message.className = "message error";
        message.textContent = error.message || "Could not load courses.";
        results.append(message);
    }
}

async function enroll(courseId, button) {
    button.disabled = true;
    button.textContent = "Enrolling...";
    domainMessage.textContent = "";
    try {
        const response = await fetch(`${DOMAIN_API}/api/enrollments`, {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify({ course_id: courseId })
        });
        if (response.status === 401) return window.location.replace("login.html");
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error(result.message || "Could not enroll in this course.");
        domainMessage.textContent = result.message || "You are enrolled in this course.";
        domainMessage.className = "message success";
        await loadDomainCourses();
    } catch (error) {
        button.disabled = false;
        button.textContent = "Enroll in course";
        domainMessage.textContent = error.message || "Could not enroll in this course.";
        domainMessage.className = "message error";
    }
}

domainSelect.addEventListener("change", renderDomainResults);
loadDomainCourses();
