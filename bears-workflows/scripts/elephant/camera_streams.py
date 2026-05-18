"""Combined Pi/CAM2 raw and YOLO viewer for Elephant workflows.

This module uses the camera primitives from `elephant_driver`:

- Pi camera snapshots use `CameraConfig` and `capture_pi_image`.
- CAM2 snapshots use the `elephant_driver.cv` livestream URL and capture helper.

Run this module from a Python environment that has `elephant_driver`, Flask,
OpenCV, and optionally `ultralytics` installed.
"""

from __future__ import annotations

import argparse
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
from flask import Flask, Response

from elephant_driver import CameraConfig
from elephant_driver.camera import capture_pi_image
from elephant_driver.cv import DEFAULT_STREAM_URL, capture_snapshot


COMBINED_VIEWER_HOST = "127.0.0.1"
COMBINED_VIEWER_PORT = 5000
COMBINED_VIEWER_URL = f"http://{COMBINED_VIEWER_HOST}:{COMBINED_VIEWER_PORT}"

PI_CAMERA_RAW_STREAM_URL = f"{COMBINED_VIEWER_URL}/pi_camera"
PI_CAMERA_YOLO_STREAM_URL = f"{COMBINED_VIEWER_URL}/pi_camera_yolo"
PI_CAMERA_RAW_SNAPSHOT_URL = f"{COMBINED_VIEWER_URL}/snapshot/pi_camera"
PI_CAMERA_YOLO_SNAPSHOT_URL = f"{COMBINED_VIEWER_URL}/snapshot/pi_camera_yolo"

CAM2_RAW_STREAM_URL = f"{COMBINED_VIEWER_URL}/cam2"
CAM2_YOLO_STREAM_URL = f"{COMBINED_VIEWER_URL}/cam2_yolo"
CAM2_RAW_SNAPSHOT_URL = f"{COMBINED_VIEWER_URL}/snapshot/cam2"
CAM2_YOLO_SNAPSHOT_URL = f"{COMBINED_VIEWER_URL}/snapshot/cam2_yolo"


@dataclass(frozen=True)
class StreamUrls:
    combined_viewer: str = COMBINED_VIEWER_URL
    pi_raw_stream: str = PI_CAMERA_RAW_STREAM_URL
    pi_yolo_stream: str = PI_CAMERA_YOLO_STREAM_URL
    pi_raw_snapshot: str = PI_CAMERA_RAW_SNAPSHOT_URL
    pi_yolo_snapshot: str = PI_CAMERA_YOLO_SNAPSHOT_URL
    cam2_raw_stream: str = CAM2_RAW_STREAM_URL
    cam2_yolo_stream: str = CAM2_YOLO_STREAM_URL
    cam2_raw_snapshot: str = CAM2_RAW_SNAPSHOT_URL
    cam2_yolo_snapshot: str = CAM2_YOLO_SNAPSHOT_URL


@dataclass
class ViewerConfig:
    pi_ip: str
    pi_username: str = "pi"
    pi_password: str = "elephant"
    pi_local_image_dir: str = "."
    pi_rotate_180: bool = False
    cam2_stream_url: str = DEFAULT_STREAM_URL
    yolo_model_path: str | None = None
    yolo_conf: float = 0.25
    yolo_iou: float = 0.45
    yolo_imgsz: int = 640
    pi_poll_s: float = 1.0
    cam2_poll_s: float = 0.12

    def pi_camera_config(self) -> CameraConfig:
        return CameraConfig(
            pi_ip=self.pi_ip,
            username=self.pi_username,
            password=self.pi_password,
            local_image_dir=self.pi_local_image_dir,
            local_raw_filename="pi_camera_raw.jpg",
            local_optimized_filename="pi_camera_optimized.jpg",
        )


class FrameSource:
    def __init__(self, name: str, capture_fn: Callable[[], str | None], poll_s: float) -> None:
        self.name = name
        self.capture_fn = capture_fn
        self.poll_s = float(poll_s)
        self.frame = None
        self.last_error = ""
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while True:
            try:
                image_path = self.capture_fn()
                if image_path:
                    frame = cv2.imread(str(image_path))
                    if frame is not None:
                        with self._lock:
                            self.frame = frame
                            self.last_error = ""
            except Exception as exc:
                with self._lock:
                    self.last_error = str(exc)
            time.sleep(self.poll_s)

    def get_frame(self):
        with self._lock:
            if self.frame is None:
                return None
            return self.frame.copy()


class YoloOverlay:
    def __init__(self, model_path: str | None, *, conf: float, iou: float, imgsz: int) -> None:
        self.model_path = model_path
        self.conf = float(conf)
        self.iou = float(iou)
        self.imgsz = int(imgsz)
        self._model = None

    def _load(self):
        if self.model_path is None:
            return None
        if self._model is None:
            from ultralytics import YOLO

            self._model = YOLO(self.model_path)
        return self._model

    def draw(self, frame):
        model = self._load()
        if model is None:
            return frame
        result = model.predict(
            frame,
            conf=self.conf,
            iou=self.iou,
            imgsz=self.imgsz,
            verbose=False,
        )[0]
        return result.plot()


