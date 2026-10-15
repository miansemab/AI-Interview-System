document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("speakerEnrollmentForm");
    const consent = document.getElementById("speakerConsent");
    const recordButton = document.getElementById("recordReferenceSample");
    const submitButton = document.getElementById("enrollSpeakerButton");
    const retryButton = document.getElementById("retryReferenceSamples");
    const status = document.getElementById("enrollmentStatus");
    const count = document.getElementById("referenceSampleCount");
    if (!form || !consent || !recordButton || !submitButton || !retryButton || !status || !count) return;

    const samples = [];
    let busy = false;
    const idleRecordLabel = "Record reference sample";

    function showStatus(message, kind = "muted") {
        status.textContent = message;
        status.classList.remove("error-message", "success-message", "muted");
        status.classList.add(kind);
    }

    function updateControls() {
        consent.disabled = busy;
        recordButton.disabled = busy || !consent.checked || samples.length >= 2;
        submitButton.disabled = busy || !consent.checked || samples.length !== 2;
        retryButton.disabled = busy;
        form.classList.toggle("enrollment-busy", busy);
        recordButton.textContent = samples.length >= 2
            ? "Two reference samples ready"
            : `${idleRecordLabel} ${samples.length + 1} of 2`;
        submitButton.textContent = busy && submitButton.dataset.submitting === "true"
            ? "Enrolling…"
            : "Enroll voice and begin interview";
    }

    consent.addEventListener("change", () => {
        if (!consent.checked && samples.length) {
            samples.length = 0;
            count.textContent = "0 / 2 samples recorded";
            showStatus("Consent was withdrawn. The reference samples were cleared from this page.");
        } else if (consent.checked) {
            showStatus("Consent recorded for this interview. Choose Record reference sample 1 of 2 to request microphone access.");
        }
        updateControls();
    });

    retryButton.addEventListener("click", () => {
        if (busy) return;
        samples.length = 0;
        count.textContent = "0 / 2 samples recorded";
        showStatus(consent.checked
            ? "Samples cleared from this page. Record two new samples."
            : "Samples cleared. Agree to voice processing before recording.");
        updateControls();
    });

    recordButton.addEventListener("click", async () => {
        if (busy || !consent.checked || samples.length >= 2) return;
        busy = true;
        status.classList.remove("error-message", "success-message");
        showStatus("Requesting microphone access. Approve the browser prompt to begin recording.");
        updateControls();
        try {
            if (!window.SpeakerCapture || typeof window.SpeakerCapture.record !== "function") {
                throw new Error("Audio capture did not load. Refresh this page; if it continues, contact the interview administrator.");
            }
            const wav = await window.SpeakerCapture.record(6, status);
            if (!(wav instanceof Blob) || wav.size <= 44) {
                throw new Error("The microphone returned an empty recording. Check that it is not muted, then try again.");
            }
            samples.push(wav);
            count.textContent = `${samples.length} / 2 samples recorded`;
            if (samples.length < 2) {
                showStatus("Sample 1 of 2 recorded successfully. Record the second sample when ready.", "success-message");
            } else {
                showStatus("Both samples are ready. Submit to check audio quality and enroll.", "success-message");
            }
        } catch (error) {
            showStatus(error.message || "Recording failed. Check microphone access and retry.", "error-message");
        } finally {
            busy = false;
            updateControls();
        }
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (busy) return;
        if (!consent.checked) {
            showStatus("Consent is required before reference voice samples can be sent.", "error-message");
            return;
        }
        if (samples.length !== 2) {
            showStatus("Record both reference samples before enrolling.", "error-message");
            return;
        }
        // Build the payload while the consent checkbox is still enabled.
        // Disabled controls are excluded from FormData, so constructing it
        // after updateControls() would silently omit the acknowledgement.
        const consentValue = consent.checked ? consent.value : "";
        const body = new FormData(form);
        if (consentValue !== "on" || body.get("consent") !== consentValue) {
            showStatus("Consent is required before reference voice samples can be sent.", "error-message");
            return;
        }
        // Preserve the exact checked checkbox value the endpoint requires.
        body.set("consent", consentValue);

        busy = true;
        submitButton.dataset.submitting = "true";
        showStatus("Uploading and checking both samples. Please wait…");
        updateControls();
        samples.forEach((sample, index) => {
            body.append(`reference_sample_${index + 1}`, sample, `reference-${index + 1}.wav`);
        });

        try {
            const response = await fetch(form.action, {
                method: "POST",
                body,
                credentials: "same-origin",
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });
            const responseText = await response.text();
            let payload;
            try {
                payload = JSON.parse(responseText);
            } catch (error) {
                throw new Error(response.status === 403
                    ? "The enrollment request was denied. Refresh the page and check that this interview is still open."
                    : `The server returned an unreadable response (${response.status}). Your samples remain in this page; retry or clear them.`);
            }
            if (!response.ok) {
                throw new Error(payload.error || `Enrollment failed (${response.status}). Your samples remain in this page; retry or clear them.`);
            }
            if (typeof payload.redirect !== "string" || !payload.redirect.startsWith("/")) {
                throw new Error("Enrollment succeeded, but the server did not provide a valid interview link. Contact the interview administrator.");
            }
            samples.length = 0;
            showStatus("Enrollment succeeded. Opening your interview…", "success-message");
            window.location.assign(payload.redirect);
        } catch (error) {
            showStatus(error.message || "Upload failed. Your samples remain in this page; retry or clear them.", "error-message");
            submitButton.dataset.submitting = "false";
            busy = false;
            updateControls();
        }
    });

    updateControls();
});
