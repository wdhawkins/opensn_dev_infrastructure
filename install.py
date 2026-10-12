#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The OpenSn Authors <https://open-sn.github.io/opensn/>
# SPDX-License-Identifier: MIT
"""Generate the private-Spack OpenSn development-stack installer."""

import argparse
import copy
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
DEFAULT_PACKAGES_REF = "19c15b598f462517e2d091baa65a86a53c7d36a9"
DEPENDENCIES = {
    "cmake": "4.4.4",
    "gmake": "4.4.1",
    "doxygen": "1.17.0",
    "pandoc": "3.7.0.2",
    "googletest": "1.18.0",
    "mpicpp-lite": "2.7.1",
    "boost": "1.90.0",
    "hdf5": "1.14.6",
    "vtk": "9.5.1",
    "caliper": "2.15.0",
    "petsc": "3.26.0",
    "hypre": "3.0.0",
    "superlu-dist": "9.2.1",
    "metis": "5.1.0",
    "parmetis": "4.0.3",
    "scotch": "7.0.16",
    "openblas": "0.3.34",
    "intel-oneapi-mkl": "2026.1.0",
}


def quote(value):
    return shlex.quote(str(value))


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", value):
        raise ValueError(f"Expected a release version, got {value!r}")
    return value


def package_version(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d[A-Za-z0-9._-]*", value):
        raise ValueError(f"Expected an exact package version, got {value!r}")
    return value


def read_url(url):
    result = subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location", url],
                            capture_output=True, text=True)
    if result.returncode:
        raise ValueError(f"Cannot fetch {url}: {result.stderr.strip()}")
    return result.stdout


def newest_majors(versions, count=3):
    selected = {}
    for item in sorted(set(versions), key=lambda x: tuple(map(int, x.split("."))), reverse=True):
        selected.setdefault(item.split(".")[0], item)
    if len(selected) < count:
        raise ValueError(f"Found fewer than {count} stable major releases")
    return list(selected.values())[:count]


def compiler_releases(family, packages_ref=DEFAULT_PACKAGES_REF):
    package = {"gcc": "gcc", "clang": "llvm"}[family]
    url = ("https://raw.githubusercontent.com/spack/spack-packages/"
           f"{packages_ref}/repos/spack_repo/builtin/packages/{package}/package.py")
    found = re.findall(r'^\s*version\("(\d+\.\d+\.\d+)"', read_url(url), re.MULTILINE)
    return newest_majors(found)


def recipe_url(package, packages_ref):
    return ("https://raw.githubusercontent.com/spack/spack-packages/"
            f"{packages_ref}/repos/spack_repo/builtin/packages/{package}/package.py")


def newest_release(found, name):
    releases = sorted(set(found), key=lambda x: tuple(map(int, x.split("."))), reverse=True)
    if not releases:
        raise ValueError(f"Found no {name} releases in the pinned recipe")
    return releases[0]


def gpu_release(kind, packages_ref=DEFAULT_PACKAGES_REF):
    """Return the newest CUDA or ROCm release in the pinned recipes."""
    if kind == "cuda":
        # CUDA releases are keys of the recipe's table of per-platform installers.
        recipe = read_url(recipe_url("cuda", packages_ref))
        found = re.findall(r'^\s*"(\d+\.\d+\.\d+)":\s*\{', recipe, re.MULTILINE)
    else:
        recipe = read_url(recipe_url("hip", packages_ref))
        found = re.findall(r'^\s*version\("(\d+\.\d+\.\d+)"', recipe, re.MULTILINE)
    return newest_release(found, kind)


def resolve_compilers(entries, packages_ref=DEFAULT_PACKAGES_REF):
    result = []
    for original in entries:
        item = copy.deepcopy(original)
        if item.get("family") in ("gcc", "clang") and item.get("version") == "latest-3":
            releases = compiler_releases(item["family"], packages_ref)
            result += [dict(item, version=x) for x in releases]
        else:
            result.append(item)
    gccs = [x["version"] for x in result if x.get("family") == "gcc"]
    for item in result:
        if item.get("gcc_toolchain") == "latest":
            if not gccs:
                raise ValueError("gcc_toolchain: latest requires a GCC stack")
            item["gcc_toolchain"] = max(gccs, key=lambda x: tuple(map(int, x.split("."))))
    return result


