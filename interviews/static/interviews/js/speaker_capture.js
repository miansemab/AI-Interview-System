/* Capture local audio and prepare bounded PCM WAV samples for verification. */
(() => {
    const OUTPUT_RATE = 16000;
    const MIN_SAMPLE_SECONDS = 4;
    const MAX_SAMPLE_SECONDS = 15;

    function encodeWav(floatSamples, inputRate) {
        const step = inputRate / OUTPUT_RATE;
        const outputLength = Math.floor(floatSamples.length / step);
        const pcm = new DataView(new ArrayBuffer(44 + outputLength * 2));
        const writeText = (offset, text) => {
            for (let i = 0; i < text.length; i += 1) pcm.setUint8(offset + i, text.charCodeAt(i));
        };
        writeText(0, "RIFF");
        pcm.setUint32(4, 36 + outputLength * 2, true);
        writeText(8, "WAVE");
        writeText(12, "fmt ");
        pcm.setUint32(16, 16, true);
        pcm.setUint16(20, 1, true);
        pcm.setUint16(22, 1, true);
        pcm.setUint32(24, OUTPUT_RATE, true);
        pcm.setUint32(28, OUTPUT_RATE * 2, true);
        pcm.setUint16(32, 2, true);
        pcm.setUint16(34, 16, true);
        writeText(36, "data");
        pcm.setUint32(40, outputLength * 2, true);
        for (let i = 0; i < outputLength; i += 1) {
            const position = i * step;
            const left = Math.floor(position);
            const fraction = position - left;
            const a = floatSamples[left] || 0;
            const b = floatSamples[Math.min(left + 1, floatSamples.length - 1)] || 0;
            const sample = Math.max(-1, Math.min(1, a + (b - a) * fraction));
            pcm.setInt16(44 + i * 2, sample < 0 ? sample * 32768 : sample * 32767, true);
        }
        return new Blob([pcm], { type: "audio/wav" });
    }

    function microphoneError(error) {
        if (error?.name === "NotAllowedError" || error?.name === "PermissionDeniedError") {
            return new Error("Microphone access was denied. Allow microphone access for this site, then try again.");
        }
        if (error?.name === "NotFoundError" || error?.name === "DevicesNotFoundError") {
            return new Error("No microphone was found. Connect a microphone and try again.");
        }
        if (error?.name === "NotReadableError" || error?.name === "TrackStartError") {
            return new Error("The microphone is busy or unavailable. Close other apps using it and retry.");
        }
        if (error?.name === "SecurityError") {
            return new Error("Microphone access requires localhost or HTTPS. Open this interview on a secure page.");
        }
        if (error?.name === "NotSupportedError" || error?.name === "TypeError") {
            return new Error("This browser could not initialize audio capture. Try a current browser on localhost or HTTPS.");
        }
        return new Error(error?.message || "The microphone could not start. Check its connection and browser permission, then retry.");
    }

    function captureSupport() {
        const AudioContextConstructor = window.AudioContext || window.webkitAudioContext;
        if (!navigator.mediaDevices?.getUserMedia) {
            throw new Error("This browser cannot capture audio for speaker verification. Use a current browser on localhost or HTTPS.");
        }
        if (!window.MediaRecorder) {
            throw new Error("This browser does not support audio recording. Use a current version of Chrome, Edge, Firefox, or Safari.");
        }
        if (!AudioContextConstructor) {
            throw new Error("This browser cannot convert the recording into the required audio format. Use a current browser.");
        }
        return AudioContextConstructor;
    }

    async function toWav(recordedBlob) {
        if (recordedBlob.size === 0) {
            throw new Error("The microphone returned an empty recording. Check that it is not muted, then try again.");
        }
        const AudioContextConstructor = captureSupport();
        const context = new AudioContextConstructor();
        try {
            const buffer = await context.decodeAudioData(await recordedBlob.arrayBuffer());
            if (buffer.duration < MIN_SAMPLE_SECONDS) {
                throw new Error("Speak for at least four seconds so the speaker check has enough audio.");
            }
            const length = Math.min(buffer.length, buffer.sampleRate * MAX_SAMPLE_SECONDS);
            const samples = new Float32Array(length);
            for (let channel = 0; channel < buffer.numberOfChannels; channel += 1) {
                const source = buffer.getChannelData(channel);
                for (let index = 0; index < length; index += 1) {
                    samples[index] += source[index] / buffer.numberOfChannels;
                }
            }
            const wav = encodeWav(samples, buffer.sampleRate);
            if (wav.size > 1000000) {
                throw new Error("The recording was too large to upload. Try a shorter answer.");
            }
            return wav;
        } finally {
            if (context.state !== "closed") await context.close();
        }
    }

    async function beginCapture(statusElement, statusMessage, onMaximumDuration) {
        captureSupport();
        if (statusElement) statusElement.textContent = "Requesting microphone access. Approve the browser prompt to begin recording.";
        let stream;
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
                video: false,
            });
            const mimeType = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"]
                .find((type) => MediaRecorder.isTypeSupported?.(type));
            const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
            const chunks = [];
            const stopped = new Promise((resolve, reject) => {
                recorder.addEventListener("dataavailable", (event) => {
                    if (event.data?.size) chunks.push(event.data);
                });
                recorder.addEventListener("error", (event) => {
                    reject(event.error || new Error("The browser could not record microphone audio."));
                }, { once: true });
                recorder.addEventListener("stop", () => {
                    resolve(new Blob(chunks, { type: recorder.mimeType || chunks[0]?.type || "" }));
                }, { once: true });
            });
            void stopped.catch(() => {});
            recorder.start(250);
            if (statusElement) statusElement.textContent = statusMessage;

            let finishPromise = null;
            let maximumTimer = null;
            const finish = () => {
                if (finishPromise) return finishPromise;
                if (maximumTimer !== null) window.clearTimeout(maximumTimer);
                finishPromise = (async () => {
                    if (recorder.state !== "inactive") recorder.stop();
                    return toWav(await stopped);
                })().finally(() => {
                    stream?.getTracks().forEach((track) => track.stop());
                    if (statusElement) statusElement.textContent = "Audio ready for the speaker check.";
                });
                return finishPromise;
            };
            const cancel = async () => {
                if (maximumTimer !== null) window.clearTimeout(maximumTimer);
                if (recorder.state !== "inactive") recorder.stop();
                await stopped.catch(() => {});
                stream?.getTracks().forEach((track) => track.stop());
            };
            if (onMaximumDuration) maximumTimer = window.setTimeout(onMaximumDuration, MAX_SAMPLE_SECONDS * 1000);
            return { finish, cancel };
        } catch (error) {
            stream?.getTracks().forEach((track) => track.stop());
            if (error?.name && error.name !== "Error") throw microphoneError(error);
            throw error;
        }
    }

    async function record(seconds, statusElement) {
        let remaining = seconds;
        const capture = await beginCapture(
            statusElement,
            `Recording a short sample: ${seconds} seconds. Speak naturally.`,
        );
        try {
            while (remaining > 0) {
                await new Promise((resolve) => window.setTimeout(resolve, 1000));
                remaining -= 1;
                if (remaining > 0 && statusElement) {
                    statusElement.textContent = `Recording a short sample: ${remaining} seconds remaining.`;
                }
            }
            return await capture.finish();
        } catch (error) {
            await capture.cancel();
            throw error;
        }
    }

    async function startAnswerCapture(statusElement, onMaximumDuration) {
        return beginCapture(
            statusElement,
            `Recording your spoken answer for the speaker check (up to ${MAX_SAMPLE_SECONDS} seconds).`,
            onMaximumDuration,
        );
    }

    window.SpeakerCapture = { record, startAnswerCapture };
})();
