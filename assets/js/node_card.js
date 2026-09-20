/**
 * Role: Mounts direct browser-camera capture on the Camera Photo canvas node card.
 * File Name: node_card.js
 * Author: Alexandre EL
 * Email: alex@hackinvent.com
 * Created Date: 2026-05-19
 */
const DEFAULT_RESOLUTION = "1280x720";
const DEFAULT_JPEG_QUALITY = 0.92;

/**
 * Parse a WIDTHxHEIGHT string into optional media constraints.
 *
 * @param {string} resolution - User configured resolution.
 * @returns {{width?: {ideal: number}, height?: {ideal: number}}} Video constraints.
 */
function videoSizeConstraint(resolution) {
  const match = String(resolution || "").trim().toLowerCase().match(/^([1-9][0-9]{1,4})x([1-9][0-9]{1,4})$/);
  if (!match) {
    return {};
  }
  return {
    width: { ideal: Number(match[1]) },
    height: { ideal: Number(match[2]) },
  };
}

/**
 * Clamp the configured JPEG quality to the canvas API range.
 *
 * @param {number|string} rawValue - Raw quality value from node-card context.
 * @returns {number} JPEG quality between 0.1 and 1.
 */
function jpegQuality(rawValue) {
  const parsed = Number(rawValue);
  if (!Number.isFinite(parsed)) {
    return DEFAULT_JPEG_QUALITY;
  }
  return Math.min(1, Math.max(0.1, parsed));
}

/**
 * Return the capture config sent to the backend persistence action.
 *
 * @param {object} context - Node-card context returned by block.py.
 * @returns {{resolution: string, camera_facing: string, jpeg_quality: number, output_dir: string}} Capture config.
 */
function captureConfig(context) {
  return {
    resolution: String(context?.resolution || DEFAULT_RESOLUTION),
    camera_facing: String(context?.camera_facing || "environment"),
    jpeg_quality: jpegQuality(context?.jpeg_quality),
    output_dir: String(context?.output_dir || "exports/camera"),
  };
}

/**
 * Return getUserMedia video constraints for the selected front/back camera.
 *
 * @param {object} config - Normalized capture config.
 * @returns {object} Video constraints sent to the browser.
 */
function videoConstraints(config) {
  return {
    ...videoSizeConstraint(config.resolution),
    facingMode: { ideal: config.camera_facing || "environment" },
  };
}

/**
 * Stop every media track opened for a one-shot capture.
 *
 * @param {MediaStream|null} stream - Browser media stream to close.
 * @returns {void}
 */
function stopStream(stream) {
  for (const track of stream?.getTracks?.() || []) {
    track.stop();
  }
}

/**
 * Wait until the technical video exposes a drawable frame.
 *
 * @param {HTMLVideoElement} video - Technical video element.
 * @returns {Promise<void>} Resolves when dimensions are available.
 */
function waitForVideoFrame(video) {
  if (video.videoWidth > 0 && video.videoHeight > 0) {
    return new Promise((resolve) => requestAnimationFrame(() => resolve()));
  }
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      cleanup();
      reject(new Error("camera_frame_timeout"));
    }, 5000);
    const onReady = () => {
      if (video.videoWidth <= 0 || video.videoHeight <= 0) {
        return;
      }
      cleanup();
      requestAnimationFrame(() => resolve());
    };
    const cleanup = () => {
      window.clearTimeout(timeout);
      video.removeEventListener("loadedmetadata", onReady);
      video.removeEventListener("loadeddata", onReady);
      video.removeEventListener("canplay", onReady);
    };
    video.addEventListener("loadedmetadata", onReady);
    video.addEventListener("loadeddata", onReady);
    video.addEventListener("canplay", onReady);
  });
}

/**
 * Build the mobile-friendly preview overlay and technical capture elements.
 *
 * @returns {{overlay: HTMLElement, video: HTMLVideoElement, canvas: HTMLCanvasElement, preview: HTMLImageElement, status: HTMLElement, captureButton: HTMLButtonElement, closeButton: HTMLButtonElement, remove: Function}} Capture elements.
 */