def validate(config):
    allowed = {"root", "work", "jobs", "python", "mpich", "spack", "clang_ptx", "docs",
               "prune", "gpu", "compilers", "dependencies"}
    if set(config) - allowed:
        raise ValueError(f"Unknown configuration keys: {set(config) - allowed}")
    result = copy.deepcopy(config)
    for key, default in (("root", "/opt/local"), ("work", "/tmp/opensn-toolchains")):
        value = result.setdefault(key, default)
        if not isinstance(value, str) or not re.fullmatch(r"/[A-Za-z0-9_./-]+", value):
            raise ValueError(f"{key} must be an absolute path without spaces")
        result[key] = os.path.normpath(value)
        if result[key] == "/":
            raise ValueError(f"{key} must not be /")
    if type(result.setdefault("jobs", 4)) is not int or result["jobs"] < 1:
        raise ValueError("jobs must be a positive integer")
    result["python"] = version(result.setdefault("python", "3.13.13"))
    result["mpich"] = version(result.setdefault("mpich", "5.0.2"))
    dependencies = result.get("dependencies")
    if not isinstance(dependencies, dict) or set(dependencies) != set(DEPENDENCIES):
        raise ValueError("dependencies must contain exactly: " + ", ".join(DEPENDENCIES))
    result["dependencies"] = {
        name: package_version(value) for name, value in dependencies.items()
    }
    if type(result.setdefault("clang_ptx", True)) is not bool:
        raise ValueError("clang_ptx must be a JSON boolean")
    if type(result.setdefault("docs", True)) is not bool:
        raise ValueError("docs must be a JSON boolean")
    if type(result.setdefault("prune", False)) is not bool:
        raise ValueError("prune must be a JSON boolean")
    spack = result.setdefault("spack", {})
    if set(spack) - {"url", "ref", "packages_ref"}:
        raise ValueError("spack accepts only url, ref, and packages_ref")
    spack.setdefault("url", "https://github.com/spack/spack.git")
    spack.setdefault("ref", "v1.2.2")
    spack.setdefault("packages_ref", DEFAULT_PACKAGES_REF)
    if (not spack["url"].startswith("https://")
            or not re.fullmatch(r"[\w./-]+", spack["ref"])
            or not re.fullmatch(r"[\w./-]+", spack["packages_ref"])):
        raise ValueError("spack requires an HTTPS URL and safe refs")
    gpu = result.setdefault("gpu", {})
    if not isinstance(gpu, dict) or set(gpu) - {"cuda", "rocm"}:
        raise ValueError("gpu accepts only cuda and rocm")
    for kind, value in gpu.items():
        gpu[kind] = (gpu_release(kind, spack["packages_ref"]) if value == "latest"
                     else version(value))
    compilers = resolve_compilers(result.get("compilers", []), spack["packages_ref"])
    if not compilers:
        raise ValueError("At least one compiler is required")
    known_gcc = {x.get("version") for x in compilers if x.get("family") == "gcc"}
    seen = set()
    for item in compilers:
        if set(item) - {"family", "version", "mpich", "gcc_toolchain"}:
            raise ValueError("Unknown compiler configuration key")
        family, release = item.get("family"), version(item.get("version"))
        if family not in ("gcc", "clang", "oneapi") or (family, release) in seen:
            raise ValueError(f"Invalid or duplicate compiler: {family}/{release}")
        seen.add((family, release))
        item["mpich"] = version(item.get("mpich", result["mpich"]))
        if family != "gcc" and item.get("gcc_toolchain") not in known_gcc:
            raise ValueError(f"{family}/{release} requires a listed gcc_toolchain")
    result["compilers"] = ([item for item in compilers if item["family"] == "gcc"]
                           + [item for item in compilers if item["family"] != "gcc"])
    return result


