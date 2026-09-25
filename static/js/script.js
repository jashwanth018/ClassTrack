const root = document.documentElement;
const themeToggle = document.querySelector(".theme-toggle");
const menuToggle = document.querySelector(".menu-toggle");
const navContent = document.querySelector(".nav-content");

// Restore the saved theme and keep the control text accessible.
function applyTheme(theme) {
    root.dataset.theme = theme;
    if (!themeToggle) return;
    const isDark = theme === "dark";
    themeToggle.setAttribute("aria-label", isDark ? "Switch to light theme" : "Switch to dark theme");
    themeToggle.querySelector(".theme-icon").textContent = isDark ? "☾" : "☼";
    themeToggle.querySelector(".theme-label").textContent = isDark ? "Dark mode" : "Light mode";
}

applyTheme(localStorage.getItem("classtrack-theme") || "light");

themeToggle?.addEventListener("click", () => {
    const nextTheme = root.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem("classtrack-theme", nextTheme);
    applyTheme(nextTheme);
});

menuToggle?.addEventListener("click", () => {
    const isOpen = navContent.classList.toggle("open");
    menuToggle.setAttribute("aria-expanded", String(isOpen));
});

const attendanceButtons = Array.from(document.querySelectorAll(".attendance-bubble"));
const totalNode = document.getElementById("attendance-total");
const presentNode = document.getElementById("attendance-present");
const absentNode = document.getElementById("attendance-absent");
const percentNode = document.getElementById("attendance-percent");
const attendanceSearch = document.getElementById("attendance-search");
const saveAttendanceButton = document.getElementById("save-attendance-button");
const attendanceMessage = document.getElementById("attendance-message");

function getStatusState(button) {
    return button.classList.contains("present") ? "present" : "absent";
}

function updateAttendanceStats() {
    if (!totalNode || !presentNode || !absentNode || !percentNode) return;

    const total = attendanceButtons.length;
    const present = attendanceButtons.filter((button) => getStatusState(button) === "present").length;
    const absent = total - present;
    const percentage = total === 0 ? 0 : (present / total) * 100;

    totalNode.textContent = String(total);
    presentNode.textContent = String(present);
    absentNode.textContent = String(absent);
    percentNode.textContent = `${percentage.toFixed(2)}%`;
}

function updateButtonAccessibility(button, status) {
    if (!button) return;
    const rollNumber = button.dataset.rollNumber || "Unknown roll number";
    const name = button.dataset.name || "student";
    const label = status === "present" ? "present" : "absent";
    button.setAttribute("aria-label", `Roll number ${rollNumber}, ${name}, currently ${label}`);
    button.setAttribute("aria-pressed", status === "present" ? "true" : "false");
}

function toggleButton(button) {
    if (!button) return;

    const nextState = getStatusState(button) === "present" ? "absent" : "present";
    button.classList.toggle("present", nextState === "present");
    button.classList.toggle("absent", nextState === "absent");
    updateButtonAccessibility(button, nextState);
    updateAttendanceStats();
}

attendanceButtons.forEach((button) => {
    updateButtonAccessibility(button, getStatusState(button));
    button.addEventListener("click", () => toggleButton(button));
});

updateAttendanceStats();

attendanceSearch?.addEventListener("input", (event) => {
    const query = (event.target.value || "").trim().toLowerCase();

    attendanceButtons.forEach((button) => {
        const fullRoll = (button.dataset.rollNumber || "").toLowerCase();
        const lastTwo = (button.dataset.displayLabel || "").toLowerCase();
        const name = (button.dataset.name || "").toLowerCase();
        const matches = !query || fullRoll.includes(query) || lastTwo.includes(query) || name.includes(query);
        button.classList.toggle("hidden", !matches);
    });
});

document.querySelector(".attendance-mark-all")?.addEventListener("click", () => {
    attendanceButtons.forEach((button) => {
        button.classList.remove("absent");
        button.classList.add("present");
        updateButtonAccessibility(button, "present");
    });
    updateAttendanceStats();
});