function createCaptureOverlay() {
  const overlay = document.createElement("div");
  overlay.className = "camera-photo-preview-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.innerHTML = `
    <div class="camera-photo-preview-shell">
      <div class="camera-photo-preview-stage">
        <video class="camera-photo-preview-video" autoplay muted playsinline></video>
        <canvas hidden></canvas>
        <img class="camera-photo-preview-image" alt="" hidden />
      </div>
      <div class="camera-photo-preview-controls">
        <button class="camera-photo-preview-close" type="button" aria-label="Close">Close</button>
        <button class="camera-photo-preview-shot" type="button" aria-label="Prendre la photo"></button>
      </div>
      <p class="camera-photo-preview-status">Opening the camera...</p>
    </div>
  `;
  document.body.append(overlay);
  const video = overlay.querySelector("video");
  const canvas = overlay.querySelector("canvas");
  const preview = overlay.querySelector("img");
  const status = overlay.querySelector(".camera-photo-preview-status");
  const captureButton = overlay.querySelector(".camera-photo-preview-shot");
  const closeButton = overlay.querySelector(".camera-photo-preview-close");
  if (
    !(video instanceof HTMLVideoElement) ||
    !(canvas instanceof HTMLCanvasElement) ||
    !(preview instanceof HTMLImageElement) ||
    !(status instanceof HTMLElement) ||
    !(captureButton instanceof HTMLButtonElement) ||
    !(closeButton instanceof HTMLButtonElement)
  ) {
    overlay.remove();
    throw new Error("camera_overlay_unavailable");
  }
  return {
    overlay,
    video,
    canvas,
    preview,
    status,
    captureButton,
    closeButton,
    remove: () => overlay.remove(),
  };
}

/**
 * Build hidden technical media elements used as a desktop fallback.
 *
 * @returns {{video: HTMLVideoElement, canvas: HTMLCanvasElement, remove: Function}} Capture elements.
 */
function createHiddenCaptureElements() {
  const video = document.createElement("video");
  video.autoplay = true;
  video.muted = true;
  video.playsInline = true;
  video.setAttribute("playsinline", "");
  video.style.position = "fixed";
  video.style.left = "-10000px";
  video.style.top = "0";
  video.style.width = "1px";
  video.style.height = "1px";
  video.style.opacity = "0";
  video.style.pointerEvents = "none";
  const canvas = document.createElement("canvas");
  document.body.append(video);
  return {
    video,
    canvas,
    remove: () => video.remove(),
  };
}

/**
 * Persist a frame from the active video element through the block UI action.
 *
 * @param {HTMLVideoElement} video - Video element carrying the active stream.
 * @param {HTMLCanvasElement} canvas - Technical canvas used to create the image.
 * @param {object} api - Generic block UI API exposed by the framework.
 * @param {object} config - Capture config persisted with the image.
 * @returns {Promise<string>} Saved relative path when available.
 */
async function persistVideoFrame(video, canvas, api, config) {
  const width = video.videoWidth || 1280;
  const height = video.videoHeight || 720;
  canvas.width = width;
  canvas.height = height;
  const drawingContext = canvas.getContext("2d");
  if (!drawingContext) {
    throw new Error("camera_canvas_unavailable");
  }
  drawingContext.drawImage(video, 0, 0, width, height);
  const dataUrl = canvas.toDataURL("image/jpeg", config.jpeg_quality);
  const result = await api.applyAction("capture_browser_photo", {
    data_url: dataUrl,
    config,
  });
  return String(result?.saved_path || result?.node_patch?.config?.latest_capture_path || "");
}

/**
 * Open an overlay, show live camera preview, and save only when the user taps the shutter.
 *
 * @param {HTMLElement} root - Camera node-card root.
 * @param {object} api - Generic block UI API exposed by the framework.
 * @param {object} context - Node-card render context from block.py.
 * @returns {Promise<void>} Resolves when capture handling is complete.
 */
async function openCaptureOverlay(root, api, context) {
  const button = root.querySelector("[data-camera-photo-capture]");
  if (!(button instanceof HTMLButtonElement) || button.disabled) {
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    api.log?.("[camera] navigator.mediaDevices.getUserMedia unavailable.");
    return;
  }
  if (window.isSecureContext === false) {
    api.log?.("[camera-error] The browser camera requires HTTPS on mobile.");
    return;
  }
  if (typeof api.applyAction !== "function") {
    api.log?.("[camera-error] Action UI de carte indisponible.");
    return;
  }

  const config = captureConfig(context || {});
  const elements = createCaptureOverlay();
  let stream = null;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  elements.captureButton.disabled = true;
  let closed = false;
  const close = () => {
    closed = true;
    stopStream(stream);
    elements.video.srcObject = null;
    elements.remove();
    button.removeAttribute("aria-busy");
    button.disabled = false;
  };
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: videoConstraints(config),
      audio: false,
    });
    elements.video.srcObject = stream;
    await elements.video.play();
    await waitForVideoFrame(elements.video);
    elements.status.textContent = "Frame the shot, then press the button.";
    elements.captureButton.disabled = false;
    elements.captureButton.addEventListener("click", async () => {
      if (closed || elements.captureButton.disabled) {
        return;
      }
      elements.captureButton.disabled = true;
      elements.status.textContent = "Saving the photo...";
      try {
        const savedPath = await persistVideoFrame(elements.video, elements.canvas, api, config);
        elements.preview.src = elements.canvas.toDataURL("image/jpeg", config.jpeg_quality);
        elements.preview.hidden = false;
        elements.status.textContent = savedPath ? `Photo saved: ${savedPath}` : "Photo saved.";
        api.log?.(savedPath ? `[camera] Photo saved from the card: ${savedPath}` : "[camera] Photo saved from the card.");
        window.setTimeout(close, 450);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error || "erreur inconnue");
        elements.status.textContent = `Enregistrement impossible: ${message}`;
        elements.captureButton.disabled = false;
        api.log?.(`[camera-error] Saving from the card failed: ${message}`);
      }
    });
    elements.closeButton.addEventListener("click", close);
    elements.overlay.addEventListener("click", (event) => {
      if (event.target === elements.overlay) {
        close();
      }
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error || "erreur inconnue");
    api.log?.(`[camera-error] Opening the camera from the card failed: ${message}`);
    close();
  }
}

/**
 * Capture immediately without preview for callers that explicitly need the old behavior.
 *
 * @param {HTMLElement} root - Camera node-card root.
 * @param {object} api - Generic block UI API exposed by the framework.
 * @param {object} context - Node-card render context from block.py.
 * @returns {Promise<void>} Resolves when capture handling is complete.
 */
async function captureFromNodeCard(root, api, context) {
  const config = captureConfig(context || {});
  const elements = createHiddenCaptureElements();
  let stream = null;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: videoConstraints(config),
      audio: false,
    });
    elements.video.srcObject = stream;
    await elements.video.play();
    await waitForVideoFrame(elements.video);
    const savedPath = await persistVideoFrame(elements.video, elements.canvas, api, config);
    api.log?.(savedPath ? `[camera] Photo saved from the card: ${savedPath}` : "[camera] Photo saved from the card.");
  } finally {
    stopStream(stream);
    elements.video.srcObject = null;
    elements.remove();
  }
}

/**
 * Bind the direct capture button rendered inside the Camera Photo node card.
 *
 * @param {HTMLElement} root - Mounted node-card root.
 * @param {object} api - Generic block UI API.
 * @param {object} context - Node-card render context.
 * @returns {void}
 */
export function mount(root, api, context) {
  const button = root.querySelector("[data-camera-photo-capture]");
  if (!(button instanceof HTMLButtonElement)) {
    return;
  }
  button.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    event.stopPropagation();
  });
  button.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    void openCaptureOverlay(root, api || {}, context || {});
  });
  root.__cwCameraPhotoOpenCaptureOverlay = () => openCaptureOverlay(root, api || {}, context || {});
  root.__cwCameraPhotoCaptureNow = () => captureFromNodeCard(root, api || {}, context || {});
}