def manifest(specs, view, store, compiler_mixing=None, packages=None):
    lines = ["spack:", "  specs:"] + [f"  - {x}" for x in specs]
    lines += [f"  view: {view}", "  concretizer:", "    unify: true", "    reuse: false"]
    if compiler_mixing is not None:
        if isinstance(compiler_mixing, list):
            value = "[" + ", ".join(compiler_mixing) + "]"
        else:
            value = str(compiler_mixing).lower()
        lines.append(f"    compiler_mixing: {value}")
    if packages:
        lines += ["  packages:"] + packages
    lines += ["  config:", "    install_tree:", f"      root: {store}"]
    return "\n".join(lines)


def stack_manifest(compiler, specs, compiler_view, stack_view, store, compiler_mixing,
                   reuse_specs, externals, blas, bootstrap=None):
    lines = ["spack:", "  specs:"]
    if bootstrap:
        lines += [
            "  - group: bootstrap",
            "    specs:",
            f"    - {bootstrap}",
        ]
    lines += [
        "  - group: compiler",
    ]
    if bootstrap:
        lines.append("    needs: [bootstrap]")
    lines += [
        "    specs:",
        f"    - {compiler}",
        "  - group: stack",
        "    needs: [compiler]",
        "    specs:",
    ]
    lines += [f"    - {spec}" for spec in specs]
    lines += [
        "  view:",
        "    compiler:",
        f"      root: {compiler_view}",
        "      group: compiler",
        "    stack:",
        f"      root: {stack_view}",
        "      group: stack",
        "  concretizer:",
        "    unify: true",
        "    reuse:",
        "      roots: true",
        "      from:",
        "      - type: local",
        "        include:",
    ]
    lines += [f'        - "{spec}"' for spec in reuse_specs]
    lines += [
        "      - type: external",
        f"    compiler_mixing: {str(compiler_mixing).lower()}",
    ]
    lines += [
        "  packages:",
        "    mesa:",
        '      require: "~llvm"',
    ]
    lines += blas
    if bootstrap is None:
        lines += [
            "    gcc:",
            "      buildable: true",
            "      externals:: []",
        ]
    for name, spec, prefix, compilers in externals:
        lines += [
            f"    {name}:",
            "      buildable: false",
            "      externals:",
            f'      - spec: "{spec}"',
            f"        prefix: {prefix}",
        ]
        if compilers:
            lines += ["        extra_attributes:", "          compilers:"]
            lines += [f"            {language}: {path}"
                      for language, path in compilers.items()]
    lines += [
        "  config:",
        "    install_tree:",
        f"      root: {store}",
    ]
    return "\n".join(lines)


def dependency_specs(dependencies, mpi, compiler):
    compiled_with = f"%{compiler}"
    mpi_dep = f"^mpich@{mpi}"
    specs = [
        f"googletest@{dependencies['googletest']} {compiled_with}",
        f"mpich@{mpi}~fortran {compiled_with}",
        f"mpicpp-lite@{dependencies['mpicpp-lite']} {compiled_with} {mpi_dep}",
        f"boost@{dependencies['boost']} {compiled_with}",
        f"hdf5@{dependencies['hdf5']}+hl+mpi {compiled_with} {mpi_dep}",
        (f"vtk@{dependencies['vtk']}+mpi io=exodusii {compiled_with} {mpi_dep} "
         f"^hdf5@{dependencies['hdf5']}"),
        (f"caliper@{dependencies['caliper']}+mpi~gotcha~kokkos {compiled_with} "
         f"{mpi_dep}"),
    ]
    petsc = (
        f"petsc@{dependencies['petsc']}+mpi+double~complex+int64+hdf5+metis+ptscotch"
        f"+hypre+superlu-dist~fortran {compiled_with} {mpi_dep} "
        f"^hdf5@{dependencies['hdf5']} ^hypre@{dependencies['hypre']} "
        f"^superlu-dist@{dependencies['superlu-dist']}~fortran "
        f"^metis@{dependencies['metis']} ^parmetis@{dependencies['parmetis']} "
        f"^scotch@{dependencies['scotch']}~fortran"
    )
    return specs + [petsc]