def _encode_jpeg(frame, quality: int = 85) -> bytes | None:
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        return None
    return buf.tobytes()


def _mjpeg(source: FrameSource, overlay: YoloOverlay | None = None):
    while True:
        frame = source.get_frame()
        if frame is None:
            frame = 255 * cv2.UMat(360, 640, cv2.CV_8UC3).get()
            cv2.putText(
                frame,
                f"Waiting for {source.name}",
                (24, 180),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 0, 255),
                2,
            )
        elif overlay is not None:
            frame = overlay.draw(frame)

        jpeg = _encode_jpeg(frame)
        if jpeg is not None:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        time.sleep(0.03)


def create_app(config: ViewerConfig) -> Flask:
    app = Flask(__name__)
    workdir = Path(config.pi_local_image_dir)
    workdir.mkdir(parents=True, exist_ok=True)

    pi_config = config.pi_camera_config()
    cam2_snapshot_path = workdir / "cam2_snapshot.jpg"

    pi_source = FrameSource(
        "Pi camera",
        lambda: capture_pi_image(pi_config, rotate=config.pi_rotate_180),
        config.pi_poll_s,
    )
    cam2_source = FrameSource(
        "CAM2 CV livestream",
        lambda: str(cam2_snapshot_path)
        if capture_snapshot(config.cam2_stream_url, cam2_snapshot_path)
        else None,
        config.cam2_poll_s,
    )
    yolo = YoloOverlay(
        config.yolo_model_path,
        conf=config.yolo_conf,
        iou=config.yolo_iou,
        imgsz=config.yolo_imgsz,
    )

    @app.route("/")
    def index():
        return f"""
        <html>
        <head><title>Elephant Combined Viewer</title></head>
        <body style="background:#111;color:white;font-family:Arial,sans-serif;">
            <h1>Elephant Combined Viewer</h1>
            <p>CAM2 source: <code>{config.cam2_stream_url}</code></p>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
                <section><h2>Pi Camera Raw</h2><img src="/pi_camera" width="100%"></section>
                <section><h2>Pi Camera YOLO</h2><img src="/pi_camera_yolo" width="100%"></section>
                <section><h2>CAM2 Raw</h2><img src="/cam2" width="100%"></section>
                <section><h2>CAM2 YOLO</h2><img src="/cam2_yolo" width="100%"></section>
            </div>
        </body>
        </html>
        """

    @app.route("/pi_camera")
    def pi_camera():
        return Response(_mjpeg(pi_source), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.route("/pi_camera_yolo")
    def pi_camera_yolo():
        return Response(_mjpeg(pi_source, yolo), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.route("/cam2")
    def cam2():
        return Response(_mjpeg(cam2_source), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.route("/cam2_yolo")
    def cam2_yolo():
        return Response(_mjpeg(cam2_source, yolo), mimetype="multipart/x-mixed-replace; boundary=frame")

    def snapshot_response(source: FrameSource, overlay: YoloOverlay | None = None):
        frame = source.get_frame()
        if frame is None:
            return "No frame available", 503
        if overlay is not None:
            frame = overlay.draw(frame)
        jpeg = _encode_jpeg(frame, quality=95)
        if jpeg is None:
            return "Could not encode frame", 500
        return Response(jpeg, mimetype="image/jpeg")

    @app.route("/snapshot/pi_camera")
    def snapshot_pi_camera():
        return snapshot_response(pi_source)

    @app.route("/snapshot/pi_camera_yolo")
    def snapshot_pi_camera_yolo():
        return snapshot_response(pi_source, yolo)

    @app.route("/snapshot/cam2")
    def snapshot_cam2():
        return snapshot_response(cam2_source)

    @app.route("/snapshot/cam2_yolo")
    def snapshot_cam2_yolo():
        return snapshot_response(cam2_source, yolo)

    return app


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the Elephant combined raw/YOLO camera viewer.")
    parser.add_argument("--pi-ip", required=True)
    parser.add_argument("--pi-username", default="pi")
    parser.add_argument("--pi-password", default="elephant")
    parser.add_argument("--workdir", default=".")
    parser.add_argument("--cam2-stream-url", default=DEFAULT_STREAM_URL)
    parser.add_argument("--yolo-model-path")
    parser.add_argument("--host", default=COMBINED_VIEWER_HOST)
    parser.add_argument("--port", type=int, default=COMBINED_VIEWER_PORT)
    args = parser.parse_args()

    config = ViewerConfig(
        pi_ip=args.pi_ip,
        pi_username=args.pi_username,
        pi_password=args.pi_password,
        pi_local_image_dir=args.workdir,
        cam2_stream_url=args.cam2_stream_url,
        yolo_model_path=args.yolo_model_path,
    )
    app = create_app(config)
    app.run(host=args.host, port=args.port, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

