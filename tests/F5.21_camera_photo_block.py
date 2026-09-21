#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Role: Verifies browser-backed camera photo block behavior without requiring hardware.
# File Name: F5.21_camera_photo_block.py
# Author: Alexandre EL
# Email: alex@hackinvent.com
# Created Date: 2026-05-19
# -----------------------------------------------------------------------------

# Test cases:
# - FB1 - Render the modal and node-card browser capture controls with declared getUserMedia JS assets.
# - FB2 - Save a browser-submitted image data URL under the configured output directory.
# - FB3 - Emit the saved browser capture path as image/path directly and in centralized/zeromq_active runs.
# - FB4 - Render editable browser capture settings without legacy server camera fields.

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen
import tempfile
import sys


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
TESTS_DIR = ROOT_DIR / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from blocs import get_block_definition
from bloxsmith_app.block_runtime import BlockRuntimeContext
from bloxsmith_app.port_types import IMAGE_PATH
from ui_smoke_common import create_project_api, create_run_api, expect, http_json, isolated_server, wait_for_run_terminal
from urllib.parse import quote
from block_test_packages import install_test_package, release_key, surface_payload


JPEG_BYTES = b"\xff\xd8\xff\xe0browser camera jpeg\xff\xd9"


def data_url() -> str:
    """Return a small browser-like JPEG data URL for capture tests."""

    return "data:image/jpeg;base64," + base64.b64encode(JPEG_BYTES).decode("ascii")


def context(root_dir: Path, latest_capture_path: str) -> BlockRuntimeContext:
    """Build a direct runtime context for the Camera Photo block."""

    return BlockRuntimeContext(
        run_id="run-camera-test",
        node_id="camera-photo-1",
        kind="camera_photo",
        title="Camera",
        config={
            "resolution": "640x480",
            "camera_facing": "environment",
            "output_dir": "exports/camera-test",
            "latest_capture_path": latest_capture_path,
        },
        inputs={},
        input_content_types={},
        input_message="",
        input_ports=(),
        output_ports=(SimpleNamespace(id=1, name="photo"),),
        root_dir=root_dir,
    )


def camera_display_document(config: dict) -> dict:
    """Return a minimal graph that routes the camera photo path to Display."""

    return {
        "kind": "bloxsmith.graph",
        "schema_version": "2",
        "graph_id": "",
        "title": "Camera Photo Test",
        "editor": {"viewport": {"x": 0, "y": 0, "zoom": 0.75}},
        "nodes": [
            {
                "id": "camera-photo-1",
                "kind": "camera_photo",
                "title": "Camera navigateur",
                "position": {"x": 80, "y": 120},
                "inputs": [],
                "outputs": [
                    {
                        "id": 1,
                        "name": "photo",
                        "title": "Photo",
                        "emits": ["image/path", "file/path", "message/*"],
                        "multiplicity": "many",
                    }
                ],
                "config": dict(config),
            },
            {
                "id": "display-1",
                "kind": "display",
                "title": "Affichage",
                "position": {"x": 360, "y": 120},
                "inputs": [
                    {
                        "id": 1,
                        "name": "photo",
                        "title": "Photo",
                        "accepts": ["image/path", "file/path", "message/*"],
                        "multiplicity": "many",
                    }
                ],
                "outputs": [],
                "config": {},
            },
        ],
        "edges": [
            {
                "id": "edge-camera-display",
                "from": {"node": "camera-photo-1", "port": 1},
                "to": {"node": "display-1", "port": 1},
                "kind": "data",
            }
        ],
        "inputs": [],
        "outputs": [],
    }