def blas_packages(dependencies):
    """Require oneMKL on x86_64, where it exists, and OpenBLAS on other targets."""
    mkl = "^[virtuals=blas,lapack] intel-oneapi-mkl"
    openblas = "^[virtuals=blas,lapack] openblas"
    lines = [
        "    intel-oneapi-mkl:",
        f'      require: "@{dependencies["intel-oneapi-mkl"]}"',
        "    openblas:",
        f'      require: "@{dependencies["openblas"]}~fortran"',
    ]
    for name in ("petsc", "hypre", "superlu-dist"):
        lines += [
            f"    {name}:",
            "      require:",
            f'      - one_of: ["{mkl}", "{openblas}"]',
            f'      - spec: "{mkl}"',
            '        when: "target=x86_64:"',
        ]
    return lines


def modulefile(family, release, mpi, compiler_view, gcc_runtime_view, view, common_view,
               common_venv, stack_venv, python):
    cc, cxx = {"gcc": ("gcc", "g++"), "clang": ("clang", "clang++"),
               "oneapi": ("icx", "icpx")}[family]
    compiler_bin = (compiler_view / "compiler" / "latest" / "bin"
                    if family == "oneapi" else compiler_view / "bin")
    py = ".".join(python.split(".")[:2])
    py_site = f"lib/python{py}/site-packages"
    return "\n".join([
        "#%Module1.0",
        f'module-whatis "OpenSn {family} {release} / MPICH {mpi}"',
        "conflict opensn-stack",
        f"setenv OPENSN_STACK {view}",
        f"setenv CC {compiler_bin}/{cc}",
        f"setenv CXX {compiler_bin}/{cxx}",
        f"setenv MPI_HOME {view}",
        f"setenv MPICC {view}/bin/mpicc",
        f"setenv MPICXX {view}/bin/mpicxx",
        f"setenv PETSC_DIR {view}",
        # AMD's clang++ compiles HIP code; use the stack's GCC C++ headers and libstdc++.
        f"setenv HIPFLAGS --gcc-toolchain={gcc_runtime_view}",
        # OpenSn's style requires clang-format 19; Clang compiler views shadow it on PATH.
        f"setenv CLANG_FORMAT {common_venv}/bin/clang-format",
        f"setenv VIRTUAL_ENV {stack_venv}",
        f"setenv Python3_EXECUTABLE {stack_venv}/bin/python",
        f"setenv pybind11_DIR {common_venv}/{py_site}/pybind11/share/cmake/pybind11",
        f"prepend-path PATH {common_venv}/bin",
        f"prepend-path PATH {common_view}/bin",
        f"prepend-path PATH {compiler_bin}",
        f"prepend-path PATH {view}/bin",
        f"prepend-path PATH {stack_venv}/bin",
        f"prepend-path CMAKE_PREFIX_PATH {compiler_view}",
        f"prepend-path CMAKE_PREFIX_PATH {view}",
        f"prepend-path CMAKE_PREFIX_PATH {common_venv}",
        f"prepend-path CMAKE_PREFIX_PATH {common_view}",
        f"prepend-path LD_LIBRARY_PATH {view}/lib",
        f"prepend-path LD_LIBRARY_PATH {view}/lib64",
        f"prepend-path LD_LIBRARY_PATH {compiler_view}/lib",
        f"prepend-path LD_LIBRARY_PATH {compiler_view}/lib64",
        f"prepend-path LD_PRELOAD {gcc_runtime_view}/lib64/libstdc++.so.6",
    ])


def tool_modulefile(name, release, view):
    return "\n".join([
        "#%Module1.0",
        f'module-whatis "OpenSn documentation tool {name} {release}"',
        f"conflict {name}",
        f"setenv {name.upper()}_ROOT {view}",
        f"prepend-path PATH {view}/bin",
        f"prepend-path CMAKE_PREFIX_PATH {view}",
    ])


