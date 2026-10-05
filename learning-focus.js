"use strict";

const focusForm = document.getElementById("focusForm");
const focusInput = document.getElementById("focusInput");
const focusMessage = document.getElementById("focusMessage");
const focusKey = "pls-learning-focus";

focusInput.value = localStorage.getItem(focusKey) || "";

focusForm.addEventListener("submit", (event) => {
    event.preventDefault();
    localStorage.setItem(focusKey, focusInput.value.trim());
    focusMessage.textContent = "Your learning focus has been saved.";
    focusMessage.className = "message success";
});

document.getElementById("clearFocus").addEventListener("click", () => {
    localStorage.removeItem(focusKey);
    focusInput.value = "";
    focusMessage.textContent = "Your learning focus has been cleared.";
    focusMessage.className = "message";
});
