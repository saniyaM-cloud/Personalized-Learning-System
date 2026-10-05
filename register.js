"use strict";

const registerForm = document.getElementById("registerForm");
const message = document.getElementById("message");
const registerButton = document.getElementById("registerButton");
const fullNameInput = document.getElementById("fullName");
const emailInput = document.getElementById("email");
const passwordInput = document.getElementById("password");
const confirmPasswordInput = document.getElementById("confirmPassword");
const termsInput = document.getElementById("terms");
const roleInput = document.getElementById("role");
const adminCodeInput = document.getElementById("adminCode");
const adminCodeField = document.getElementById("adminCodeField");
const fieldErrors = {
    fullName: document.getElementById("fullNameError"),
    email: document.getElementById("emailError"),
    password: document.getElementById("passwordError"),
    confirmPassword: document.getElementById("confirmPasswordError"),
    terms: document.getElementById("termsError"),
    role: document.getElementById("roleError"),
    adminCode: document.getElementById("adminCodeError")
};

if (!registerForm || !message || !registerButton || !fullNameInput || !emailInput ||
    !passwordInput || !confirmPasswordInput || !termsInput || !roleInput || !adminCodeInput || !adminCodeField) {
    throw new Error("The registration form is missing one or more required fields.");
}

message.setAttribute("role", "status");
message.setAttribute("aria-live", "polite");

const MIN_NAME_LENGTH = 2;
const MAX_NAME_LENGTH = 255;
const MAX_EMAIL_LENGTH = 254;
const MIN_PASSWORD_LENGTH = 8;
// bcrypt only uses the first 72 bytes; reject longer passwords instead of silently truncating.
const MAX_PASSWORD_BYTES = 72;
let isSubmitting = false;

function showMessage(text, type) {
    message.textContent = text;
    message.className = `message ${type}`;
}

function clearMessage() {
    message.textContent = "";
    message.className = "message";
}

function clearFieldError(fieldName, input) {
    fieldErrors[fieldName].textContent = "";
    input.removeAttribute("aria-invalid");
}

function clearAllFieldErrors() {
    clearFieldError("fullName", fullNameInput);
    clearFieldError("email", emailInput);
    clearFieldError("password", passwordInput);
    clearFieldError("confirmPassword", confirmPasswordInput);
    clearFieldError("terms", termsInput);
    clearFieldError("role", roleInput);
    clearFieldError("adminCode", adminCodeInput);
}

function normalizeEmail() {
    emailInput.value = emailInput.value.trim().toLowerCase();
}

function displayValidationError(error) {
    clearAllFieldErrors();
    fieldErrors[error.name].textContent = error.text;
    error.field.setAttribute("aria-invalid", "true");
    showMessage(error.text, "error");
    error.field.focus();
}

function getValidationError() {
    const fullName = fullNameInput.value.trim();
    normalizeEmail();
    const email = emailInput.value;
    const password = passwordInput.value;
    const confirmPassword = confirmPasswordInput.value;
    const role = roleInput.value;

    if (Array.from(fullName).length < MIN_NAME_LENGTH) {
        return { name: "fullName", field: fullNameInput, text: "Please enter your full name (at least 2 characters)." };
    }
    if (Array.from(fullName).length > MAX_NAME_LENGTH) {
        return { name: "fullName", field: fullNameInput, text: "Your name must be 255 characters or fewer." };
    }
    if (!/\p{L}/u.test(fullName) || !/^[\p{L}\p{M} .'-\u2019]+$/u.test(fullName)) {
        return { name: "fullName", field: fullNameInput, text: "Use letters, spaces, apostrophes, hyphens, or periods for your name." };
    }
    if (!email) {
        return { name: "email", field: emailInput, text: "Please enter your email address." };
    }
    if (email.length > MAX_EMAIL_LENGTH || !emailInput.checkValidity()) {
        return { name: "email", field: emailInput, text: "Please enter a valid email address (254 characters or fewer)." };
    }
    if (Array.from(password).length < MIN_PASSWORD_LENGTH) {
        return { name: "password", field: passwordInput, text: "Your password must be at least 8 characters." };
    }
    if (new TextEncoder().encode(password).length > MAX_PASSWORD_BYTES) {
        return { name: "password", field: passwordInput, text: "Your password is too long. Use 72 UTF-8 bytes or fewer." };
    }
    if (password !== confirmPassword) {
        return { name: "confirmPassword", field: confirmPasswordInput, text: "Passwords do not match." };
    }
    if (!["student", "teacher", "admin"].includes(role)) {
        return { name: "role", field: roleInput, text: "Choose a valid account type." };
    }
    if (role === "admin" && !adminCodeInput.value.trim()) {
        return { name: "adminCode", field: adminCodeInput, text: "Enter the admin invite code." };
    }
    if (!termsInput.checked) {
        return { name: "terms", field: termsInput, text: "Please accept the Terms of Service and Privacy Policy." };
    }

    return null;
}

registerForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (isSubmitting) return;

    clearMessage();
    const validationError = getValidationError();
    if (validationError) {
        displayValidationError(validationError);
        return;
    }
    clearAllFieldErrors();

    isSubmitting = true;
    registerButton.disabled = true;
    registerButton.textContent = "Creating account…";

    try {
        const response = await fetch("http://127.0.0.1:5000/api/register", {
            method: "POST",
            headers: { "Content-Type": "application/json", "Accept": "application/json" },
            body: JSON.stringify({
                full_name: fullNameInput.value.trim(),
                email: emailInput.value.trim().toLowerCase(),
                password: passwordInput.value,
                role: roleInput.value,
                admin_code: adminCodeInput.value
            })
        });

        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
            showMessage(result.message || `Registration failed (HTTP ${response.status}).`, "error");
            return;
        }

        showMessage(result.message || "Account created successfully. You can now sign in.", "success");
        registerForm.reset();
        window.location.replace("login.html?registered=1");
    } catch (error) {
        console.error("Registration request failed:", error);
        showMessage("Unable to connect to the server. Check that Flask is running, then try again.", "error");
    } finally {
        isSubmitting = false;
        registerButton.disabled = false;
        registerButton.textContent = "Create account";
    }
});

const fields = [
    ["fullName", fullNameInput],
    ["email", emailInput],
    ["password", passwordInput],
    ["confirmPassword", confirmPasswordInput],
    ["terms", termsInput],
    ["role", roleInput],
    ["adminCode", adminCodeInput]
];

for (const [fieldName, input] of fields) {
    const clearField = () => {
        clearFieldError(fieldName, input);
        clearMessage();
    };
    input.addEventListener("input", clearField);
    input.addEventListener("change", clearField);
}

emailInput.addEventListener("blur", normalizeEmail);

roleInput.addEventListener("change", () => {
    adminCodeField.hidden = roleInput.value !== "admin";
    if (roleInput.value !== "admin") adminCodeInput.value = "";
    clearFieldError("role", roleInput);
    clearFieldError("adminCode", adminCodeInput);
    clearMessage();
});