def gpu_modulefile(kind, release, view):
    if kind == "cuda":
        return "\n".join([
            "#%Module1.0",
            f'module-whatis "CUDA toolkit {release}"',
            "conflict cuda",
            f"setenv CUDA_HOME {view}",
            f"setenv CUDA_PATH {view}",
            f"setenv CUDAToolkit_ROOT {view}",
            f"prepend-path PATH {view}/bin",
            f"prepend-path CMAKE_PREFIX_PATH {view}",
            f"prepend-path LD_LIBRARY_PATH {view}/lib64",
        ])
    return "\n".join([
        "#%Module1.0",
        f'module-whatis "ROCm HIP toolkit {release}"',
        "conflict rocm",
        f"setenv ROCM_PATH {view}",
        f"setenv HIP_PATH {view}",
        "setenv HIP_PLATFORM amd",
        f"setenv HIPCXX {view}/bin/clang++",
        f"prepend-path PATH {view}/bin",
        f"prepend-path CMAKE_PREFIX_PATH {view}",
        f"prepend-path LD_LIBRARY_PATH {view}/lib",
    ])


def gpu_lines(kind, release, root, envs, store, jobs):
    """Install CUDA or ROCm in its own environment, independent of every compiler stack."""
    env = envs / f"{kind}-{release}"
    view = root / "gpu" / kind / release / "view"
    if kind == "cuda":
        # NVIDIA publishes CUDA installers for x86_64 and aarch64 Linux.
        arches, specs, packages, check = ("x86_64|aarch64", [f"cuda@{release}"], None,
                                          view / "bin/nvcc")
    else:
        # Mesa is only an OpenGL provider for HIP; do not build its LLVM rasterizer.
        arches, specs, packages, check = ("x86_64", [f"hip@{release}"],
                                          ["    mesa:", '      require: "~llvm"'],
                                          view / "bin/hipcc")
    lines = [f'case "$(uname -m)" in {arches})']
    add_file(lines, env / "spack.yaml", manifest(specs, view, store, packages=packages))
    lines += [f"echo '==> Concretizing {kind} {release}'",
              f'"$spack" -e {quote(env)} concretize -f',
              f"echo '==> Installing {kind} {release}'",
              f'"$spack" -e {quote(env)} install -j {jobs}',
              f'"$spack" -e {quote(env)} env view regenerate',
              f"{quote(check)} --version >/dev/null"]
    add_file(lines, root / "modules" / kind / release, gpu_modulefile(kind, release, view))
    return lines + [
        ";;",
        f"*) echo '==> Skipping {kind} {release}: not available for '\"$(uname -m)\" ;;",
        "esac",
    ]


def add_file(lines, path, content):
    lines += [f"mkdir -p {quote(Path(path).parent)}", f"cat > {quote(path)} <<'OPENSN_EOF'",
              content, "OPENSN_EOF"]


def prune_lines(root, envs, stacks, compilers):
    """Remove stack environments, views, and modules that are no longer configured.

    ``stacks`` holds the configured environment names and ``compilers`` the configured
    FAMILY/RELEASE pairs. Every remaining environment directory protects its packages
    (including build dependencies) from garbage collection.
    """
    opensn, compiler_root, modules = root / "opensn", root / "compilers", root / "modules"
    return [
        "echo '==> Pruning stacks that are no longer configured'",
        "keep_stacks=" + quote(" " + " ".join(stacks) + " "),
        "keep_compilers=" + quote(" " + " ".join(compilers) + " "),
        f"for env_dir in {quote(envs)}/*-mpich-*/; do",
        '  [[ -d $env_dir ]] || continue',
        '  name=$(basename "$env_dir")',
        '  [[ $keep_stacks == *" $name "* ]] && continue',
        '  if [[ ! $name =~ ^(gcc|clang|oneapi)-([0-9.]+)-mpich-([0-9.]+)$ ]]; then',
        '    echo "Skipping unrecognized environment $name" >&2',
        "    continue",
        "  fi",
        '  family=${BASH_REMATCH[1]} release=${BASH_REMATCH[2]} mpi=${BASH_REMATCH[3]}',
        '  echo "==> Removing stack $name"',
        f'  rm -rf -- "$env_dir" {quote(opensn)}/"$family/$family-$release/mpich-$mpi"',
        f'  rmdir {quote(opensn)}/"$family/$family-$release" 2>/dev/null || true',
        '  if [[ $keep_compilers != *" $family/$release "* ]]; then',
        f'    rm -rf -- {quote(compiler_root)}/"$family/$release" '
        f'{quote(modules)}/"$family/$release"',
        "  fi",
        "done",
        "keep_envs=()",
        f'for env_dir in {quote(envs)}/*/; do keep_envs+=(-e "$env_dir"); done',
        '"$spack" gc -y -b "${keep_envs[@]}"',
    ]


