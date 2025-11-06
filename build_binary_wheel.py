#!/usr/bin/env python3
"""
Utility script to convert a pure-Python package into a binary-only wheel that can
be installed via pip. The workflow mirrors the manual steps used to build the
`txs_mf_stat_binary` artefacts:

1. Copy the target package(s) into an isolated working directory (inside `dist`).
2. Use Cython (via the requested Python interpreter) to translate all `.py` files
   into C source files.
3. Compile the generated C sources into `.so` extension modules with
   `build_ext --inplace`.
4. Remove the original `.py` sources and recreate lightweight loader stubs only
   for `__init__.py` files so packages remain discoverable while their logic
   stays in the compiled extensions.
5. Produce a platform-specific wheel (`cp312-manylinux2014_x86_64` by default)
   and an optional tarball copy of the binary package directory.

This script expects:
  * Python 3.12 toolchain (interpreter path passed via `--python-bin`)
  * The target packages to live under a common project root.
  * Cython and setuptools to be installed in that interpreter environment.

Typical usage (run from the project root):

    python dist/build_binary_wheel.py \\
        --project-root . \\
        --packages txs_mf_stat \\
        --python-bin /home/ansonxiang/miniconda3/envs/py312/bin/python \\
        --wheel-name txs_mf_stat_binary \\
        --version 0.1.0 \\
        --output-dir dist

The resulting files will be placed alongside the script by default.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple


def run(cmd: Sequence[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    """Invoke a subprocess, raising on non-zero exit."""
    print(f"[build_binary_wheel] $ {' '.join(cmd)} (cwd={cwd})")
    completed = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        stdout=sys.stdout,
        stderr=sys.stderr,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {completed.returncode}: {' '.join(cmd)}")


def clean_directory(path: Path) -> None:
    """Remove a directory if it exists, then recreate it empty."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_packages(project_root: Path, package_names: Sequence[str], destination: Path) -> List[Tuple[str, Path]]:
    """Copy each requested package into the working directory."""
    copied = []
    for pkg in package_names:
        src = project_root / pkg.replace(".", os.sep)
        if not src.exists():
            raise FileNotFoundError(f"Package path not found: {src}")
        dst = destination / pkg.replace(".", os.sep)
        if dst.exists():
            shutil.rmtree(dst)
        print(f"[build_binary_wheel] Copying {src} -> {dst}")
        shutil.copytree(src, dst)
        copied.append((pkg, dst))
    return copied


def discover_packages(root: Path, package_dirs: Sequence[Path] | None = None) -> List[str]:
    """
    Return dotted package names for every directory under root containing __init__.py.
    When package_dirs is provided, only packages inside those directories are included.
    """
    limited_to: set[Path] = set()
    if package_dirs:
        for pkg_dir in package_dirs:
            if pkg_dir.is_dir():
                limited_to.add(pkg_dir.resolve().relative_to(root))

    packages: List[str] = []
    for init_path in root.rglob("__init__.py"):
        rel = init_path.relative_to(root)
        package_name = ".".join(rel.parent.parts)
        if not package_name:
            continue

        if limited_to:
            package_rel_dir = rel.parent
            if not any(package_rel_dir.is_relative_to(target) for target in limited_to):
                continue

        packages.append(package_name)
    seen: set[str] = set()
    ordered: List[str] = []
    for name in packages:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def write_prepare_script(work_dir: Path, package_dirs: Sequence[Path]) -> Path:
    script_path = work_dir / "prepare_c.py"
    patterns = [f"{pkg.relative_to(work_dir)}/**/*.py" for pkg in package_dirs]
    script_content = textwrap.dedent(
        f"""
        from pathlib import Path
        from Cython.Build import cythonize

        PATTERNS = {patterns!r}

        if not PATTERNS:
            raise SystemExit("No Python files found to cythonize.")

        cythonize(
            PATTERNS,
            build_dir="build",
            compiler_directives={{"language_level": "3"}},
        )
        """
    ).lstrip()
    script_path.write_text(script_content, encoding="utf-8")
    return script_path


def write_setup_build_script(work_dir: Path) -> Path:
    script_path = work_dir / "setup_build.py"
    script_content = textwrap.dedent(
        """
        from pathlib import Path
        from setuptools import Extension, setup


        BASE_DIR = Path(__file__).parent.resolve()
        BUILD_DIR = BASE_DIR / "build"


        def iter_extensions():
            for c_path in BUILD_DIR.rglob("*.c"):
                rel = c_path.relative_to(BUILD_DIR).with_suffix("")
                module_name = ".".join(rel.parts)
                yield Extension(module_name, [str(c_path)])


        extensions = list(iter_extensions())
        if not extensions:
            raise SystemExit("No generated C sources found in build/; run prepare_c.py first.")

        setup(
            name="binary_build_extensions",
            ext_modules=extensions,
        )
        """
    ).lstrip()
    script_path.write_text(script_content, encoding="utf-8")
    return script_path


