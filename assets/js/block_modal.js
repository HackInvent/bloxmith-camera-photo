import { withProperties } from "./properties.js";

/**
 * Role: Mounts browser-camera capture controls for the Camera Photo modal.
 * File Name: block_modal.js
 * Author: Alexandre EL
 * Email: alex@hackinvent.com
 * Created Date: 2026-05-19
 */
/**
 * Read a config field value from the mounted modal.
 *
 * @param {HTMLElement} root - Camera modal root.
 * @param {string} name - Config field name.
 * @returns {string} Current field value.
 */
function configFieldValue(root, name) {
  const field = root.querySelector(`[data-block-config-field="${name}"]`);
  if (field instanceof HTMLInputElement || field instanceof HTMLSelectElement || field instanceof HTMLTextAreaElement) {
    return field.value;
  }
  return "";
}

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
 * @param {string} rawValue - Raw field value.
 * @returns {number} JPEG quality between 0.1 and 1.
 */
function jpegQuality(rawValue) {
  const parsed = Number(rawValue);
  if (!Number.isFinite(parsed)) {
    return 0.92;
  }
  return Math.min(1, Math.max(0.1, parsed));
}

/**
 * Collect config values that affect browser capture persistence.
 *
 * @param {HTMLElement} root - Camera modal root.
 * @returns {{resolution: string, camera_facing: string, jpeg_quality: number, output_dir: string}} Pending config patch.
 */
function captureConfig(root) {
  return {
    resolution: configFieldValue(root, "resolution"),
    camera_facing: configFieldValue(root, "camera_facing") || "environment",
    jpeg_quality: jpegQuality(configFieldValue(root, "jpeg_quality")),
    output_dir: configFieldValue(root, "output_dir"),
  };
}

/**
 * Build video constraints including mobile front/back camera preference.
 *
 * @param {HTMLElement} root - Camera modal root.
 * @returns {object} getUserMedia video constraints.
 */
function videoConstraints(root) {
  return {
    ...videoSizeConstraint(configFieldValue(root, "resolution")),
    facingMode: { ideal: configFieldValue(root, "camera_facing") || "environment" },
  };
}

/**
 * Set the modal status line.
 *
 * @param {HTMLElement} root - Camera modal root.
 * @param {string} message - Status message.
 */
/**
 * Resolve one block text in the active language, from the catalog of the owning release.
 *
 * @param {HTMLElement} element - Element inside the mounted surface, carrying its release.
 * @param {string} key - Block catalog key.
 * @param {object} params - Placeholder values.
 * @param {string} fallback - Authored English text.
 * @returns {string} Localized text.
 */
function text(element, key, params, fallback) {
  const release = element?.closest?.("[data-block-release]")?.dataset?.blockRelease || "";
  return window.CWI18n?.t?.(key, params, fallback, release) ?? fallback;
}

function setStatus(root, message) {
  const status = root.querySelector("[data-camera-browser-status]");
  if (status) {
    status.textContent = message;
  }
}

/**
 * Stop the active media stream and reset button states.
 *
 * @param {object} state - Modal-local camera state.
 */
function stopCamera(state) {
  if (state.stream) {
    for (const track of state.stream.getTracks()) {
      track.stop();
    }
  }
  state.stream = null;
  if (state.video instanceof HTMLVideoElement) {
    state.video.srcObject = null;
  }
  if (state.startButton instanceof HTMLButtonElement) {
    state.startButton.disabled = false;
  }
  if (state.saveButton instanceof HTMLButtonElement) {
    state.saveButton.disabled = true;
  }
  if (state.stopButton instanceof HTMLButtonElement) {
    state.stopButton.disabled = true;
  }
}

/**
 * Request browser camera access and attach the stream to the modal video.
 *
 * @param {HTMLElement} root - Camera modal root.
 * @param {object} state - Modal-local camera state.
 * @param {object} api - Generic block UI API for logs.
 */
async function startCamera(root, state, api) {
  if (!navigator.mediaDevices?.getUserMedia) {
    setStatus(root, text(root, "block.camera_photo.camera_unavailable_browser", {}, "The browser camera is unavailable."));
    api.log?.("[camera] navigator.mediaDevices.getUserMedia unavailable.");
    return;
  }
  if (state.startButton instanceof HTMLButtonElement) {
    state.startButton.disabled = true;
  }
  setStatus(root, text(root, "block.camera_photo.opening_camera", {}, "Opening the browser camera..."));
  try {
    const constraints = {
      video: videoConstraints(root),
      audio: false,
    };
    const stream = await navigator.mediaDevices.getUserMedia(constraints);
    state.stream = stream;
    state.video.srcObject = stream;
    await state.video.play();
    if (state.saveButton instanceof HTMLButtonElement) {
      state.saveButton.disabled = false;
    }
    if (state.stopButton instanceof HTMLButtonElement) {
      state.stopButton.disabled = false;
    }
    setStatus(root, text(root, "block.camera_photo.camera_ready", {}, "Camera ready."));
  } catch (error) {
    stopCamera(state);
    const message = error instanceof Error ? error.message : String(error || "unknown error");
    setStatus(root, text(root, "block.camera_photo.open_failed", { error: message }, `Opening the camera failed: ${message}`));
    api.log?.(`[camera-error] Opening the camera failed: ${message}`);
  }
}