def generate(config):
    root = Path(config["root"])
    private = root / ".spack"
    source = private / "spack"
    store = private / "store"
    envs = private / "environments"
    python_view = root / "python" / f'python-{config["python"]}'
    common_venv = root / "python" / f'common-{config["python"]}'
    clone = " ".join(["git clone --depth 1 --branch", quote(config["spack"]["ref"]),
                      quote(config["spack"]["url"]), quote(source)])
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "[[ $(uname -s) == Linux ]] || { echo 'Linux is required' >&2; exit 1; }",
        "command -v git >/dev/null; command -v python3 >/dev/null; command -v flock >/dev/null",
        f"mkdir -p {quote(private)} {quote(config['work'])}",
        f"exec 9>{quote(private / 'install.lock')}",
        ("flock -n 9 || { echo 'Another OpenSn toolchain install is using "
         f"{root}' >&2; exit 1; }}"),
        f"if [[ ! -x {quote(source / 'bin/spack')} ]]; then",
        clone,
        "fi",
        f"export SPACK_USER_CONFIG_PATH={quote(private / 'config')}",
        f"export SPACK_USER_CACHE_PATH={quote(private / 'cache')}",
        f"spack={quote(source / 'bin/spack')}",
        '"$spack" config --scope user remove config:build_stage >/dev/null 2>&1 || true',
        ('"$spack" config --scope user add '
         f'{quote("config:build_stage:[" + str(Path(config["work"]) / "spack-stage") + "]")}'),
        f'"$spack" repo update --commit {quote(config["spack"]["packages_ref"])} builtin',
        '"$spack" repo remove opensn >/dev/null 2>&1 || true',
        f'"$spack" repo add {quote(PROJECT / "spack")}',
        "echo '==> Detecting compatible system build tools'",
        '"$spack" config --scope user remove packages:perl',
        '"$spack" config --scope user remove packages:curl',
        ('"$spack" external find --scope user --tag build-tools '
         '--exclude cmake --exclude gmake --exclude python '
         '--exclude python-venv --exclude \'py-.*\' --exclude perl '
         '--exclude curl --exclude libxcb --exclude libxcrypt'),
    ]
    common_env = envs / f'python-{config["python"]}'
    common_specs = [f'python@{config["python"]}+shared~libxml2',
                    f'cmake@{config["dependencies"]["cmake"]}',
                    f'gmake@{config["dependencies"]["gmake"]}']
    add_file(lines, common_env / "spack.yaml", manifest(common_specs, python_view, store))
    lines += [f"echo '==> Concretizing shared Python {config['python']}'",
              f'"$spack" -e {quote(common_env)} concretize -f',
              f"echo '==> Installing shared Python {config['python']}'",
              f'"$spack" -e {quote(common_env)} install -j {config["jobs"]}',
              f'"$spack" -e {quote(common_env)} env view regenerate',
              f"{quote(python_view / 'bin/python3')} -m venv {quote(common_venv)}",
              f"{quote(common_venv / 'bin/python')} -m pip install --upgrade pip setuptools wheel",
              f"{quote(common_venv / 'bin/python')} -m pip install "
              f"-r {quote(PROJECT / 'python-requirements.txt')}"]
    if config["docs"]:
        lines.append(f"{quote(common_venv / 'bin/python')} -m pip install "
                     f"-r {quote(PROJECT / 'documentation-requirements.txt')}")
        common_test = (
            "import breathe, exhale, h5py, IPython, matplotlib, nbconvert, nbformat, nbsphinx, "
            "numpy, pybind11, sphinx, sphinx_design, sphinx_rtd_theme, sphinxcontrib.bibtex; "
            "assert not h5py.get_config().mpi"
        )
    else:
        common_test = ("import h5py, matplotlib, numpy, pybind11; "
                       "assert not h5py.get_config().mpi")
    lines.append(f"{quote(common_venv / 'bin/python')} -c {quote(common_test)}")

    for name in ("doxygen", "pandoc"):
        release = config["dependencies"][name]
        tool_env = envs / f"{name}-{release}"
        tool_view = root / "tools" / name / release / "view"
        add_file(lines, tool_env / "spack.yaml",
                 manifest([f"{name}@{release}"], tool_view, store))
        lines += [f"echo '==> Concretizing {name} {release}'",
                  f'"$spack" -e {quote(tool_env)} concretize -f',
                  f"echo '==> Installing {name} {release}'",
                  f'"$spack" -e {quote(tool_env)} install -j {config["jobs"]}',
                  f'"$spack" -e {quote(tool_env)} env view regenerate',
                  f"{quote(tool_view / 'bin' / name)} --version >/dev/null"]
        add_file(lines, root / "modules" / name / release,
                 tool_modulefile(name, release, tool_view))
    for kind, release in config["gpu"].items():
        lines += gpu_lines(kind, release, root, envs, store, config["jobs"])
    py_site = "lib/python" + ".".join(config["python"].split(".")[:2]) + "/site-packages"
    stacks, compilers = [], []
    for item in config["compilers"]:
        family, release, mpi = item["family"], item["version"], item["mpich"]
        stacks.append(f"{family}-{release}-mpich-{mpi}")
        compilers.append(f"{family}/{release}")
        prefix = root / "opensn" / family / f"{family}-{release}" / f"mpich-{mpi}"
        view = prefix / "view"
        stack_venv = prefix / "venv"
        stack_env = envs / f"{family}-{release}-mpich-{mpi}"
        compiler_prefix = root / "compilers" / family / release
        compiler_view = compiler_prefix / "view"
        bootstrap_view = None
        externals = [
            ("python", f'python@{config["python"]}+shared~libxml2', python_view, None),
            ("cmake", f'cmake@{config["dependencies"]["cmake"]}', python_view, None),
            ("gmake", f'gmake@{config["dependencies"]["gmake"]}', python_view, None),
        ]
        if family == "gcc":
            compiler = f"gcc@{release} languages:=c,c++"
            compiler_ref = f"gcc@{release}"
            bootstrap = None
            reuse_specs = [f"gcc@{release}", f"%gcc@{release}"]
            compiler_mixing = False
        elif family == "clang":
            targets = "x86,nvptx" if config["clang_ptx"] else "x86"
            bootstrap = (f"gcc@{item['gcc_toolchain']} "
                         "languages:=c,c++")
            bootstrap_view = root / "compilers" / "gcc" / item["gcc_toolchain"] / "view"
            gcc_release = item["gcc_toolchain"]
            reuse_specs = [f"gcc@{gcc_release}", f"%gcc@{gcc_release}",
                           f"llvm@{release}", f"%llvm@{release}"]
            externals.append((
                "gcc", f"gcc@{gcc_release} languages='c,c++'", bootstrap_view,
                {"c": bootstrap_view / "bin/gcc", "cxx": bootstrap_view / "bin/g++"},
            ))
            compiler = (f"llvm@{release}+clang+lld+lldb~flang openmp=runtime "
                        f"targets:={targets} %gcc@{item['gcc_toolchain']}")
            compiler_ref = f"llvm@{release}"
            compiler_mixing = False
        else:
            bootstrap = (f"gcc@{item['gcc_toolchain']} "
                         "languages:=c,c++")
            bootstrap_view = root / "compilers" / "gcc" / item["gcc_toolchain"] / "view"
            gcc_release = item["gcc_toolchain"]
            reuse_specs = [f"gcc@{gcc_release}", f"%gcc@{gcc_release}",
                           f"intel-oneapi-compilers@{release}",
                           f"%intel-oneapi-compilers@{release}"]
            externals.append((
                "gcc", f"gcc@{gcc_release} languages='c,c++'", bootstrap_view,
                {"c": bootstrap_view / "bin/gcc", "cxx": bootstrap_view / "bin/g++"},
            ))
            compiler = f"intel-oneapi-compilers@{release} %gcc@{item['gcc_toolchain']}"
            compiler_ref = f"intel-oneapi-compilers@{release}"
            compiler_mixing = False
        specs = dependency_specs(config["dependencies"], mpi, compiler_ref)
        if bootstrap_view:
            tools = [bootstrap_view / "bin" / name for name in ("gcc", "g++")]
            checks = " && ".join(f"[[ -x {quote(path)} ]]" for path in tools)
            lines.append(f"{checks} || {{ echo 'Missing GCC bootstrap view: "
                         f"{bootstrap_view}' >&2; exit 1; }}")
        add_file(lines, stack_env / "spack.yaml",
                 stack_manifest(compiler, specs, compiler_view, view, store,
                                compiler_mixing, reuse_specs, externals,
                                blas_packages(config["dependencies"]), bootstrap))
        mpi_test = ("import h5py, numpy; assert not h5py.get_config().mpi; "
                    "from mpi4py import MPI; assert MPI.COMM_WORLD.size == 2; "
                    "assert 'MPICH' in MPI.Get_library_version()")
        label = f"{family} {release} / MPICH {mpi}"
        lines += [f"echo '==> Concretizing {label}'",
                  f'"$spack" -e {quote(stack_env)} concretize -f']
        # Intel's offline installers clean up files under /tmp/$USER, including other packages'
        # Spack stages, so each one is installed while no other build is running.
        if family == "oneapi":
            lines.append(f'"$spack" -e {quote(stack_env)} install --only-concrete '
                         'intel-oneapi-compilers')
        lines += ['if [[ $(uname -m) == x86_64 ]]; then',
                  f'"$spack" -e {quote(stack_env)} install --only-concrete intel-oneapi-mkl',
                  "fi",
                  f"echo '==> Installing {label}'",
                  f'"$spack" -e {quote(stack_env)} install -j {config["jobs"]}',
                  f'"$spack" -e {quote(stack_env)} env view regenerate',
                  f"{quote(python_view / 'bin/python3')} -m venv {quote(stack_venv)}",
                  f"{quote(stack_venv / 'bin/python')} -m pip install --upgrade "
                  "pip setuptools wheel",
                  f"MPI4PY_BUILD_MPICC={quote(view / 'bin/mpicc')} "
                  f"{quote(stack_venv / 'bin/python')} -m pip install --no-cache-dir "
                  "--no-binary=mpi4py mpi4py"]
        add_file(lines, stack_venv / py_site / "opensn-common.pth", str(common_venv / py_site))
        lines.append(f"{quote(view / 'bin/mpiexec')} -n 2 "
                     f"{quote(stack_venv / 'bin/python')} -c {quote(mpi_test)}")
        add_file(lines, root / "modules" / family / release,
                 modulefile(family, release, mpi, compiler_view,
                            compiler_view if family == "gcc" else bootstrap_view, view, python_view,
                            common_venv, stack_venv, config["python"]))
    if config["prune"]:
        lines += prune_lines(root, envs, stacks, compilers)
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        content = generate(validate(json.loads(args.config.read_text())))
        with args.output.open("x") as stream:
            stream.write(content)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(f"Wrote {args.output}; review it, then run: bash {quote(args.output)}")


if __name__ == "__main__":
    main()
