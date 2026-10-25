"""Compile/run policy C tests on HOST only; never access Luckfox.
Explicit --zig supports a portable local compiler; no toolchain downloads here.
Host builds do not validate RV1103 ARM/uClibc ABI, camera, or NPU.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workshop', action='store_true', help='Also build/run generated Python-to-C workshop replay parity tests')
    parser.add_argument('--zig', type=Path, help='Explicit path to verified HOST zig.exe; use its cc frontend')
    args = parser.parse_args(argv)
    if args.zig:
        if not args.zig.is_file():
            parser.error('explicit zig compiler path does not exist')
        compiler = [str(args.zig.resolve()), 'cc']
    else:
        found = shutil.which('gcc') or shutil.which('clang')
        if not found:
            print('NOT TESTED: no host C compiler found. No board access attempted.')
            return 2
        compiler = [found]
    with tempfile.TemporaryDirectory(prefix='apd-native-') as directory:
        binary = Path(directory) / ('apd_test.exe' if sys.platform == 'win32' else 'apd_test')
        sources = ROOT / 'edge' / 'luckfox'
        command = compiler + ['-std=c99', '-Wall', '-Wextra', '-Werror', '-pedantic',
            str(sources / 'apd_core.c'), str(sources / 'session.c'),
            str(sources / 'test_core.c'), '-o', str(binary)]
        subprocess.run(command, check=True, timeout=600)
        subprocess.run([str(binary)], check=True, timeout=10)
        if args.workshop:
            from native_workshop_parity import generate_test
            receiver = ROOT / 'arduino' / 'legacy' / 'apd_receiver_v3'
            test = Path(directory) / 'test_workshop.c'
            count = generate_test(test)
            workshop = Path(directory) / ('workshop_test.exe' if sys.platform == 'win32' else 'workshop_test')
            subprocess.run(compiler + ['-std=c99', '-Wall', '-Wextra', '-Werror', '-pedantic',
                '-I', str(sources), '-I', str(receiver), str(sources / 'workshop_tracker.c'),
                str(sources / 'mcu_frame.c'), str(receiver / 'receiver_core.c'), str(test), '-o', str(workshop)], check=True, timeout=600)
            subprocess.run([str(workshop)], check=True, timeout=10)
            print(f'Workshop C/Python parity PASS: {count} synthetic frames; NOT detector accuracy.')
            from native_backend_vectors import generate_vectors
            vectors = Path(directory) / 'backend_vectors.c'
            vector_count = generate_vectors(vectors)
            backend = Path(directory) / ('backend_test.exe' if sys.platform == 'win32' else 'backend_test')
            subprocess.run(compiler + ['-std=c99', '-Wall', '-Wextra', '-Werror', '-pedantic',
                '-I', str(sources), str(sources / 'backend_frame.c'), str(sources / 'workshop_tracker.c'),
                str(sources / 'test_backend_frame.c'), str(vectors), '-lm', '-o', str(backend)], check=True, timeout=600)
            subprocess.run([str(backend)], check=True, timeout=10)
            print(f'HOST backend transform PASS: {vector_count} synthetic boxes; NOT live calibration.')
            boundary = Path(directory) / ('boundary_test.exe' if sys.platform == 'win32' else 'boundary_test')
            subprocess.run(compiler + ['-std=c99', '-Wall', '-Wextra', '-Werror', '-pedantic',
                '-I', str(sources), str(sources / 'workshop_tracker.c'),
                str(sources / 'test_workshop_boundaries.c'), '-o', str(boundary)], check=True, timeout=600)
            subprocess.run([str(boundary)], check=True, timeout=10)
            sys.path.insert(0, str(ROOT / 'python'))
            from native_mcu_vectors import generate_test as generate_mcu_test
            mcu_source = Path(directory) / 'test_mcu.c'
            stream_count = generate_mcu_test(mcu_source)
            mcu = Path(directory) / ('mcu_test.exe' if sys.platform == 'win32' else 'mcu_test')
            receiver = ROOT / 'arduino' / 'legacy' / 'apd_receiver_v3'
            subprocess.run(compiler + ['-std=c99', '-Wall', '-Wextra', '-Werror', '-pedantic',
                '-I', str(receiver), str(receiver / 'receiver_core.c'), str(mcu_source),
                '-o', str(mcu)], check=True, timeout=600)
            subprocess.run([str(mcu)], check=True, timeout=10)
            print(f'HOST MCU parser tests PASS: {stream_count} streams; NOT AVR/physical commissioning.')
            from native_grid_vectors import generate_test as generate_grid_test
            grid_vectors = Path(directory) / 'grid_vectors.c'
            grid_count = generate_grid_test(grid_vectors)
            grid = Path(directory) / ('grid_test.exe' if sys.platform == 'win32' else 'grid_test')
            subprocess.run(compiler + ['-std=c99', '-Wall', '-Wextra', '-Werror', '-pedantic',
                '-I', str(sources), str(sources / 'grid_decoder.c'),
                str(sources / 'backend_frame.c'), str(sources / 'workshop_tracker.c'),
                str(sources / 'test_grid_decoder.c'), str(grid_vectors), '-lm',
                '-o', str(grid)], check=True, timeout=600)
            subprocess.run([str(grid)], check=True, timeout=30)
            print(f'HOST grid decoder PASS: {grid_count} synthetic tensors; NOT real-model INT8 parity.')



            # Candidate engine links HOST mocks, never board .so/.reference.
            import hashlib
            reference = ROOT / 'docs/luckfox/debug/build-preflight/sdk-native/rknn_api-1.4.0.h.txt'
            header = reference.read_bytes()
            if hashlib.sha256(header).hexdigest() != '2bb8008935f6ea3df421fcc3d294887c804fff5c08e7f29c330b557bd31d65c2':
                raise RuntimeError('Pinned RKNN reference header hash mismatch; refusing build')
            include = Path(directory) / 'reference-sdk'
            include.mkdir()
            (include / 'rknn_api.h').write_bytes(header)
            engine = Path(directory) / ('rknn_engine_test.exe' if sys.platform == 'win32' else 'rknn_engine_test')
            subprocess.run(compiler + ['-std=c99', '-Wall', '-Wextra', '-Werror', '-pedantic',
                '-I', str(include), '-I', str(sources), str(sources / 'rknn_engine.c'),
                str(sources / 'grid_decoder.c'), str(sources / 'test_rknn_engine.c'),
                '-lm', '-o', str(engine)], check=True, timeout=600)
            subprocess.run([str(engine)], check=True, timeout=30)

        print('HOST native policy tests PASS; NOT an ARM/NPU/camera deployment.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