def remove_python_sources(package_dirs: Sequence[Path]) -> None:
    for package_dir in package_dirs:
        for py_file in package_dir.rglob("*.py"):
            py_file.unlink()
        for cache_dir in package_dir.rglob("__pycache__"):
            shutil.rmtree(cache_dir)


def create_loader_stub(init_file: Path) -> None:
    """Write a generic loader stub that proxies to the compiled __init__ extension."""
    stub = textwrap.dedent(
        """
        \"\"\"Binary loader stub generated by build_binary_wheel.py.\"\"\"
        from __future__ import annotations

        import importlib.machinery as _machinery
        import importlib.util as _util
        import pathlib as _pathlib
        import sys as _sys


        _pkg_dir = _pathlib.Path(__file__).resolve().parent
        _candidates = sorted(_pkg_dir.glob("__init__*.so"))
        if not _candidates:
            raise ImportError(f"Binary module for {_pkg_dir} not found.")

        _loader = _machinery.ExtensionFileLoader(__name__, str(_candidates[0]))
        _spec = _util.spec_from_loader(__name__, _loader)
        _module = _util.module_from_spec(_spec)
        _loader.exec_module(_module)
        _sys.modules[__name__] = _module
        globals().update({k: v for k, v in vars(_module).items() if k not in globals()})
        """
    ).lstrip()
    init_file.write_text(stub, encoding="utf-8")


def ensure_namespace_inits(package_dirs: Sequence[Path]) -> None:
    """Ensure every package directory has an __init__.py placeholder for discovery."""
    placeholder = textwrap.dedent(
        """
        \"\"\"Namespace placeholder generated by build_binary_wheel.py.\"\"\"
        """
    ).lstrip()

    for package_dir in package_dirs:
        # Always consider the root package directory itself.
        targets: set[Path] = {package_dir}

        for so_path in package_dir.rglob("*.so"):
            current = so_path.parent
            while True:
                targets.add(current)
                if current == package_dir:
                    break
                current = current.parent

        for target in targets:
            if not target.exists():
                continue
            init_py = target / "__init__.py"
            if init_py.exists():
                continue
            init_py.write_text(placeholder, encoding="utf-8")


def recreate_init_stubs(package_dirs: Sequence[Path]) -> None:
    """Ensure each package directory hosting a compiled __init__ has a loader stub."""
    for package_dir in package_dirs:
        for so_path in package_dir.rglob("__init__*.so"):
            init_py = so_path.with_name("__init__.py")
            create_loader_stub(init_py)


def write_pyproject(work_dir: Path) -> None:
    content = textwrap.dedent(
        """
        [build-system]
        requires = ["setuptools>=61"]
        build-backend = "setuptools.build_meta"
        """
    ).lstrip()
    (work_dir / "pyproject.toml").write_text(content, encoding="utf-8")


def write_setup_files(
    work_dir: Path,
    wheel_name: str,
    version: str,
    packages: Sequence[str],
    python_tag: str,
    platform_tag: str,
) -> None:
    include_targets = sorted({pkg for pkg in packages})
    config_lines: list[str] = [
        "[metadata]",
        f"name = {wheel_name}",
        f"version = {version}",
        "description = Binary distribution generated by build_binary_wheel.py",
        "license = MIT",
        "",
        "[options]",
        "packages = find:",
        "package_dir =",
        "    =.",
        "include_package_data = True",
        "python_requires = >=3.12,<3.13",
        "zip_safe = False",
        "has_ext_modules = True",
        "",
        "[options.package_data]",
        "* = *.so",
        "",
        "[options.packages.find]",
        "where = .",
        "include =",
    ]

    for pkg in include_targets:
        config_lines.append(f"    {pkg}")
    for pkg in include_targets:
        config_lines.append(f"    {pkg}.*")

    config_lines.extend(
        [
            "",
            "[bdist_wheel]",
            "universal = 0",
            f"python_tag = {python_tag}",
            f"plat_name = {platform_tag}",
            "",
        ]
    )

    setup_cfg = "\n".join(config_lines)
    (work_dir / "setup.cfg").write_text(setup_cfg, encoding="utf-8")
    (work_dir / "setup.py").write_text("from setuptools import setup\n\nsetup()\n", encoding="utf-8")


