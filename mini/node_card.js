/**
 * Role: Mounts the Camera Photo mini-card behavior for compact displays.
 * File Name: node_card.js
 */
/**
 * Trigger the best available compact capture flow.
 *
 * The mini-card first reuses the full camera node-card behavior when it is
 * already loaded, then falls back to framework-provided generic actions.
 *
 * @param {HTMLElement} root - Mounted mini-card root.
 * @param {object} api - Generic block UI API supplied by the compact view.
 * @param {object} context - Camera render context from block.py.
 * @returns {void}
 */
function triggerCapture(root, api, context) {
  if (typeof root.__cwCameraPhotoOpenCaptureOverlay === "function") {
    void root.__cwCameraPhotoOpenCaptureOverlay();
    return;
  }
  registry.camera_photoNodeCard?.mount?.(root, api || {}, context || {});
  if (typeof root.__cwCameraPhotoOpenCaptureOverlay === "function") {
    void root.__cwCameraPhotoOpenCaptureOverlay();
    return;
  }
  if (typeof api?.actions?.openCameraCapture === "function") {
    api.actions.openCameraCapture(root, context || {});
    return;
  }
  api?.actions?.openBlockModal?.(context?.node_id || context?.nodeId || "");
}

/**
 * Bind tap/click activation for the compact Camera Photo card.
 *
 * @param {HTMLElement} root - Mounted mini-card root.
 * @param {object} api - Generic compact block UI API.
 * @param {object} context - Camera render context.
 * @returns {void}
 */
export function mount(root, api, context) {
  if (!root || root.dataset.cameraPhotoMiniBound === "true") {
    return;
  }
  root.dataset.cameraPhotoMiniBound = "true";
  root.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    triggerCapture(root, api || {}, context || {});
  });
  root.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    event.preventDefault();
    triggerCapture(root, api || {}, context || {});
  });
}