def main() -> None:
    block = get_block_definition("camera_photo")
    with tempfile.TemporaryDirectory() as tmp_dir:
        root_dir = Path(tmp_dir)
        capture_path = root_dir / "exports/camera-test/camera-photo-1_browser_test.jpg"
        capture_path.parent.mkdir(parents=True, exist_ok=True)
        capture_path.write_bytes(JPEG_BYTES)
        result = block.execute_runtime(context(root_dir, "exports/camera-test/camera-photo-1_browser_test.jpg"))
        expect(result.status == "success", "The saved browser capture must be emitted.")
        expect(result.outputs and result.outputs[0].content_type == IMAGE_PATH, "The output must be image/path.")
        expect(Path(result.outputs[0].value).is_file(), "The emitted path must point to the saved file.")

        failed = block.execute_runtime(context(root_dir, ""))
        expect(failed.status == "failed", "Without a browser capture, the block must fail cleanly.")
        expect("No browser image captured" in failed.error, "The error must ask for a browser capture.")

    node = block.build_node_payload(node_id="camera-photo-ui")
    card = block.render_node_card(node=node)
    expect("Camera" in card["html"], "The node card must render the Camera block.")
    expect("Navigateur web" in card["html"], "The node card must show the browser source.")
    expect("data-camera-photo-capture" in card["html"], "The node card must expose the capture button.")
    expect('aria-label="Take a photo"' in card["html"], "The capture button must be accessible.")
    expect(card.get("context", {}).get("resolution") == "1280x720", "The node card must receive the resolution.")
    expect(card.get("context", {}).get("camera_facing") == "environment", "The node card must request the rear camera by default.")
    expect(card.get("context", {}).get("output_dir") == "exports/camera", "The node card must receive output_dir.")
    mini_card = block.render_mini_node_card(node=node)
    expect("data-camera-photo-mini-card" in mini_card["html"], "The mini card must be rendered by the Camera block.")
    expect("Toucher pour capturer" in mini_card["html"], "The mini card must expose the compact capture action.")
    inspector = block.render_inspector_panel(node=node)
    expect("data-block-config-field=\"camera_facing\"" in inspector["html"], "The inspector must expose the front/rear camera.")
    expect("data-block-config-field=\"jpeg_quality\"" in inspector["html"], "The inspector must expose the JPEG quality.")
    expect("data-block-config-field=\"device\"" not in inspector["html"], "The inspector must no longer expose the server device.")
    modal = block.render_modal(node=node)
    expect("data-camera-browser-start" in modal["html"], "The modal must expose the browser camera opening.")
    expect("data-block-config-field=\"resolution\"" in modal["html"], "The modal must expose the resolution.")
    expect("data-block-config-field=\"camera_facing\"" in modal["html"], "The modal must expose the front/rear camera.")

    with isolated_server() as server:
        # Surfaces are release assets: a bundled kind serves none of them.
        model = install_test_package(server, "camera_photo")
        key = quote(release_key(model), safe="")
        served = lambda payload, suffix: next(
            asset["path"] for asset in payload["assets"] if asset["path"].endswith(suffix))
        node = block.build_node_payload(
            node_id="camera-photo-1",
            config_overrides={"resolution": "640x480", "output_dir": "exports/camera-api"},
        )
        rendered = surface_payload(server, model, node, "modal")
        assets = rendered.get("assets") or []
        rendered_card = surface_payload(server, model, node, "node_card")
        card_assets = rendered_card.get("assets") or []
        with urlopen(
            f"{server.base_url}/api/blocks/{key}/assets/{served(rendered, 'assets/js/block_modal.js')}",
            timeout=5,
        ) as response:
            js_body = response.read().decode("utf-8")
        expect("getUserMedia" in js_body, "The modal JS must use getUserMedia.")
        expect("facingMode" in js_body, "The modal JS must request the front/rear camera.")
        with urlopen(
            f"{server.base_url}/api/blocks/{key}/assets/{served(rendered_card, 'assets/js/node_card.js')}",
            timeout=5,
        ) as response:
            node_card_js_body = response.read().decode("utf-8")
        expect("getUserMedia" in node_card_js_body, "The node card JS must use getUserMedia.")
        expect("camera-photo-preview-overlay" in node_card_js_body, "The node card JS must show a preview before capture.")
        expect("facingMode" in node_card_js_body, "The node card JS must request the front/rear camera.")
        expect('applyAction("capture_browser_photo"' in node_card_js_body, "The node card JS must call the existing action.")
        expect("stopStream(stream)" in node_card_js_body, "The node card JS must stop the stream in finally.")
        expect("stopPropagation" in node_card_js_body, "The node card button must isolate its click from the canvas.")

        applied = http_json(
            server.base_url,
            "/api/blocks/camera_photo/ui-action",
            method="POST",
            payload={
                "node": node,
                "action": "capture_browser_photo",
                "values": {
                    "data_url": data_url(),
                    "config": {
                        "resolution": "640x480",
                        "camera_facing": "environment",
                        "jpeg_quality": 0.8,
                        "output_dir": "exports/camera-api",
                    },
                },
            },
        )
        saved_path = str(applied.get("saved_path") or "")
        expect(saved_path.startswith("exports/camera-api/"), "The capture must honor output_dir.")
        expect((server.root_dir / saved_path).read_bytes() == JPEG_BYTES, "The capture must be written on the server.")

        document_for_patch = camera_display_document(node.get("config") or {})
        created_project = create_project_api(server, title="Camera Photo Graph Patch", document=document_for_patch)
        project_id = str(created_project["project"]["project_id"])
        graph_state = http_json(server.base_url, f"/api/projects/{project_id}/graph/state")
        graph_node = next(item for item in graph_state["document"]["nodes"] if item["id"] == "camera-photo-1")
        patched = http_json(
            server.base_url,
            "/api/blocks/camera_photo/ui-action",
            method="POST",
            payload={
                "project_id": project_id,
                "base_version": graph_state["version"],
                "apply_graph_patch": True,
                "op_id_prefix": "camera-node-card",
                "node": graph_node,
                "action": "capture_browser_photo",
                "values": {
                    "data_url": data_url(),
                    "config": {
                        "resolution": "640x480",
                        "camera_facing": "environment",
                        "jpeg_quality": 0.8,
                        "output_dir": "exports/camera-api",
                    },
                },
            },
        )
        expect(patched.get("graph_patch", {}).get("ok") is True, f"The node-card capture must patch the graph: {patched}")
        updated_graph = http_json(server.base_url, f"/api/projects/{project_id}/graph/state")
        updated_camera = next(item for item in updated_graph["document"]["nodes"] if item["id"] == "camera-photo-1")
        patched_path = str(updated_camera.get("config", {}).get("latest_capture_path") or "")
        expect(patched_path.startswith("exports/camera-api/"), "latest_capture_path must be persisted in the graph.")

        config = dict(node.get("config") or {})
        config.update(applied.get("node_patch", {}).get("config") or {})
        document = camera_display_document(config)
        for runtime_mode in ("centralized", "zeromq_active"):
            created = create_run_api(server, document, runtime_mode=runtime_mode)
            run = wait_for_run_terminal(server, str(created.get("run_id") or ""), timeout_sec=15)
            expect(run.get("status") == "success", f"The Camera run must succeed in {runtime_mode}.")
            camera_result = run.get("results", {}).get("camera-photo-1", {})
            expect(camera_result.get("content_type") == IMAGE_PATH, f"Camera doit emettre image/path en {runtime_mode}.")
            expect(saved_path in str(camera_result.get("last_message") or ""), f"Camera must emit the capture in {runtime_mode}.")
            display_result = run.get("results", {}).get("display-1", {})
            expect(saved_path in str(display_result.get("last_message") or ""), f"Display must receive the photo in {runtime_mode}.")

    print("[ok] F5.21_camera_photo_block")


if __name__ == "__main__":
    main()