def build_wheel(work_dir: Path, python_bin: Path) -> Path:
    run([str(python_bin), "setup.py", "bdist_wheel"], cwd=work_dir)
    dist_dir = work_dir / "dist"
    wheels = sorted(dist_dir.glob("*.whl"))
    if not wheels:
        raise RuntimeError("Wheel build succeeded but no wheel file was produced.")
    return wheels[0]


def create_tarball(work_dir: Path, package_dirs: Sequence[Path], output_dir: Path, wheel_name: str, version: str) -> Path:
    root_name = f"{wheel_name}_package"
    temp_root = work_dir / root_name
    clean_directory(temp_root)
    for package_dir in package_dirs:
        rel = package_dir.relative_to(work_dir)
        dest = temp_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(package_dir, dest)
    archive_path = output_dir / f"{wheel_name}-{version}-binary.tar.gz"
    base_name = archive_path.parent / archive_path.name.replace(".tar.gz", "")
    shutil.make_archive(str(base_name), "gztar", root_dir=temp_root)
    shutil.rmtree(temp_root)
    return archive_path


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build binary-only wheel via Cython.")
    parser.add_argument("--project-root", type=Path, required=True, help="Root directory of the source project.")
    parser.add_argument(
        "--packages",
        nargs="+",
        required=True,
        help="One or more package import paths (e.g. txs_mf_stat).",
    )
    parser.add_argument("--python-bin", type=Path, required=True, help="Python 3.12 interpreter to run build steps.")
    parser.add_argument("--wheel-name", type=str, required=True, help="Distribution name for the generated wheel.")
    parser.add_argument("--version", type=str, required=True, help="Version string for the binary distribution.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dist"),
        help="Directory to store the final artefacts (wheel, tarball). Default: ./dist",
    )
    parser.add_argument(
        "--python-tag",
        type=str,
        default="cp312",
        help="PEP 425 python tag for wheel metadata (default: cp312).",
    )
    parser.add_argument(
        "--platform-tag",
        type=str,
        default="manylinux2014_x86_64",
        help="PEP 425 platform tag for wheel metadata (default: manylinux2014_x86_64).",
    )
    parser.add_argument(
        "--keep-work-dir",
        action="store_true",
        help="Keep the intermediate working directory for inspection.",
    )
    parser.add_argument(
        "--skip-tarball",
        action="store_true",
        help="Skip creation of the auxiliary tar.gz copy of the binary package.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> None:
    args = parse_args(argv)

    project_root = args.project_root.resolve()
    output_dir = args.output_dir.resolve()
    python_bin = args.python_bin.resolve()

    if not python_bin.exists():
        raise FileNotFoundError(f"Python interpreter not found: {python_bin}")

    output_dir.mkdir(parents=True, exist_ok=True)

    work_dir = output_dir / f"{args.wheel_name}_build"
    clean_directory(work_dir)

    copied_packages = copy_packages(project_root, args.packages, work_dir)
    package_dirs = [path for _, path in copied_packages]

    prepare_script = write_prepare_script(work_dir, package_dirs)
    run([str(python_bin), str(prepare_script)], cwd=work_dir)

    setup_build_script = write_setup_build_script(work_dir)
    run([str(python_bin), str(setup_build_script), "build_ext", "--inplace"], cwd=work_dir)

    remove_python_sources(package_dirs)
    ensure_namespace_inits(package_dirs)
    recreate_init_stubs(package_dirs)

    # Collect package names after stubs are recreated (ensures __init__.py present for discovery).
    packages = discover_packages(work_dir, package_dirs)
    if not packages:
        raise RuntimeError("No packages discovered after compilation; check package layout.")

    write_pyproject(work_dir)
    write_setup_files(
        work_dir=work_dir,
        wheel_name=args.wheel_name,
        version=args.version,
        packages=packages,
        python_tag=args.python_tag,
        platform_tag=args.platform_tag,
    )

    wheel_path = build_wheel(work_dir, python_bin)
    final_wheel = output_dir / wheel_path.name
    shutil.copy2(wheel_path, final_wheel)
    print(f"[build_binary_wheel] Wheel written to {final_wheel}")

    if not args.skip_tarball:
        tarball = create_tarball(work_dir, package_dirs, output_dir, args.wheel_name, args.version)
        print(f"[build_binary_wheel] Tarball written to {tarball}")

    if not args.keep_work_dir:
        shutil.rmtree(work_dir)


if __name__ == "__main__":
    main(sys.argv[1:])