document.querySelector(".attendance-clear-all")?.addEventListener("click", () => {
    attendanceButtons.forEach((button) => {
        button.classList.remove("present");
        button.classList.add("absent");
        updateButtonAccessibility(button, "absent");
    });
    updateAttendanceStats();
});

const todayDate = document.getElementById("today-date");
const todayIsoDate = window.attendanceDate || new Date().toISOString().slice(0, 10);

if (todayDate) {
    const now = new Date();
    todayDate.textContent = now.toLocaleDateString("en-GB", {
        day: "numeric",
        month: "long",
        year: "numeric",
    });
}

const initialSavedAttendance = window.initialSavedAttendance || {};

attendanceButtons.forEach((button) => {
    const studentId = String(button.dataset.studentId || "");
    const savedStatus = initialSavedAttendance[studentId] || "absent";
    const finalStatus = savedStatus === "present" ? "present" : "absent";
    button.classList.toggle("present", finalStatus === "present");
    button.classList.toggle("absent", finalStatus === "absent");
    updateButtonAccessibility(button, finalStatus);
});

updateAttendanceStats();

saveAttendanceButton?.addEventListener("click", async () => {
    const payload = {
        date: todayIsoDate,
        attendance: attendanceButtons.map((button) => ({
            student_id: Number(button.dataset.studentId),
            status: getStatusState(button),
        })),
    };

    try {
        const response = await fetch("/api/attendance/save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify(payload),
        });

        const result = await response.json();

        if (!response.ok) {
            attendanceMessage.textContent = result.error || "Unable to save attendance.";
            return;
        }

        const displayDate = new Date(`${todayIsoDate}T00:00:00`).toLocaleDateString("en-GB", {
            day: "numeric",
            month: "long",
            year: "numeric",
        });

        attendanceMessage.textContent = `✓ Attendance saved successfully. Date: ${displayDate} Present: ${result.present} Absent: ${result.absent}`;
    } catch (error) {
        attendanceMessage.textContent = "Unable to save attendance right now.";
    }
});

const recordDateInput = document.getElementById("record-date");
const recordDateButton = document.getElementById("record-date-button");
const recordsSearch = document.getElementById("records-search");
const recordsStats = document.getElementById("records-stats");
const recordsLists = document.getElementById("records-lists");
const recordsEmpty = document.getElementById("records-empty");
const recordsNoData = document.getElementById("records-no-data");
const recordsNoDataText = document.getElementById("records-no-data-text");
const recordsMessage = document.getElementById("records-message");
const copyFullReportButton = document.getElementById("copy-full-report-button");
const copyAbsenteesButton = document.getElementById("copy-absentees-button");
const presentRecordsList = document.getElementById("records-present-list");
const absentRecordsList = document.getElementById("records-absent-list");
let currentRecords = [];
let currentRecordsDate = "";
let currentRecordsSummary = null;
let copyMessageTimer;

function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, (character) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "'": "&#39;",
        "\"": "&quot;",
    }[character]));
}

function renderRecordList(container, records) {
    if (!container) return;
    container.innerHTML = records.map((record) => (
        `<span class="record-item" data-roll-number="${escapeHtml(record.roll_number.toLowerCase())}" data-name="${escapeHtml(record.name.toLowerCase())}">${escapeHtml(record.roll_number.slice(-2))}</span>`
    )).join("");
}

function filterRecords() {
    const query = (recordsSearch?.value || "").trim().toLowerCase();
    document.querySelectorAll(".record-item").forEach((item) => {
        const matches = !query
            || item.dataset.rollNumber.includes(query)
            || item.dataset.name.includes(query)
            || item.textContent.toLowerCase().includes(query);
        item.classList.toggle("hidden", !matches);
    });
}

