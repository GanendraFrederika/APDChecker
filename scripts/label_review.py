r"""Local label checker for the workshop photos (no upload, no extra install).

Opens datasets/workshop (from scripts/collect_workshop.py): every photo with the
boxes the AI suggested. You only fix mistakes, then mark the photo as checked.
Labels are YOLO .txt files (class cx cy w h, 0..1), saved on every change.
Classes: 0 helmet, 1 vest, 2 shoes, 3 person.

  label-review.bat
  .venv\Scripts\python.exe scripts\label_review.py [--data datasets\workshop] [--no-window]
"""
import argparse
import json
from pathlib import Path
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
CLASSES = ("helmet", "vest", "shoes", "person")
PAGE = Path(__file__).with_name("label_review.html")


class Store:
    def __init__(self, data):
        self.images = Path(data) / "images"
        self.labels = Path(data) / "labels"
        self.labels.mkdir(parents=True, exist_ok=True)
        self.state_path = Path(data) / "review.json"
        self.lock = threading.Lock()
        try:
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.state = {}
        self.state.setdefault("checked", [])

    def names(self):
        return sorted(p.name for p in self.images.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))

    def _image(self, name):
        p = (self.images / Path(name).name)
        if p.parent != self.images or not p.exists():
            raise FileNotFoundError(name)
        return p

    def read(self, name):
        self._image(name)
        lab = self.labels / (Path(name).stem + ".txt")
        boxes = []
        if lab.exists():
            for line in lab.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[0].isdigit() and int(parts[0]) < len(CLASSES):
                    boxes.append([int(parts[0])] + [float(v) for v in parts[1:5]])
        return boxes

    def write(self, name, boxes, checked):
        self._image(name)
        rows = []
        for b in boxes:
            c = int(b[0])
            cx, cy, w, h = (min(1.0, max(0.0, float(v))) for v in b[1:5])
            if 0 <= c < len(CLASSES) and w > 0.002 and h > 0.002:
                rows.append(f"{c} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
        lab = self.labels / (Path(name).stem + ".txt")
        tmp = lab.with_suffix(".tmp")
        tmp.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
        tmp.replace(lab)                          # atomic: never a half-written label file
        with self.lock:
            done = set(self.state["checked"])
            (done.add if checked else done.discard)(Path(name).name)
            self.state["checked"] = sorted(done)
            self.state["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.state_path.write_text(json.dumps(self.state, indent=1), encoding="utf-8")
        return len(rows)

    def summary(self):
        names = self.names()
        done = set(self.state["checked"])
        counts = [0] * len(CLASSES)
        for n in names:
            for b in self.read(n):
                counts[b[0]] += 1
        return dict(total=len(names), checked=sum(1 for n in names if n in done),
                    counts=dict(zip(CLASSES, counts)))


def make_handler(store):
    page = PAGE.read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, kind, data):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj):
            return self._send(200, "application/json", json.dumps(obj).encode())

        def do_GET(self):
            try:
                if self.path == "/":
                    return self._send(200, "text/html; charset=utf-8", page)
                if self.path == "/api/list":
                    done = set(store.state["checked"])
                    return self._json(dict(classes=CLASSES, items=[dict(name=n, checked=n in done) for n in store.names()]))
                if self.path == "/api/summary":
                    return self._json(store.summary())
                if self.path.startswith("/api/labels/"):
                    name = unquote(self.path[len("/api/labels/"):])
                    return self._json(dict(name=name, boxes=store.read(name),
                                           checked=Path(name).name in set(store.state["checked"])))
                if self.path.startswith("/img/"):
                    p = store._image(unquote(self.path[len("/img/"):]))
                    kind = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
                    return self._send(200, kind, p.read_bytes())
            except FileNotFoundError:
                return self._send(404, "text/plain", b"not found")
            return self._send(404, "text/plain", b"not found")

        def do_POST(self):
            length = min(int(self.headers.get("Content-Length") or 0), 1 << 20)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._send(400, "text/plain", b"bad json")
            if self.path == "/api/save":
                try:
                    n = store.write(body["name"], body.get("boxes", []), bool(body.get("checked")))
                except (KeyError, FileNotFoundError, TypeError, ValueError):
                    return self._send(400, "text/plain", b"bad request")
                return self._json(dict(ok=True, boxes=n))
            return self._send(404, "text/plain", b"not found")

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(ROOT / "datasets/workshop"))
    ap.add_argument("--port", type=int, default=8095)
    ap.add_argument("--no-window", action="store_true")
    args = ap.parse_args()
    store = Store(args.data)
    if not store.names():
        print(f"Belum ada foto di {store.images}.")
        print("Rekam dulu: .venv\\Scripts\\python.exe scripts\\collect_workshop.py --minutes 20")
        return 1
    url = f"http://127.0.0.1:{args.port}/"
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(store))
    except OSError:
        print(f"Pemeriksa label sudah berjalan: {url}")
        if not args.no_window:
            from preview_camera import open_window
            open_window(url, 16 / 9)
        return 0
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    s = store.summary()
    print(f"Pemeriksa label: {url}  ({s['checked']}/{s['total']} foto sudah diperiksa)")
    print("Tutup jendela (atau Ctrl+C di sini) untuk berhenti. Semua perubahan langsung tersimpan.")
    proc = None
    if not args.no_window:
        from preview_camera import open_window
        proc = open_window(url, 16 / 9)
    started = time.monotonic()
    try:
        while True:
            if proc is not None and proc.poll() is not None:
                if time.monotonic() - started > 4:
                    break
                proc = None
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    s = store.summary()
    print(f"Selesai: {s['checked']}/{s['total']} foto diperiksa. Kotak: {s['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
