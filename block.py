# -----------------------------------------------------------------------------
# Role: Implements the camera photo block runtime and UI contract.
# File Name: block.py
# Author: Alexandre EL
# Email: alex@hackinvent.com
# Created Date: 2026-05-19
# -----------------------------------------------------------------------------

from __future__ import annotations

import base64
import binascii
from html import escape
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import re
import time

from bloxsmith_app.block_api import (
    BlockDefinition,
    BlockRuntimeContext,
    BlockRuntimeOutput,
    BlockRuntimeResult,
    IMAGE_PATH,
    render_inspector_template,
    render_mini_node_card_template,
    render_node_card_template,
)


DEFAULT_CAMERA_RESOLUTION = "1280x720"
DEFAULT_CAMERA_OUTPUT_DIR = "exports/camera"
DEFAULT_BROWSER_JPEG_QUALITY = 0.92
DEFAULT_CAPTURE_SOURCE = "browser"
DEFAULT_CAMERA_FACING = "environment"
SUPPORTED_CAMERA_FACING = {"environment", "user"}
MAX_BROWSER_CAPTURE_BYTES = 12 * 1024 * 1024
SUPPORTED_BROWSER_MIME_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


# Functional behavior:
# FB1 - Capture one still image from the operator browser through block-owned HTML/JS.
# FB2 - Store the browser-submitted image under the configured exports/camera directory.
# FB3 - Emit the latest browser-captured image path as image/path in both runtime modes.
# FB4 - Keep capture settings editable through block-owned modal and inspector HTML.
class CameraPhotoBlock(BlockDefinition):
    """Capture and publish browser-camera still images as project-local files.

    The block keeps capture configuration in node config, lets block-owned UI
    assets perform browser capture, and exposes the latest saved image path to
    both centralized and active runtimes.
    """

    kind = "camera_photo"

    def ui_assets(self, surface: str = "modal") -> list[dict[str, str]]:
        """Return frontend assets for each camera block UI surface.

        Args:
            surface: Requested UI surface name.

        Returns:
            CSS and JavaScript assets declared for the requested surface.
        """

        if surface == "modal":
            return [
                {"kind": "css", "path": "assets/css/block_ui.css"},
                {"kind": "js", "path": "assets/js/block_modal.js"},
            ]
        if surface == "inspector_panel":
            return [{"kind": "css", "path": "assets/css/block_ui.css"}]
        if surface == "node_card":
            return [
                {"kind": "css", "path": "assets/css/block_ui.css"},
                {"kind": "js", "path": "assets/js/node_card.js"},
            ]
        if surface == "mini_node_card":
            return [
                {"kind": "css", "path": "assets/css/block_ui.css"},
                {"kind": "js", "path": "assets/js/node_card.js"},
                {"kind": "css", "path": "mini/node_card.css"},
                {"kind": "js", "path": "mini/node_card.js"},
            ]
        return []

    def render_node_card(self, *, node: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Render the camera block canvas body.

        Args:
            node: Serialized camera node whose config stores capture settings.
            payload: Optional UI payload.

        Returns:
            Block UI payload consumed by the generic canvas shell.
        """

        config = self._ui_config(node)
        rendered = render_node_card_template(
            block=self,
            node=node,
            node_classes=["camera-photo-node"],
            replacements={
                "title": node.get("title") or self.default_title(),
                "source": "Navigateur web",
                "resolution": config["resolution"],
                "last_capture": config["latest_capture_path"] or "Aucune capture",
            },
        )
        context = dict(rendered.get("context") if isinstance(rendered.get("context"), dict) else {})
        context.update(
            {
                "resolution": config["resolution"],
                "camera_facing": config["camera_facing"],
                "jpeg_quality": config["jpeg_quality"],
                "output_dir": config["output_dir"],
            }
        )
        rendered["context"] = context
        return rendered

    def render_mini_node_card(self, *, node: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Render the compact Camera Photo card for reduced displays.

        Args:
            node: Serialized camera node whose config stores capture settings.
            payload: Optional compact UI payload.

        Returns:
            Block UI payload consumed by the generic compact view.
        """

        config = self._ui_config(node)
        rendered = render_mini_node_card_template(
            block=self,
            node=node,
            node_classes=["camera-photo-mini-node"],
            replacements={
                "title": node.get("title") or self.default_title(),
                "resolution": config["resolution"],
            },
        )
        context = dict(rendered.get("context") if isinstance(rendered.get("context"), dict) else {})
        context.update(
            {
                "resolution": config["resolution"],
                "camera_facing": config["camera_facing"],
                "jpeg_quality": config["jpeg_quality"],
                "output_dir": config["output_dir"],
            }
        )
        rendered["context"] = context
        return rendered

    def render_inspector_panel(self, *, node: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Render the camera inspector panel with editable capture settings."""

        config = self._ui_config(node)
        template = (self.directory / "inspector_panel.html").read_text(encoding="utf-8")
        html = render_inspector_template(
            template=template,
            node={**node, "type": self.kind, "kind": self.kind},
            payload=payload,
            replacements=self._template_replacements(config),
            show_duplicate=True,
        )
        return {"html": html, "context": {"node_id": str(node.get("id") or ""), "full_panel": True}}

    def render_modal(self, *, node: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Render the camera modal with configuration, ports, and runtime state."""

        config = self._ui_config(node)
        template = (self.directory / "block_modal.html").read_text(encoding="utf-8")
        html = self._render_generic_modal_template(template=template, node=node, payload=payload or {})
        for key, value in self._template_replacements(config).items():
            html = html.replace(f"{{{{ {key} }}}}", str(value))
        return {
            "html": html,
            "context": {
                "node_id": str(node.get("id") or ""),
                "node_kind": self.kind,
                "resolution": config["resolution"],
                "camera_facing": config["camera_facing"],
            },
        }

    def execute_runtime(self, context: BlockRuntimeContext) -> BlockRuntimeResult:
        """Emit the latest browser-captured photo path.

        Args:
            context: Runtime context containing persisted browser capture config.

        Returns:
            Successful image/path output when a browser capture has already been
            saved, otherwise a failed result with actionable logs.
        """

        config = self._runtime_config(context.config)
        logs = [
            (
                f"[camera] {context.node_id}: source={config['capture_source']} "
                f"resolution={config['resolution']} camera={config['camera_facing']} "
                f"latest={config['latest_capture_path'] or '-'}."
            )
        ]
        output_path = self._resolve_existing_capture_path(context.root_dir, config["latest_capture_path"])
        if output_path is None:
            error = "Aucune image navigateur capturee. Ouvrez le modal du bloc et enregistrez une photo."
            logs.append(f"[camera-error] {context.node_id}: {error}")
            return self._failed(error, logs)

        value = str(output_path)
        logs.append(f"[done] Camera {context.node_id}: photo navigateur disponible: {value}")
        output_ports = tuple(context.output_ports or ())
        if not output_ports:
            output_ports = (SimpleNamespace(id=1, name="photo"),)
        outputs = [
            BlockRuntimeOutput(
                port_id=int(getattr(port, "id", 1) or 1),
                port_name=str(getattr(port, "name", "") or "photo"),
                value=value,
                content_type=IMAGE_PATH,
                metadata={
                    "capture_source": config["capture_source"],
                    "resolution": config["resolution"],
                    "camera_facing": config["camera_facing"],
                    "output_dir": config["output_dir"],
                },
            )
            for port in output_ports
        ]
        return BlockRuntimeResult(
            status="success",
            outputs=outputs,
            logs=logs,
            last_message=value,
            content_type=IMAGE_PATH,
            worker_received=value,
            metadata={
                "capture_source": config["capture_source"],
                "resolution": config["resolution"],
                "camera_facing": config["camera_facing"],
                "output_dir": config["output_dir"],
                "output_path": value,
            },
        )

    def handle_ui_action(
        self,
        *,
        node: dict[str, Any],
        action: str,
        values: dict[str, Any],
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Handle browser camera capture actions emitted by the modal JS.

        Args:
            node: Serialized camera node being edited.
            action: Block-owned action name.
            values: Payload containing a browser image data URL and config values.
            payload: Optional framework request context.

        Returns:
            A node config patch storing the latest saved capture path.
        """

        if action == "capture_browser_photo":
            return self._handle_browser_capture_action(node=node, values=values)
        if action in {"inspector_update_fields", "modal_update_fields"}:
            return super().handle_ui_action(node=node, action=action, values=values, payload=payload)
        return {"error": f"unsupported_action:{action}"}

    def preview_received(self, *, node: Any, **runtime_services: Any) -> str:
        """Return the latest browser capture path for runtime previews."""

        config = self._runtime_config(getattr(node, "config", {}) or {})
        return config["latest_capture_path"] or "Aucune capture navigateur"

    def _ui_config(self, node: dict[str, Any]) -> dict[str, Any]:
        """Return normalized capture settings from a serialized node."""

        return self._runtime_config(node.get("config") if isinstance(node.get("config"), dict) else {})

    def _runtime_config(self, raw_config: dict[str, Any]) -> dict[str, Any]:
        """Normalize and validate runtime config values without accessing hardware."""

        config = raw_config if isinstance(raw_config, dict) else {}
        return {
            "resolution": self._normalize_resolution(config.get("resolution")),
            "camera_facing": self._normalize_camera_facing(config.get("camera_facing")),
            "jpeg_quality": self._normalize_jpeg_quality(config.get("jpeg_quality")),
            "output_dir": self._normalize_output_dir(config.get("output_dir")),
            "latest_capture_path": self._normalize_latest_capture_path(config.get("latest_capture_path")),
            "latest_capture_mime": self._normalize_mime_type(config.get("latest_capture_mime")),
            "latest_capture_at": str(config.get("latest_capture_at") or "").strip(),
            "capture_source": DEFAULT_CAPTURE_SOURCE,
        }

    def _template_replacements(self, config: dict[str, Any]) -> dict[str, str]:
        """Build escaped HTML replacements for modal and inspector templates."""

        latest_capture_path = config["latest_capture_path"]
        return {
            "resolution": escape(config["resolution"], quote=True),
            "camera_facing_environment_selected": "selected" if config["camera_facing"] == "environment" else "",
            "camera_facing_user_selected": "selected" if config["camera_facing"] == "user" else "",
            "jpeg_quality": str(config["jpeg_quality"]),
            "output_dir": escape(config["output_dir"], quote=True),
            "latest_capture_path": escape(latest_capture_path or "Aucune capture enregistree.", quote=True),
            "latest_capture_value": escape(latest_capture_path, quote=True),
            "latest_capture_hidden": "hidden" if not latest_capture_path else "",
            "latest_capture_at": escape(config["latest_capture_at"] or "-", quote=True),
        }

    def _handle_browser_capture_action(self, *, node: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
        """Persist a browser-submitted image and return a durable config patch.

        Args:
            node: Serialized camera node whose id prefixes the output filename.
            values: Action payload with ``data_url`` and optional pending config.

        Returns:
            UI action result containing the saved relative path and node config patch.
        """

        raw_config = dict(node.get("config") if isinstance(node.get("config"), dict) else {})
        pending_config = values.get("config") if isinstance(values, dict) else {}
        if isinstance(pending_config, dict):
            raw_config.update(pending_config)
        config = self._runtime_config(raw_config)
        try:
            mime_type, image_bytes = self._decode_browser_data_url(values.get("data_url"))
            output_path = self._browser_output_path(
                root_dir=self._ui_root_dir(),
                config=config,
                mime_type=mime_type,
                node_id=str(node.get("id") or "camera"),
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(image_bytes)
        except ValueError as exc:
            return {"error": str(exc)}
        relative_path = self._relative_path(self._ui_root_dir(), output_path)
        captured_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        config_patch = {
            "resolution": config["resolution"],
            "camera_facing": config["camera_facing"],
            "jpeg_quality": config["jpeg_quality"],
            "output_dir": config["output_dir"],
            "latest_capture_path": relative_path,
            "latest_capture_mime": mime_type,
            "latest_capture_at": captured_at,
            "capture_source": DEFAULT_CAPTURE_SOURCE,
        }
        return {
            "node_patch": {"config": config_patch},
            "rerender_inspector": False,
            "saved_path": relative_path,
            "message": f"[camera] Photo navigateur enregistree: {relative_path}",
        }

    def _decode_browser_data_url(self, data_url: Any) -> tuple[str, bytes]:
        """Decode and validate a browser canvas data URL."""

        text = str(data_url or "").strip()
        if "," not in text:
            raise ValueError("capture_browser_data_url_invalide")
        header, encoded = text.split(",", 1)
        match = re.fullmatch(r"data:(image/(?:jpeg|png|webp));base64", header.strip(), flags=re.IGNORECASE)
        if not match:
            raise ValueError("format_image_navigateur_non_supporte")
        mime_type = match.group(1).lower()
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("capture_browser_base64_invalide") from exc
        if not image_bytes:
            raise ValueError("capture_browser_vide")
        if len(image_bytes) > MAX_BROWSER_CAPTURE_BYTES:
            raise ValueError("capture_browser_trop_volumineuse")
        return mime_type, image_bytes

    def _browser_output_path(self, *, root_dir: Path, config: dict[str, Any], mime_type: str, node_id: str) -> Path:
        """Build a unique browser capture output path under the configured directory."""

        output_dir = self._resolve_output_dir(root_dir, config["output_dir"])
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        millis = int(time.time() * 1000) % 1000
        safe_node_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", node_id or "camera")
        extension = SUPPORTED_BROWSER_MIME_TYPES.get(mime_type, ".jpg")
        return output_dir / f"{safe_node_id}_browser_{timestamp}-{millis:03d}{extension}"

    def _resolve_output_dir(self, root_dir: Path, output_dir: str) -> Path:
        """Return a safe output directory inside the application root."""

        output_path = (root_dir / output_dir).resolve()
        try:
            output_path.relative_to(root_dir.resolve())
        except ValueError:
            output_path = (root_dir / DEFAULT_CAMERA_OUTPUT_DIR).resolve()
        return output_path

    def _resolve_existing_capture_path(self, root_dir: Path, latest_capture_path: str) -> Path | None:
        """Resolve a persisted capture path and ensure it points to a readable file."""

        text = str(latest_capture_path or "").strip()
        if not text:
            return None
        candidate = Path(text)
        output_path = candidate.resolve() if candidate.is_absolute() else (root_dir / candidate).resolve()
        try:
            output_path.relative_to(root_dir.resolve())
        except ValueError:
            return None
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            return None
        return output_path

    def _relative_path(self, root_dir: Path, output_path: Path) -> str:
        """Return a POSIX relative output path when possible."""

        try:
            return output_path.resolve().relative_to(root_dir.resolve()).as_posix()
        except ValueError:
            return output_path.as_posix()

    def _ui_root_dir(self) -> Path:
        """Return the application root used by block UI actions."""

        return self.directory.parent.parent

    def _failed(self, error: str, logs: list[str], *, exit_code: int = 1) -> BlockRuntimeResult:
        """Return a standardized failed runtime result."""

        return BlockRuntimeResult(
            status="failed",
            outputs=[],
            logs=logs,
            error=error,
            exit_code=exit_code,
            last_message=error,
            content_type=IMAGE_PATH,
            worker_received="-",
        )

    def _normalize_resolution(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        return text if re.fullmatch(r"[1-9][0-9]{1,4}x[1-9][0-9]{1,4}", text) else DEFAULT_CAMERA_RESOLUTION

    def _normalize_camera_facing(self, value: Any) -> str:
        """Return the browser camera facing preference for getUserMedia."""

        text = str(value or "").strip().lower()
        return text if text in SUPPORTED_CAMERA_FACING else DEFAULT_CAMERA_FACING

    def _normalize_jpeg_quality(self, value: Any) -> float:
        """Clamp browser JPEG quality to the canvas API range."""

        try:
            quality = float(value)
        except (TypeError, ValueError):
            quality = DEFAULT_BROWSER_JPEG_QUALITY
        return round(min(1.0, max(0.1, quality)), 2)

    def _normalize_output_dir(self, value: Any) -> str:
        text = str(value or "").strip().replace("\\", "/")
        if not text or text.startswith("/") or ".." in Path(text).parts:
            return DEFAULT_CAMERA_OUTPUT_DIR
        return text

    def _normalize_latest_capture_path(self, value: Any) -> str:
        """Normalize the persisted latest capture path without resolving it."""

        text = str(value or "").strip().replace("\\", "/")
        if not text or ".." in Path(text).parts:
            return ""
        return text

    def _normalize_mime_type(self, value: Any) -> str:
        """Return a supported image MIME type or the default browser type."""

        mime_type = str(value or "").strip().lower()
        return mime_type if mime_type in SUPPORTED_BROWSER_MIME_TYPES else "image/jpeg"