/**
 * Capture the current video frame and persist it through the block UI action.
 *
 * @param {HTMLElement} root - Camera modal root.
 * @param {object} state - Modal-local camera state.
 * @param {object} api - Generic block UI API.
 */
async function captureAndSave(root, state, api) {
  if (!state.stream || !(state.video instanceof HTMLVideoElement)) {
    setStatus(root, text(root, "block.camera_photo.camera_not_open", {}, "The camera is not open."));
    return;
  }
  const width = state.video.videoWidth || 1280;
  const height = state.video.videoHeight || 720;
  state.canvas.width = width;
  state.canvas.height = height;
  const context = state.canvas.getContext("2d");
  if (!context) {
    setStatus(root, text(root, "block.camera_photo.canvas_unavailable", {}, "The browser canvas is unavailable."));
    return;
  }
  context.drawImage(state.video, 0, 0, width, height);
  const dataUrl = state.canvas.toDataURL("image/jpeg", jpegQuality(configFieldValue(root, "jpeg_quality")));
  if (state.saveButton instanceof HTMLButtonElement) {
    state.saveButton.disabled = true;
  }
  setStatus(root, text(root, "block.camera_photo.saving_photo", {}, "Saving the photo..."));
  try {
    const result = await api.applyAction("capture_browser_photo", {
      data_url: dataUrl,
      config: captureConfig(root),
    });
    const savedPath = String(result.saved_path || result.node_patch?.config?.latest_capture_path || "");
    if (state.preview instanceof HTMLImageElement) {
      state.preview.src = dataUrl;
      state.preview.hidden = false;
    }
    setStatus(root, savedPath
      ? text(root, "block.camera_photo.photo_saved", { path: savedPath }, `Photo saved: ${savedPath}`)
      : text(root, "block.camera_photo.photo_saved_plain", {}, "Photo saved."));
    api.log?.(savedPath ? `[camera] Photo saved: ${savedPath}` : "[camera] Photo saved.");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error || "unknown error");
    setStatus(root, text(root, "block.camera_photo.save_failed", { error: message }, `Saving failed: ${message}`));
    api.log?.(`[camera-error] Saving failed: ${message}`);
  } finally {
    if (state.saveButton instanceof HTMLButtonElement && state.stream) {
      state.saveButton.disabled = false;
    }
  }
}

/**
 * Bind the Camera Photo modal browser capture controls.
 *
 * @param {HTMLElement} root - Mounted modal root.
 * @param {object} api - Generic block UI API.
 */
function mountOwned(root, api) {
  const video = root.querySelector("[data-camera-browser-video]");
  const canvas = root.querySelector("[data-camera-browser-canvas]");
  const preview = root.querySelector("[data-camera-browser-preview]");
  const startButton = root.querySelector("[data-camera-browser-start]");
  const saveButton = root.querySelector("[data-camera-browser-save]");
  const stopButton = root.querySelector("[data-camera-browser-stop]");
  if (!(video instanceof HTMLVideoElement) || !(canvas instanceof HTMLCanvasElement)) {
    return;
  }
  const state = {
    stream: null,
    video,
    canvas,
    preview,
    startButton,
    saveButton,
    stopButton,
  };
  startButton?.addEventListener("click", (event) => {
    event.preventDefault();
    void startCamera(root, state, api || {});
  });
  saveButton?.addEventListener("click", (event) => {
    event.preventDefault();
    void captureAndSave(root, state, api || {});
  });
  stopButton?.addEventListener("click", (event) => {
    event.preventDefault();
    stopCamera(state);
    setStatus(root, text(root, "block.camera_photo.camera_stopped", {}, "Camera stopped."));
  });
  root.addEventListener("click", (event) => {
    if (event.target.closest("[data-close-block-modal]")) {
      stopCamera(state);
    }
  });
  const observer = new MutationObserver(() => {
    if (!root.isConnected) {
      stopCamera(state);
      observer.disconnect();
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
}

/** Keep the block behavior and add properties-only accessibility. */
export function mount(root, ...args) {
  return withProperties(mountOwned).call(this, root, ...args);
}