function buildRecordsReport() {
    const present = currentRecords.filter((record) => record.status === "present").map((record) => record.roll_number.slice(-2));
    const absent = currentRecords.filter((record) => record.status === "absent").map((record) => record.roll_number.slice(-2));
    const total = currentRecordsSummary.total;
    const presentCount = present.length;
    const absentCount = absent.length;
    const percentage = total ? ((presentCount / total) * 100).toFixed(2) : "0.00";
    return `ClassTrack Attendance\n\nDate: ${currentRecordsDate}\n\nPresent: ${present.join(", ")}\n\nAbsent: ${absent.join(", ")}\n\nTotal Students: ${total}\nPresent: ${presentCount}\nAbsent: ${absentCount}\nAttendance: ${percentage}%`;
}

function buildAbsenteesReport() {
    const absent = currentRecords
        .filter((record) => record.status === "absent")
        .map((record) => record.roll_number.slice(-2));
    const [year, month, day] = recordDateInput.value.split("-");
    const formattedDate = `${day}-${month}-${year}`;
    return `${formattedDate} Absentees: ${absent.length ? absent.join(", ") : "None"}`;
}

async function copyText(text, successMessage) {
    if (!currentRecords.length) return;
    try {
        if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(text);
        } else {
            const fallback = document.createElement("textarea");
            fallback.value = text;
            document.body.appendChild(fallback);
            fallback.select();
            document.execCommand("copy");
            fallback.remove();
        }
        recordsMessage.textContent = successMessage;
        clearTimeout(copyMessageTimer);
        copyMessageTimer = setTimeout(() => { recordsMessage.textContent = ""; }, 3500);
    } catch (error) {
        recordsMessage.textContent = "Unable to copy the attendance report.";
    }
}

function copyFullReport() {
    copyText(buildRecordsReport(), "✓ Attendance report copied to clipboard.");
}

function copyAbsenteesOnly() {
    copyText(buildAbsenteesReport(), "✓ Absentee list copied to clipboard.");
}

async function loadRecords() {
    const selectedDate = recordDateInput?.value;
    if (!selectedDate) {
        recordsMessage.textContent = "Please select a date first.";
        return;
    }

    try {
        const response = await fetch(`/api/records/${selectedDate}`, { credentials: "same-origin" });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Unable to load records.");

        recordsEmpty.hidden = true;
        recordsNoData.hidden = result.has_records;
        recordsStats.hidden = !result.has_records;
        recordsLists.hidden = !result.has_records;
        copyFullReportButton.disabled = !result.has_records;
        copyAbsenteesButton.disabled = !result.has_records;
        recordsSearch.disabled = !result.has_records;
        recordsMessage.textContent = "";

        if (!result.has_records) {
            recordsNoDataText.textContent = `No attendance recorded for ${result.date}.`;
            currentRecords = [];
            currentRecordsDate = "";
            currentRecordsSummary = null;
            return;
        }

        currentRecords = result.records;
        currentRecordsDate = result.date;
        currentRecordsSummary = result.summary;
        document.getElementById("records-total").textContent = result.summary.total;
        document.getElementById("records-present").textContent = result.summary.present;
        document.getElementById("records-absent").textContent = result.summary.absent;
        document.getElementById("records-percentage").textContent = `${result.summary.percentage.toFixed(2)}%`;
        document.getElementById("records-present-count").textContent = result.summary.present;
        document.getElementById("records-absent-count").textContent = result.summary.absent;
        renderRecordList(presentRecordsList, currentRecords.filter((record) => record.status === "present"));
        renderRecordList(absentRecordsList, currentRecords.filter((record) => record.status === "absent"));
        filterRecords();
    } catch (error) {
        recordsMessage.textContent = error.message || "Unable to load attendance records.";
    }
}

recordDateButton?.addEventListener("click", loadRecords);
recordsSearch?.addEventListener("input", filterRecords);
copyFullReportButton?.addEventListener("click", copyFullReport);
copyAbsenteesButton?.addEventListener("click", copyAbsenteesOnly);
