
document.addEventListener("DOMContentLoaded", () => {
    const visualizer = document.getElementById("heroVisualizer");
    const avatar = document.getElementById("heroAvatar");

    // Homepage hologram animation
    if (visualizer && avatar) {
        avatar.setAttribute("title", "Animated AI interviewer");

        avatar.addEventListener("mouseenter", () => {
            visualizer.classList.add("is-speaking");
        });

        avatar.addEventListener("mouseleave", () => {
            visualizer.classList.remove("is-speaking");
        });
    }

    // Voice support
    const SpeechRecognition =
        window.SpeechRecognition || window.webkitSpeechRecognition;

    const speakButton = document.getElementById("speakQuestion");
    const listenButton = document.getElementById("startListening");
    const stopButton = document.getElementById("stopListening");
    const answerBox = document.getElementById("answer");
    const answerSource = document.getElementById("answerSource");
    const voiceStatus = document.getElementById("voiceStatus");
    const interviewVisualizer = document.getElementById("interviewVisualizer");
    const questionElement = document.getElementById("interviewQuestion");
    const questionProgressCurrent = document.getElementById("questionProgressCurrent");
    const questionProgressBar = document.getElementById("questionProgressBar");
    const currentQuestionOrder = document.getElementById("currentQuestionOrder");
    const answeredQuestionCount = document.getElementById("answeredQuestionCount");
    const currentQuestionSkill = document.getElementById("currentQuestionSkill");
    const currentQuestionTopic = document.getElementById("currentQuestionTopic");
    const currentQuestionDifficulty = document.getElementById("currentQuestionDifficulty");
    const interviewQuestionId = document.getElementById("interviewQuestionId");

    const answerForm = answerBox?.closest("form");
    const finishInterviewForm = document.getElementById("finishInterviewForm");
    const finishInterviewButton = document.getElementById("finishInterviewButton");
    const finishInterviewStatus = document.getElementById("finishInterviewStatus");
    const answerSubmitStatus = document.getElementById("answerSubmitStatus");
    const answerSubmitButton = document.getElementById("answerSubmitButton");
    const speakerDangerAlert = document.getElementById("speakerDangerAlert");
    const recheckForm = document.getElementById("speakerRecheckForm");
    const recheckRecordButton = document.getElementById("recordRecheckSample");
    const recheckStatus = document.getElementById("recheckStatus");
    const recheckSubmitButton = document.getElementById("submitRecheckButton");

    let recognition = null;
    let recognitionState = "idle";
    let recognitionError = null;
    let finalTranscript = "";
    let recognitionSessionResults = [];
    let voiceRecordingRequested = false;
    let recognitionRestartTimer = null;
    let recognitionRestartTimes = [];
    let updatingAnswerFromRecognition = false;
    let manualTextEdited = false;
    let pendingVoiceAction = null;
    let activeUtterance = null;
    let speechStopPoll = null;
    let speechCancelFailed = false;
    let finishSubmissionPending = false;
    let answerSubmissionPending = false;
    let answerSpeakerAudio = null;
    let recheckSpeakerAudio = null;
    let speakerPaused = false;
    let speakerCapturePending = false;
    let answerCaptureStartPromise = null;
    let activeAnswerCapture = null;
    let answerCaptureFinishPromise = null;

    const RECOGNITION_RESTART_DELAY_MS = 500;
    const RECOGNITION_RESTART_WINDOW_MS = 60_000;
    const MAX_RECOGNITION_RESTARTS_PER_WINDOW = 10;

    function setAnswerSubmitStatus(message, kind = "") {
        if (!answerSubmitStatus) return;
        answerSubmitStatus.textContent = message;
        answerSubmitStatus.classList.remove("is-error", "is-success", "is-loading");
        if (kind) answerSubmitStatus.classList.add(`is-${kind}`);
    }

    function setFinishStatus(message, kind = "") {
        if (!finishInterviewStatus) return;
        finishInterviewStatus.textContent = message;
        finishInterviewStatus.classList.remove("is-error", "is-success", "is-loading");
        if (kind) finishInterviewStatus.classList.add(`is-${kind}`);
    }

    function updateInterviewQuestion(payload) {
        const question = payload.question;
        if (!question || !questionElement || !answerBox || !interviewQuestionId) {
            throw new Error("The next question response was missing required interview room data.");
        }

        questionElement.textContent = question.text;
        interviewQuestionId.value = question.id;
        if (questionProgressCurrent) questionProgressCurrent.textContent = question.order;
        if (currentQuestionOrder) currentQuestionOrder.textContent = question.order;
        if (answeredQuestionCount) answeredQuestionCount.textContent = `${payload.answered_count} answered`;
        if (currentQuestionSkill) currentQuestionSkill.textContent = question.skill;
        if (currentQuestionTopic) currentQuestionTopic.textContent = question.topic;
        if (currentQuestionDifficulty) currentQuestionDifficulty.textContent = question.difficulty;
        if (questionProgressBar) {
            questionProgressBar.setAttribute("aria-valuemax", payload.question_limit);
            questionProgressBar.setAttribute("aria-valuenow", question.order);
            const progressFill = questionProgressBar.querySelector("span");
            if (progressFill) progressFill.style.width = `${payload.progress_percent}%`;
        }

        answerBox.value = "";
        answerSource.value = "text";
        manualTextEdited = false;
        finalTranscript = "";
        recognitionSessionResults = [];
        voiceRecordingRequested = false;
        if (recognitionRestartTimer !== null) {
            window.clearTimeout(recognitionRestartTimer);
            recognitionRestartTimer = null;
        }
        setVoiceStatus(cameraStream
            ? "Next question loaded. Your camera preview remains active until you turn it off or leave the interview."
            : "Next question loaded. Continue with your answer controls when ready.");
        questionElement.focus?.({ preventScroll: true });
    }

    async function finishAnswerVoiceCapture() {
        if (answerCaptureFinishPromise || !answerCaptureStartPromise) return answerCaptureFinishPromise;
        answerCaptureFinishPromise = (async () => {
            const capture = activeAnswerCapture || await answerCaptureStartPromise;
            activeAnswerCapture = null;
            if (!capture) return;
            answerSpeakerAudio = await capture.finish();
            setVoiceStatus("Voice answer is ready. Review the transcript before submitting.");
        })().catch((error) => {
            answerSpeakerAudio = null;
            setVoiceStatus(`${error.message || "The spoken audio could not be prepared for speaker verification."} You can still submit this as a typed answer; it will not be speaker-verified.`);
        }).finally(() => {
            answerCaptureStartPromise = null;
            activeAnswerCapture = null;
            answerCaptureFinishPromise = null;
            speakerCapturePending = false;
        });
        return answerCaptureFinishPromise;
    }

    async function cancelAnswerVoiceCapture() {
        const startPromise = answerCaptureStartPromise;
        answerCaptureStartPromise = null;
        const capture = activeAnswerCapture;
        activeAnswerCapture = null;
        try {
            const startedCapture = capture || (startPromise ? await startPromise : null);
            await startedCapture?.cancel();
            activeAnswerCapture = null;
        } catch (error) {
            // The startup failure is already reported beside the answer controls.
        } finally {
            speakerCapturePending = false;
        }
    }

    function beginAnswerVoiceCapture() {
        if (!answerForm || !window.SpeakerCapture?.startAnswerCapture) return;
        answerSpeakerAudio = null;
        speakerCapturePending = true;
        setVoiceStatus("Recording your spoken answer for speaker verification while browser speech recognition creates the transcript.");
        answerCaptureStartPromise = window.SpeakerCapture.startAnswerCapture(
            voiceStatus,
            () => {
                setVoiceStatus("The 15-second speaker-check limit was reached. Finishing voice recognition now.");
                stopVoiceRecognition();
                void finishAnswerVoiceCapture();
            },
        ).then((capture) => {
            activeAnswerCapture = capture;
            return capture;
        }).catch((error) => {
            answerCaptureStartPromise = null;
            speakerCapturePending = false;
            setVoiceStatus(`${error.message || "Could not capture the spoken answer."} You can still submit a typed answer; it will not be speaker-verified.`);
            return null;
        });
    }

    // Optional candidate preview. The camera stream is never uploaded.
    const cameraVideo = document.getElementById("candidateCamera");
    const cameraToggle = document.getElementById("cameraToggle");
    const cameraStatus = document.getElementById("cameraStatus");
    const cameraErrorDetail = document.getElementById("cameraErrorDetail");
    const cameraPlaceholder = document.getElementById("cameraPlaceholder");
    const cameraStateTitle = document.getElementById("cameraStateTitle");
    const cameraStateDetail = document.getElementById("cameraStateDetail");
    const cameraLiveLabel = document.getElementById("cameraLiveLabel");
    let cameraStream = null;
    let roomPageExiting = false;

    function setCameraError(name, message, stage, error = null, suggestion = "") {
        const diagnostic = `${name}: ${message} (stage: ${stage}; secure context: ${window.isSecureContext}; getUserMedia available: ${Boolean(navigator.mediaDevices?.getUserMedia)})${suggestion ? ` Suggested action: ${suggestion}` : ""}`;
        if (cameraErrorDetail) {
            cameraErrorDetail.textContent = diagnostic;
            cameraErrorDetail.hidden = false;
        }
        if (cameraStatus) cameraStatus.textContent = `Camera unavailable. ${suggestion || message}`;
        if (cameraStateTitle) cameraStateTitle.textContent = "Camera unavailable";
        if (cameraStateDetail) cameraStateDetail.textContent = "Check browser camera permissions and the console details, then retry.";
        if (cameraToggle) cameraToggle.textContent = "Retry camera";
        console.error("Candidate camera preview failed:", error || { name, message, stage });
    }

    function stopCandidateCamera(message = "Camera is off. The preview is optional.") {
        let cleanupError = null;
        cameraStream?.getTracks().forEach((track) => {
            try {
                track.stop();
            } catch (error) {
                console.error("Could not stop candidate camera track:", error);
                cleanupError = error;
            }
        });
        cameraStream = null;
        if (cameraVideo) {
            try {
                cameraVideo.pause();
                cameraVideo.srcObject = null;
            } catch (error) {
                console.error("Could not clear candidate camera preview:", error);
                cleanupError = cleanupError || error;
            }
        }
        if (cameraPlaceholder) cameraPlaceholder.hidden = false;
        if (cameraToggle) {
            cameraToggle.textContent = "Turn camera on";
            cameraToggle.setAttribute("aria-pressed", "false");
        }
        if (cameraLiveLabel) cameraLiveLabel.hidden = true;
        if (cameraStateTitle) cameraStateTitle.textContent = "Camera is off";
        if (cameraStateDetail) cameraStateDetail.textContent = "Turn it on to preview your camera. Video is not analyzed.";
        if (cameraStatus) cameraStatus.textContent = message;
        if (cameraErrorDetail) cameraErrorDetail.hidden = true;
        if (cleanupError) {
            setCameraError(cleanupError.name || "CameraCleanupError", cleanupError.message || "The browser reported an error while releasing the camera.", "cleanup", cleanupError);
        }
    }

    if (cameraToggle && cameraVideo) {
        cameraToggle.addEventListener("click", async () => {
            if (cameraStatus) cameraStatus.textContent = "Camera button clicked. Checking browser support…";
            console.info("Candidate camera button clicked", {
                secureContext: window.isSecureContext,
                getUserMediaAvailable: Boolean(navigator.mediaDevices?.getUserMedia),
            });
            if (cameraStream) {
                stopCandidateCamera();
                return;
            }

            let stage = "checking-browser-support";
            if (!navigator.mediaDevices?.getUserMedia) {
                const name = window.isSecureContext === false ? "InsecureContextError" : "NotSupportedError";
                const message = window.isSecureContext === false
                    ? "Camera access requires localhost or a secure HTTPS connection."
                    : "This browser does not expose navigator.mediaDevices.getUserMedia().";
                setCameraError(name, message, stage);
                return;
            }

            cameraToggle.disabled = true;
            if (cameraErrorDetail) cameraErrorDetail.hidden = true;
            if (cameraStateTitle) cameraStateTitle.textContent = "Starting camera…";
            if (cameraStateDetail) cameraStateDetail.textContent = "Allow camera access in your browser to show a local preview.";
            if (cameraStatus) cameraStatus.textContent = "Requesting camera permission…";
            try {
                stage = "requesting-camera-permission";
                const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
                stage = "checking-video-track";
                const videoTracks = stream.getVideoTracks();
                if (!videoTracks.length || videoTracks.every((track) => track.readyState !== "live")) {
                    stream.getTracks().forEach((track) => track.stop());
                    throw Object.assign(new Error("The browser returned no live video track."), { name: "NoLiveVideoTrackError" });
                }
                console.info("Candidate camera stream acquired", videoTracks.map((track) => ({
                    label: track.label,
                    readyState: track.readyState,
                    enabled: track.enabled,
                })));
                if (roomPageExiting) {
                    stream.getTracks().forEach((track) => track.stop());
                    return;
                }
                cameraStream = stream;
                videoTracks.forEach((track) => {
                    track.addEventListener("ended", () => {
                        if (cameraStream === stream) {
                            stopCandidateCamera("The camera stopped. Check the device and retry the preview.");
                            setCameraError("VideoTrackEndedError", "The camera track ended unexpectedly. Check device availability and browser permission.", "active-preview");
                        }
                    }, { once: true });
                });
                stage = "assigning-video-stream";
                cameraVideo.srcObject = cameraStream;
                stage = "starting-video-playback";
                await cameraVideo.play();
                if (roomPageExiting) {
                    stopCandidateCamera("Camera stopped because the interview page was exited.");
                    return;
                }
                if (cameraPlaceholder) cameraPlaceholder.hidden = true;
                cameraToggle.textContent = "Turn camera off";
                cameraToggle.setAttribute("aria-pressed", "true");
                if (cameraStateTitle) cameraStateTitle.textContent = "Camera preview is on";
                if (cameraStateDetail) cameraStateDetail.textContent = "Only you can see this preview on this page.";
                if (cameraLiveLabel) cameraLiveLabel.hidden = false;
                if (cameraStatus) cameraStatus.textContent = "Live preview is active. Video is not sent to the server or analyzed.";
                console.info("Candidate camera preview is playing", {
                    hasSrcObject: cameraVideo.srcObject === cameraStream,
                    videoWidth: cameraVideo.videoWidth,
                    videoHeight: cameraVideo.videoHeight,
                });
            } catch (error) {
                const cameraErrors = {
                    NotAllowedError: "Camera access was denied or blocked. Allow access in the browser's site settings, then retry.",
                    NotFoundError: "No camera was found. Connect or enable a camera, then retry.",
                    NotReadableError: "The camera could not be read. Another application may be using it; close that app and retry.",
                    SecurityError: "Camera access requires localhost or a secure HTTPS connection.",
                    OverconstrainedError: "The available camera could not satisfy the requested video settings.",
                    AbortError: "The browser interrupted camera startup. Retry the preview.",
                    NotSupportedError: "This browser does not support camera preview.",
                };
                const name = error?.name || "UnknownCameraError";
                const message = error?.message || "The browser did not provide an error message.";
                const suggestion = cameraErrors[name] || "Check the camera connection and browser permission, then retry.";
                stopCandidateCamera("Camera preview failed. You can retry; the interview can continue without it.");
                setCameraError(name, message, stage, error, suggestion);
            } finally {
                cameraToggle.disabled = false;
            }
        });
    } else if (cameraStatus) {
        const message = "Camera controls could not initialize because the camera button or video element is missing.";
        cameraStatus.textContent = message;
        setCameraError("CameraElementMissingError", message, "initializing-camera-controls");
    } else {
        console.error("Candidate camera controls could not initialize", {
            cameraButtonFound: Boolean(cameraToggle),
            videoElementFound: Boolean(cameraVideo),
        });
    }
    if (answerBox) {
        answerBox.addEventListener("input", () => {
            if (updatingAnswerFromRecognition) return;

            manualTextEdited = true;
            if (answerSource) {
                answerSource.value = "text";
            }

            finalTranscript = answerBox.value.trim();
        });
    }

    function setVoiceStatus(message) {
        if (voiceStatus) {
            voiceStatus.textContent = message;
        }
    }

    function renderRecognitionTranscript() {
        if (!answerBox || manualTextEdited) return;
        const finalized = recognitionSessionResults
            .filter((result) => result?.isFinal)
            .map((result) => result.transcript)
            .filter(Boolean)
            .join(" ");
        const interim = recognitionSessionResults
            .filter((result) => result && !result.isFinal)
            .map((result) => result.transcript)
            .filter(Boolean)
            .join(" ");
        updatingAnswerFromRecognition = true;
        answerBox.value = [finalTranscript, finalized, interim]
            .filter(Boolean)
            .join(" ");
        updatingAnswerFromRecognition = false;
    }

    function commitRecognitionSession() {
        const finalized = recognitionSessionResults
            .filter((result) => result?.isFinal)
            .map((result) => result.transcript)
            .filter(Boolean)
            .join(" ");
        if (finalized) {
            finalTranscript = [finalTranscript, finalized].filter(Boolean).join(" ");
        }
        recognitionSessionResults = [];
        renderRecognitionTranscript();
    }

    function scheduleRecognitionRestart() {
        if (!voiceRecordingRequested || roomPageExiting || answerSubmissionPending || finishSubmissionPending) {
            return false;
        }
        if (recognitionRestartTimer !== null) return true;

        const now = Date.now();
        recognitionRestartTimes = recognitionRestartTimes.filter(
            (startedAt) => now - startedAt < RECOGNITION_RESTART_WINDOW_MS,
        );
        if (recognitionRestartTimes.length >= MAX_RECOGNITION_RESTARTS_PER_WINDOW) {
            voiceRecordingRequested = false;
            setVoiceStatus("Speech recognition paused after repeated browser session endings. Your transcript is kept; click Answer with voice to continue.");
            void finishAnswerVoiceCapture();
            return false;
        }

        recognitionRestartTimes.push(now);
        recognitionRestartTimer = window.setTimeout(() => {
            recognitionRestartTimer = null;
            if (!voiceRecordingRequested || recognitionState !== "idle" || roomPageExiting) return;
            startVoiceRecognition(true);
        }, RECOGNITION_RESTART_DELAY_MS);
        return true;
    }

    function setListening(isListening) {
        if (listenButton) {
            listenButton.classList.toggle("recording", isListening);
            listenButton.textContent = isListening
                ? "🎙 Listening..."
                : "🎙 Answer with voice";
        }

        if (interviewVisualizer) {
            interviewVisualizer.classList.toggle("is-listening", isListening);
        }
    }

    function nativeSpeechIsActive() {
        if (!("speechSynthesis" in window)) return false;

        try {
            return Boolean(window.speechSynthesis.speaking || window.speechSynthesis.pending);
        } catch (error) {
            // Keep the active utterance as the conservative fallback.
            return Boolean(activeUtterance);
        }
    }

    function speechIsActive() {
        return Boolean(activeUtterance || nativeSpeechIsActive());
    }

    function startQuestionSpeech() {
        const question = questionElement?.textContent?.trim();

        if (!question) {
            setVoiceStatus("No question is available to read.");
            return;
        }

        let utterance;

        try {
            utterance = new SpeechSynthesisUtterance(question);
            utterance.lang = "en-US";
            utterance.rate = 0.92;
            utterance.pitch = 1;
        } catch (error) {
            setVoiceStatus("Could not prepare question playback. Try again.");
            return;
        }

        activeUtterance = utterance;

        const finishUtterance = () => {
            if (activeUtterance !== utterance) return false;

            const switchingModes = Boolean(pendingVoiceAction);
            activeUtterance = null;
            if (interviewVisualizer) {
                interviewVisualizer.classList.remove("is-speaking");
            }
            runPendingVoiceAction();
            return switchingModes;
        };

        utterance.onstart = () => {
            if (activeUtterance !== utterance) return;

            if (interviewVisualizer) {
                interviewVisualizer.classList.add("is-speaking");
            }
            setVoiceStatus("AI interviewer is speaking...");
        };

        utterance.onend = () => {
            const switchingModes = finishUtterance();
            if (!switchingModes) {
                setVoiceStatus("Question playback finished.");
            }
        };

        utterance.onerror = () => {
            const switchingModes = finishUtterance();
            if (!switchingModes) {
                setVoiceStatus("Could not play the question. Try again.");
            }
        };

        try {
            window.speechSynthesis.speak(utterance);
        } catch (error) {
            finishUtterance();
            setVoiceStatus("Could not play the question. Try again.");
        }
    }

    function runPendingVoiceAction() {
        if (!pendingVoiceAction || recognitionState !== "idle") return;

        if (speechIsActive()) {
            if (pendingVoiceAction === "listen") {
                scheduleSpeechStopCheck();
            }
            return;
        }

        const action = pendingVoiceAction;
        pendingVoiceAction = null;

        if (action === "speak") {
            startQuestionSpeech();
        } else if (action === "listen") {
            startVoiceRecognition();
        }
    }

    function scheduleSpeechStopCheck() {
        if (speechStopPoll !== null) return;

        speechStopPoll = window.setTimeout(() => {
            speechStopPoll = null;

            if (!nativeSpeechIsActive()) {
                activeUtterance = null;
                runPendingVoiceAction();
                return;
            }

            scheduleSpeechStopCheck();
        }, 50);
    }

    function cancelSpeechAndWait() {
        if (!("speechSynthesis" in window)) {
            activeUtterance = null;
            runPendingVoiceAction();
            return;
        }

        try {
            window.speechSynthesis.cancel();
            speechCancelFailed = false;
        } catch (error) {
            speechCancelFailed = true;
            setVoiceStatus("Waiting for question playback to stop...");
        }

        // Some browsers do not dispatch an utterance end event on cancel.
        // Poll the browser state and continue only after playback is inactive.
        scheduleSpeechStopCheck();
    }

    // Stop listening without deleting the answer
    function stopVoiceRecognition() {
        voiceRecordingRequested = false;
        if (recognitionRestartTimer !== null) {
            window.clearTimeout(recognitionRestartTimer);
            recognitionRestartTimer = null;
        }
        if (!recognition || recognitionState === "idle") {
            if (answerCaptureStartPromise && !answerCaptureFinishPromise) {
                void finishAnswerVoiceCapture().finally(runPendingVoiceAction);
            }
            return;
        }

        recognitionState = "stopping";

        try {
            recognition.stop();
        } catch (error) {
            // Do not switch modes until an end event confirms that the
            // microphone is released. Try abort as a fallback; if that also
            // fails, a later Stop or Speak click can retry the stop request.
            pendingVoiceAction = null;
            setListening(false);

            try {
                recognition.abort();
                setVoiceStatus("Canceling voice input...");
            } catch (abortError) {
                setVoiceStatus(
                    "Could not stop voice input. Click Stop listening or Speak Question to retry."
                );
            }
        }
    }

    function startVoiceRecognition(isResume = false) {
        if (!recognition || recognitionState !== "idle" || speechIsActive()) {
            return;
        }

        if (!isResume) {
            voiceRecordingRequested = true;
            recognitionRestartTimes = [];
            finalTranscript = answerBox?.value?.trim() || "";
            recognitionSessionResults = [];
            manualTextEdited = false;
            beginAnswerVoiceCapture();
        }
        recognitionState = "starting";

        try {
            recognition.start();
        } catch (error) {
            recognitionState = "idle";
            setListening(false);
            if (isResume && scheduleRecognitionRestart()) {
                setVoiceStatus("Speech recognition is reconnecting. Keep speaking; your transcript and speaker audio capture are being kept.");
            } else {
                voiceRecordingRequested = false;
                void cancelAnswerVoiceCapture();
                setVoiceStatus("Voice input could not start. Click to try again.");
                runPendingVoiceAction();
            }
        }
    }

    function requestQuestionSpeech() {
        if (pendingVoiceAction || activeUtterance) return;
        if (!("speechSynthesis" in window)) {
            setVoiceStatus("Speech playback is not supported in this browser.");
            return;
        }

        pendingVoiceAction = "speak";

        if (recognitionState !== "idle" || voiceRecordingRequested) {
            setVoiceStatus("Stopping voice input before reading the question...");
            stopVoiceRecognition();
            return;
        }

        if (speechIsActive()) {
            pendingVoiceAction = null;
            setVoiceStatus("Question playback is already active.");
            return;
        }

        runPendingVoiceAction();
    }

    function requestVoiceRecognition(resumeAfterStop = false) {
        if (!recognition) return;

        if (pendingVoiceAction) {
            if (pendingVoiceAction === "listen" && speechCancelFailed) {
                setVoiceStatus("Retrying question playback cancellation...");
                cancelSpeechAndWait();
                return;
            }
            setVoiceStatus("Voice input is already starting or running.");
            return;
        }

        if (recognitionState !== "idle") {
            if (resumeAfterStop) {
                pendingVoiceAction = "listen";
            } else {
                setVoiceStatus("Voice input is already starting or running.");
            }
            return;
        }

        pendingVoiceAction = "listen";

        if (speechIsActive()) {
            setVoiceStatus("Stopping question playback before listening...");
            cancelSpeechAndWait();
            return;
        }

        runPendingVoiceAction();
    }

    if (answerForm) {
        answerForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (finishSubmissionPending || answerSubmissionPending) {
                return;
            }
            if (speakerCapturePending) {
                const message = "Wait for the spoken answer or speaker sample recording to finish before submitting.";
                setVoiceStatus(message);
                setAnswerSubmitStatus(message, "loading");
                return;
            }
            const source = !manualTextEdited && answerSource?.value === "voice" ? "voice" : "text";
            if (source === "voice" && !answerSpeakerAudio) {
                const message = "The spoken audio was not captured, so speaker verification cannot run. Retry voice input or submit a typed answer, which will be marked not speaker-verified.";
                setVoiceStatus(message);
                setAnswerSubmitStatus(message, "error");
                return;
            }

            answerSubmissionPending = true;
            const submitButton = answerSubmitButton || answerForm.querySelector('button[type="submit"]');
            const previousSubmitDisabled = submitButton?.disabled ?? false;
            const previousFinishDisabled = finishInterviewButton?.disabled ?? false;
            if (submitButton) submitButton.disabled = true;
            if (finishInterviewButton) finishInterviewButton.disabled = true;
            setAnswerSubmitStatus(answerSpeakerAudio ? "Submitting your answer and checking the speaker sample…" : "Submitting your typed answer…", "loading");
            if (submitButton) submitButton.textContent = "Submitting answer…";
            pendingVoiceAction = null;
            stopVoiceRecognition();
            if ("speechSynthesis" in window) window.speechSynthesis.cancel();
            activeUtterance = null;
            try {
                const body = new FormData(answerForm);
                body.set("answer_source", source);
                if (answerSpeakerAudio) {
                    body.append("speaker_audio", answerSpeakerAudio, "speaker-check.wav");
                }
                console.debug("Submitting interview answer", {
                    answerSource: source,
                    speakerAudioIncluded: Boolean(answerSpeakerAudio),
                });
                const response = await fetch(answerForm.action, {
                    method: "POST",
                    body,
                    credentials: "same-origin",
                    headers: { "X-Requested-With": "XMLHttpRequest" },
                });
                if (!response.ok) {
                    let message = "Speaker verification failed. Your answer has not been submitted.";
                    try {
                        const payload = await response.json();
                        message = payload.error || message;
                    } catch (error) {
                        // Use the actionable default if the server response is not JSON.
                    }
                    if (response.status === 423) {
                        if (speakerDangerAlert) {
                            speakerDangerAlert.hidden = false;
                            speakerDangerAlert.scrollIntoView({ behavior: "smooth", block: "center" });
                        }
                        speakerPaused = true;
                        answerForm.querySelectorAll("input, textarea, button").forEach((field) => { field.disabled = true; });
                        if (finishInterviewButton) finishInterviewButton.disabled = true;
                        if (speakButton) speakButton.disabled = true;
                        if (listenButton) listenButton.disabled = true;
                        setVoiceStatus(message);
                        setAnswerSubmitStatus(`${message} The interview is paused for a speaker recheck.`, "error");
                        return;
                    }
                    if ([400, 409, 422].includes(response.status) && answerSpeakerAudio) {
                        answerSpeakerAudio = null;
                        setVoiceStatus("Please retry voice input to capture a fresh spoken sample, or edit the answer and submit it as text without speaker verification.");
                    }
                    setVoiceStatus(message);
                    setAnswerSubmitStatus(`${message} Your answer is still here; correct the issue and retry.`, "error");
                    return;
                }
                const contentType = response.headers.get("content-type") || "";
                if (contentType.includes("application/json")) {
                    const payload = await response.json();
                    const destination = new URL(payload.redirect, window.location.href);
                    const validAnswerDestination = destination.origin === window.location.origin && (
                        /^\/interview\/room\/\d+\/$/.test(destination.pathname)
                        || /^\/interview\/report\/\d+\/$/.test(destination.pathname)
                    );
                    if (!validAnswerDestination) {
                        throw new Error("The answer response did not lead to a valid interview page.");
                    }
                    answerSpeakerAudio = null;
                    if (payload.completed) {
                        setAnswerSubmitStatus("Answer saved and evaluated. Preparing your results...", "success");
                        window.location.assign(destination.href);
                    } else {
                        if (destination.pathname !== window.location.pathname) {
                            throw new Error("The next question belongs to a different interview room.");
                        }
                        updateInterviewQuestion(payload);
                        setAnswerSubmitStatus("Answer saved and evaluated. Your next question is ready.", "success");
                    }
                } else {
                    // Preserve redirect handling for already-completed or other non-JSON responses.
                    const destination = new URL(response.url, window.location.href);
                    const validAnswerDestination = destination.origin === window.location.origin && (
                        /^\/interview\/room\/\d+\/$/.test(destination.pathname)
                        || /^\/interview\/report\/\d+\/$/.test(destination.pathname)
                    );
                    if (!validAnswerDestination) {
                        throw new Error("The answer response did not lead to the next interview page.");
                    }
                    setAnswerSubmitStatus("Answer saved and evaluated. Loading the next step...", "success");
                    answerSpeakerAudio = null;
                    window.location.assign(destination.href);
                }            } catch (error) {
                const message = error.message || "The request failed. Your answer and recorded sample remain in this page; retry when ready.";
                setVoiceStatus(message);
                setAnswerSubmitStatus(`${message} Your answer is still here; retry when ready.`, "error");
            } finally {
                answerSubmissionPending = false;
                if (!speakerPaused) {
                    if (submitButton) submitButton.disabled = previousSubmitDisabled;
                    if (submitButton) submitButton.textContent = "Submit answer and continue →";
                    if (finishInterviewButton) finishInterviewButton.disabled = previousFinishDisabled;
                }
            }
        });
    }

    if (recheckRecordButton && recheckForm) {
        recheckRecordButton.addEventListener("click", async () => {
            recheckRecordButton.disabled = true;
            try {
                recheckSpeakerAudio = await SpeakerCapture.record(6, recheckStatus);
                recheckStatus.textContent = "Voice sample captured. Submit to retry verification.";
                if (recheckSubmitButton) recheckSubmitButton.disabled = false;
            } catch (error) {
                recheckStatus.textContent = error.message || "Could not record. Check microphone access and retry.";
            } finally {
                recheckRecordButton.disabled = false;
            }
        });
        recheckForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (!recheckSpeakerAudio || answerSubmissionPending) return;
            answerSubmissionPending = true;
            if (recheckSubmitButton) recheckSubmitButton.disabled = true;
            const body = new FormData(recheckForm);
            body.append("speaker_audio", recheckSpeakerAudio, "speaker-recheck.wav");
            try {
                const response = await fetch(recheckForm.action, { method: "POST", body, credentials: "same-origin" });
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error || "The interview remains paused. Record another sample to retry.");
                recheckSpeakerAudio = null;
                window.location.assign(payload.redirect);
            } catch (error) {
                recheckSpeakerAudio = null;
                recheckStatus.textContent = error.message || "The request failed. Record a new sample to retry.";
                if (recheckSubmitButton) recheckSubmitButton.disabled = true;
            } finally {
                answerSubmissionPending = false;
            }
        });
    }

    if (finishInterviewForm) {
        finishInterviewForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (finishSubmissionPending || answerSubmissionPending) return;
            if (speakerCapturePending) {
                const message = "Wait for the voice sample recording to finish before completing the interview.";
                setVoiceStatus(message);
                setFinishStatus(message, "error");
                return;
            }
            if (answerBox?.value.trim()) {
                const message = "Submit your current answer before finishing. Your typed answer is still here.";
                setVoiceStatus(message);
                setFinishStatus(message, "error");
                answerBox.focus();
                return;
            }

            finishSubmissionPending = true;
            const previousFinishDisabled = finishInterviewButton?.disabled ?? false;
            const answerSubmitButton = answerForm?.querySelector('button[type="submit"]');
            const previousAnswerSubmitDisabled = answerSubmitButton?.disabled ?? false;
            const previousSpeakDisabled = speakButton?.disabled ?? false;
            const previousListenDisabled = listenButton?.disabled ?? false;
            if (finishInterviewButton) finishInterviewButton.disabled = true;
            if (answerSubmitButton) answerSubmitButton.disabled = true;
            if (speakButton) speakButton.disabled = true;
            if (listenButton) listenButton.disabled = true;
            setFinishStatus("Checking saved answers and preparing your results…", "loading");

            pendingVoiceAction = null;
            setVoiceStatus("Stopping voice input and question playback...");
            stopVoiceRecognition();

            if ("speechSynthesis" in window) {
                try {
                    window.speechSynthesis.cancel();
                } catch (error) {
                    // Keep waiting for the browser to report playback ended.
                }
            } else {
                activeUtterance = null;
            }

            activeUtterance = null;
            if (interviewVisualizer) interviewVisualizer.classList.remove("is-speaking");
            try {
                const response = await fetch(finishInterviewForm.action, {
                    method: "POST",
                    body: new FormData(finishInterviewForm),
                    credentials: "same-origin",
                    headers: { "X-Requested-With": "XMLHttpRequest" },
                });
                if (!response.ok) {
                    let message = "Unable to finish the interview. Please try again.";
                    try {
                        const payload = await response.json();
                        if (payload.error) message = payload.error;
                    } catch (error) {
                        // Use the actionable default for non-JSON responses.
                    }
                    setFinishStatus(`${message} Your saved answers are unchanged.`, "error");
                    throw new Error(message);
                }
                const destination = new URL(response.url, window.location.href);
                if (destination.origin !== window.location.origin || !/^\/interview\/report\/\d+\/$/.test(destination.pathname)) {
                    throw new Error("The server did not return a valid results page. Your saved answers are unchanged.");
                }
                setFinishStatus("Interview completed. Opening your results…", "success");
                window.location.assign(destination.href);
            } catch (error) {
                finishSubmissionPending = false;
                if (finishInterviewButton) finishInterviewButton.disabled = previousFinishDisabled;
                if (answerSubmitButton) answerSubmitButton.disabled = previousAnswerSubmitDisabled;
                if (speakButton) speakButton.disabled = previousSpeakDisabled;
                if (listenButton) listenButton.disabled = previousListenDisabled;
                const message = error.message || "The request failed. Please try again.";
                setVoiceStatus(message);
                setFinishStatus(message, "error");
            }
        });
    }

    // Read the interview question aloud
    if (speakButton) {
        speakButton.addEventListener("click", () => {
            if (finishSubmissionPending || speakerPaused) return;
            requestQuestionSpeech();
        });
    }

    // Set up browser speech recognition
    if (listenButton) {
        if (!SpeechRecognition) {
            listenButton.disabled = true;
            listenButton.title =
                "Speech recognition is not supported by this browser.";

            setVoiceStatus(
                "Voice recognition is unavailable here. You can type your answer instead."
            );
        } else {
            try {
                recognition = new SpeechRecognition();
            } catch (error) {
                recognition = null;
            }

            if (!recognition) {
                listenButton.disabled = true;
                listenButton.title =
                    "Speech recognition could not be started by this browser.";
                setVoiceStatus(
                    "Voice recognition is unavailable here. You can type your answer instead."
                );
            } else {
            recognition.lang = "en-US";
            recognition.continuous = true;
            recognition.interimResults = true;

            recognition.onstart = () => {
                recognitionState = "listening";
                recognitionError = null;
                setListening(true);

                if (pendingVoiceAction === "speak") {
                    setVoiceStatus("Stopping voice input before reading the question...");
                    stopVoiceRecognition();
                } else if (speechIsActive()) {
                    setVoiceStatus("Stopping voice input while question playback finishes...");
                    stopVoiceRecognition();
                } else {
                    if (pendingVoiceAction === "listen") {
                        pendingVoiceAction = null;
                    }
                    setVoiceStatus("Listening... Speak clearly. The spoken answer is also being captured for speaker verification.");
                }
            };

            recognition.onresult = (event) => {
                let recognizedTextReceived = false;

                // SpeechRecognition results are a session snapshot. Keeping each
                // result by index lets interim text become final in place instead
                // of appending it again on the next event.
                for (let i = 0; i < event.results.length; i++) {
                    const transcript = event.results[i][0].transcript;
                    recognizedTextReceived =
                        recognizedTextReceived || Boolean(transcript.trim());
                    recognitionSessionResults[i] = {
                        transcript: transcript.trim(),
                        isFinal: event.results[i].isFinal,
                    };
                }
                recognitionSessionResults.length = event.results.length;

                renderRecognitionTranscript();
                if (answerSource && recognizedTextReceived && !manualTextEdited) {
                    answerSource.value = "voice";
                }
            };

            recognition.onerror = (event) => {
                recognitionError = event.error;
                setListening(false);
                if (["not-allowed", "service-not-allowed", "audio-capture", "language-not-supported"].includes(event.error)) {
                    voiceRecordingRequested = false;
                }
                setVoiceStatus("Voice recognition issue: " + event.error + ". You can type your answer instead.");
            };

            recognition.onend = () => {
                recognitionState = "idle";
                setListening(false);
                commitRecognitionSession();
                const error = recognitionError;
                recognitionError = null;

                if (voiceRecordingRequested && scheduleRecognitionRestart()) {
                    setVoiceStatus(error
                        ? `Speech recognition ended (${error}); reconnecting while your answer audio capture continues.`
                        : "Speech recognition session ended; reconnecting while your answer audio capture continues. Keep speaking.");
                    return;
                }

                const wasCapturingAnswer = Boolean(answerCaptureStartPromise);
                if (wasCapturingAnswer) {
                    setVoiceStatus("Voice input stopped. Preparing the spoken audio for speaker verification...");
                    void finishAnswerVoiceCapture();
                }
                if (!pendingVoiceAction && !wasCapturingAnswer) {
                    setVoiceStatus(error
                        ? `Voice recognition issue: ${error}. Try again or type your answer.`
                        : "Voice input stopped. Review your answer before submitting."
                    );
                }

                runPendingVoiceAction();
            };

            listenButton.addEventListener("click", () => {
                if (finishSubmissionPending || speakerPaused) return;
                if (speakerCapturePending) {
                    setVoiceStatus("Wait for the current answer audio to finish preparing before starting voice input again.");
                    return;
                }
                requestVoiceRecognition();
            });

            if (stopButton) {
                stopButton.addEventListener("click", () => {
                    pendingVoiceAction = null;
                    stopVoiceRecognition();
                });
            }
            }
        }
    }

    // Clean up when leaving the page
    window.addEventListener("pagehide", () => {
        roomPageExiting = true;
        voiceRecordingRequested = false;
        if (recognitionRestartTimer !== null) {
            window.clearTimeout(recognitionRestartTimer);
            recognitionRestartTimer = null;
        }
        stopCandidateCamera("Camera stopped because the interview page was exited.");
        void cancelAnswerVoiceCapture();
        if (recognition) {
            recognition.abort();
        }

        if ("speechSynthesis" in window) {
            window.speechSynthesis.cancel();
        }
    });

});
