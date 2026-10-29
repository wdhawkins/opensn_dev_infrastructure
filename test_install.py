# SPDX-FileCopyrightText: 2026 The OpenSn Authors <https://open-sn.github.io/opensn/>
# SPDX-License-Identifier: MIT
import copy
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import install

CONFIG = {
    "python": "3.13.13",
    "mpich": "5.0.2",
    "dependencies": copy.deepcopy(install.DEPENDENCIES),
    "compilers": [
        {"family": "gcc", "version": "16.2.0"},
        {"family": "clang", "version": "23.1.2", "gcc_toolchain": "16.2.0"},
        {"family": "oneapi", "version": "2026.1.1", "gcc_toolchain": "16.2.0"},
    ],
}


def heredoc(script, path):
    """Return the content that the generated script writes to path."""
    return script.split(f"cat > {path} <<'OPENSN_EOF'\n", 1)[1].split("OPENSN_EOF", 1)[0]


CUDA_EXTERNAL = '      - spec: "cuda@13.4.1"\n        prefix: /opt/local/gpu/cuda/13.4.1/view'


class InstallerTests(unittest.TestCase):
    def test_selection(self):
        self.assertEqual(install.newest_majors(["16.1.0", "16.2.0", "15.3.0", "14.4.0"]),
                         ["16.2.0", "15.3.0", "14.4.0"])
        with patch.object(install, "compiler_releases",
                          return_value=["16.2.0", "15.3.0", "14.4.0"]):
            result = install.resolve_compilers([{"family": "gcc", "version": "latest-3"}])
        self.assertEqual(len(result), 3)

    def test_invalid(self):
        for change in ({"jobs": 0}, {"root": "/"}, {"cuda": False}, {"compilers": []}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                install.validate(dict(CONFIG, **change))
        value = copy.deepcopy(CONFIG)
        value["compilers"][1]["gcc_toolchain"] = "12.1.0"
        with self.assertRaises(ValueError):
            install.validate(value)
        reordered = copy.deepcopy(CONFIG)
        reordered["compilers"] = list(reversed(reordered["compilers"]))
        self.assertEqual(install.validate(reordered)["compilers"][0]["family"], "gcc")
        for dependencies in ({}, {"mpicpp-lite": "3.0"}):
            with self.subTest(dependencies=dependencies), self.assertRaises(ValueError):
                install.validate(dict(CONFIG, dependencies=dependencies))
        bad = copy.deepcopy(CONFIG["dependencies"])
        bad["mpicpp-lite"] = "2.7:3.0"
        with self.assertRaises(ValueError):
            install.validate(dict(CONFIG, dependencies=bad))
        compatible = copy.deepcopy(CONFIG["dependencies"])
        compatible["hdf5"] = "1.14.4-3"
        self.assertEqual(install.validate(dict(CONFIG, dependencies=compatible))["dependencies"],
                         compatible)

    def test_generated_installer(self):
        script = install.generate(install.validate(CONFIG))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "install.sh"
            path.write_text(script)
            subprocess.run(["bash", "-n", path], check=True)
        self.assertIn("git clone --depth 1 --branch v1.2.2", script)
        self.assertIn("repo update --commit " + install.DEFAULT_PACKAGES_REF + " builtin", script)
        self.assertIn('repo remove opensn >/dev/null 2>&1 || true', script)
        self.assertIn("root: /opt/local/.spack/store", script)
        self.assertNotIn("reuse: true", script)
        self.assertEqual(script.count("reuse: false"), 3)
        self.assertEqual(script.count("roots: true"), 3)
        self.assertEqual(script.count("- type: local"), 3)
        self.assertEqual(script.count("- type: external"), 3)
        common = script.split("- group: compiler", 1)[0]
        self.assertIn("- python@3.13.13+shared~libxml2", common)
        self.assertIn("- cmake@3.31.12", common)
        self.assertIn("- gmake@4.4.1", common)
        self.assertNotIn("  - py-", common)
        self.assertIn("-m pip install -r "
                      + str(install.PROJECT / "python-requirements.txt"), common)
        self.assertIn("-m pip install -r "
                      + str(install.PROJECT / "documentation-requirements.txt"),
                      common)
        self.assertIn("assert not h5py.get_config().mpi", common)
        no_docs = copy.deepcopy(CONFIG)
        no_docs["docs"] = False
        self.assertNotIn("documentation-requirements.txt",
                         install.generate(install.validate(no_docs)))
        tool_requirements = (install.PROJECT / "python-requirements.txt").read_text()
        for package in ("pybind11", "numpy", "matplotlib", "h5py"):
            self.assertIn(package, tool_requirements.splitlines())
        doc_requirements = (
            install.PROJECT / "documentation-requirements.txt"
        ).read_text().splitlines()
        for package in ("Sphinx", "sphinx_design", "sphinx-rtd-theme",
                        "sphinxcontrib-bibtex", "nbsphinx", "ipython", "nbconvert",
                        "nbformat", "breathe", "exhale"):
            self.assertIn(package, doc_requirements)
        self.assertIn("flock -n 9 ||", script)
        self.assertEqual(script.count("install --only-concrete intel-oneapi-mkl"), 3)
        self.assertEqual(script.count("install --only-concrete intel-oneapi-compilers"), 1)
        mkl = script.index("install --only-concrete intel-oneapi-mkl")
        self.assertLess(script.index("concretize -f", script.index("Concretizing gcc 16.2.0")), mkl)
        self.assertLess(mkl, script.index("==> Installing gcc 16.2.0"))
        self.assertIn("config:build_stage:[/tmp/opensn-toolchains/spack-stage]", script)
        self.assertIn("- doxygen@1.17.0", script)
        self.assertIn("- pandoc@3.7.0.2", script)
        self.assertIn("/opt/local/tools/doxygen/1.17.0/view", script)
        self.assertIn("/opt/local/tools/pandoc/3.7.0.2/view", script)
        self.assertIn("doxygen --version", script)
        self.assertIn("pandoc --version", script)
        compiler = "- gcc@16.2.0 languages:=c,c++"
        self.assertIn(compiler, script)
        self.assertNotIn("opensn-develop", script)
        self.assertNotIn("opensn@", script)
        self.assertIn("mpicpp-lite@2.7.1 %gcc@16.2.0 ^mpich@5.0.2", script)
        self.assertIn("petsc@3.26.0+mpi+double~complex+int64", script)
        self.assertIn("^hypre@3.0.0", script)
        self.assertIn("^superlu-dist@9.2.1~fortran", script)
        self.assertIn("+hypre+superlu-dist~fortran %gcc@16.2.0", script)
        self.assertIn("^scotch@7.0.16~fortran", script)
        self.assertIn("mpich@5.0.2~fortran %gcc@16.2.0", script)
        self.assertNotIn("mpich@5.0.2+fortran", script)
        self.assertNotIn("gfortran", script)
        self.assertNotIn("+flang", script)
        self.assertNotIn("^intel-oneapi-mkl", script)
        self.assertNotIn("^openblas", script)
        self.assertEqual(script.count('require: "@2026.1.0"'), 3)
        self.assertEqual(script.count('require: "@0.3.34~fortran"'), 3)
        self.assertEqual(script.count('- spec: "^[virtuals=blas,lapack] intel-oneapi-mkl"\n'
                                      '        when: "target=x86_64:"'), 9)
        self.assertIn("- group: compiler", script)
        self.assertIn("- group: stack", script)
        self.assertIn("needs: [compiler]", script)
        self.assertIn("group: compiler", script)
        self.assertIn("group: stack", script)
        self.assertIn("Concretizing gcc 16.2.0 / MPICH 5.0.2", script)
        self.assertIn("/opt/local/compilers/gcc/16.2.0/view", script)
        self.assertIn("llvm@23.1.2+clang+lld+lldb~flang", script)
        self.assertIn("%llvm@23.1.2", script)
        self.assertIn("%intel-oneapi-compilers@2026.1.1", script)
        self.assertEqual(script.count("- group: bootstrap"), 2)
        self.assertEqual(script.count("needs: [bootstrap]"), 2)
        self.assertEqual(script.count("      externals:\n"), 11)
        self.assertEqual(script.count("languages='c,c++'"), 2)
        self.assertEqual(script.count('spec: "python@3.13.13+shared~libxml2"'), 3)
        self.assertEqual(script.count('spec: "cmake@3.31.12"'), 3)
        self.assertEqual(script.count('spec: "gmake@4.4.1"'), 3)
        self.assertEqual(script.count('require: "~llvm"'), 3)
        self.assertNotIn("llvm-amdgpu", script)
        self.assertIn('- "%gcc@16.2.0"', script)
        self.assertIn('- "%llvm@23.1.2"', script)
        self.assertIn("prefix: /opt/local/compilers/gcc/16.2.0/view", script)
        self.assertIn("cxx: /opt/local/compilers/gcc/16.2.0/view/bin/g++", script)
        self.assertIn("Missing GCC bootstrap view: /opt/local/compilers/gcc/16.2.0/view", script)
        clang = script[script.index("- group: bootstrap", script.index("llvm@23.1.2") - 300):]
        self.assertIn("- gcc@16.2.0 languages:=c,c++", clang)
        self.assertLess(clang.index("- group: bootstrap"), clang.index("- group: compiler"))
        self.assertLess(clang.index("- group: compiler"), clang.index("- group: stack"))
        self.assertEqual(script.count("compiler_mixing: false"), 3)
        self.assertNotIn("compiler_mixing: [superlu-dist]", script)
        self.assertNotIn("^python", script)
        self.assertNotIn("py-mpi4py", script)
        self.assertIn("MPI4PY_BUILD_MPICC=/opt/local/opensn/gcc/", script)
        self.assertIn("--no-binary=mpi4py mpi4py", script)
        self.assertIn("opensn-common.pth", script)
        self.assertIn("from mpi4py import MPI", script)
        self.assertNotIn("spack load", script)
        self.assertIn("external find --scope user --tag build-tools", script)
        self.assertIn("--exclude cmake --exclude gmake --exclude python", script)
        self.assertIn("--exclude 'py-.*' --exclude perl", script)
        self.assertIn("config --scope user remove packages:perl", script)
        self.assertIn("--exclude curl", script)
        self.assertIn("config --scope user remove packages:curl", script)
        self.assertNotIn("external find --all", script)
        self.assertEqual(script.count("env view regenerate"), 6)
        self.assertEqual(script.count("externals:: []"), 1)
        self.assertNotIn("+cuda", script)
        for family, release in (("gcc", "16.2.0"), ("clang", "23.1.2"), ("oneapi", "2026.1.1")):
            self.assertIn(f"cat > /opt/local/modulefiles/opensn/{family}/{release} <<", script)
        self.assertIn("cat > /opt/local/modulefiles/doxygen/1.17.0 <<", script)
        self.assertNotIn("/opt/local/modules/", script)

    def test_modules(self):
        script = install.generate(install.validate(CONFIG))
        modules = [x.split("OPENSN_EOF", 1)[0] for x in script.split("#%Module1.0\n")[1:]]
        self.assertEqual(len(modules), 5)
        for module in modules:
            preamble = "\n".join(f"proc {x} {{args}} {{}}" for x in
                                 ["module-whatis", "conflict", "setenv", "prepend-path"])
            subprocess.run(["tclsh"], input=preamble + "\n" + module, text=True, check=True)
            self.assertNotIn(".spack", module)
        stack_modules = [module for module in modules if "module-whatis \"OpenSn " in module
                         and "documentation tool" not in module]
        self.assertEqual(len(stack_modules), 3)
        for module in stack_modules:
            self.assertIn("setenv VIRTUAL_ENV", module)
            self.assertNotIn("setenv FC", module)
            self.assertNotIn("setenv F77", module)
            self.assertNotIn("setenv MPIFC", module)
            self.assertIn("/venv/bin/python", module)
            self.assertIn("setenv pybind11_DIR", module)
            self.assertIn("/opt/local/compilers/", module)
            self.assertIn("/opt/local/python/python-3.13.13/bin", module)
            self.assertIn("prepend-path LD_PRELOAD", module)
            self.assertIn("setenv HIPFLAGS --gcc-toolchain=/opt/local/compilers/gcc/16.2.0/view",
                          module)
            self.assertIn("setenv CLANG_FORMAT /opt/local/python/common-3.13.13/bin/clang-format",
                          module)
            self.assertIn("/lib64/libstdc++.so.6", module)
        doxygen = next(module for module in modules if "documentation tool doxygen" in module)
        self.assertIn("setenv DOXYGEN_ROOT /opt/local/tools/doxygen/1.17.0/view", doxygen)
        self.assertIn("prepend-path PATH /opt/local/tools/doxygen/1.17.0/view/bin", doxygen)
        pandoc = next(module for module in modules if "documentation tool pandoc" in module)
        self.assertIn("setenv PANDOC_ROOT /opt/local/tools/pandoc/3.7.0.2/view", pandoc)
        self.assertIn("prepend-path PATH /opt/local/tools/pandoc/3.7.0.2/view/bin", pandoc)
        oneapi = next(module for module in stack_modules if "OpenSn oneapi" in module)
        self.assertIn("/compiler/latest/bin/icx", oneapi)
        self.assertIn("/compiler/latest/bin/icpx", oneapi)
        root = "/opt/local/compilers/oneapi/2026.1.1/view/compiler/latest"
        self.assertIn(f"setenv CMPLR_ROOT {root}", oneapi)
        self.assertIn(f"prepend-path LD_LIBRARY_PATH {root}/lib", oneapi)
        self.assertIn(f"prepend-path OCL_ICD_FILENAMES {root}/lib/libintelocl.so", oneapi)
        for module in stack_modules:
            if module is not oneapi:
                self.assertNotIn("CMPLR_ROOT", module)

    def test_gpu_toolkits_are_independent_environments(self):
        script = install.generate(install.validate(copy.deepcopy(CONFIG)))
        self.assertNotIn("cuda@", script)
        self.assertNotIn("hip@", script)
        config = dict(copy.deepcopy(CONFIG), gpu={"cuda": "latest", "rocm": "10.0.0"})
        with patch.object(install, "gpu_release", return_value="13.4.1") as latest:
            resolved = install.validate(config)
        latest.assert_called_once_with("cuda", install.DEFAULT_PACKAGES_REF)
        self.assertEqual(resolved["gpu"], {"cuda": "13.4.1", "rocm": "10.0.0"})
        script = install.generate(resolved)
        self.assertIn("  - cuda@13.4.1\n  view: /opt/local/gpu/cuda/13.4.1/view", script)
        self.assertIn("  - hip@10.0.0\n  view: /opt/local/gpu/rocm/10.0.0/view", script)
        self.assertIn('case "$(uname -m)" in x86_64|aarch64)', script)
        self.assertIn('case "$(uname -m)" in x86_64)', script)
        self.assertIn("setenv CUDAToolkit_ROOT /opt/local/gpu/cuda/13.4.1/view", script)
        self.assertIn("setenv HIPCXX /opt/local/gpu/rocm/10.0.0/view/bin/clang++", script)
        for module in ("/opt/local/modulefiles/cuda/13.4.1",
                       "/opt/local/modulefiles/rocm/10.0.0"):
            self.assertLess(script.index("--version >/dev/null"), script.index(module))
        env = script.index("environments/cuda-13.4.1/spack.yaml")
        self.assertNotIn("%", script[env:script.index("OPENSN_EOF", env)])
        self.assertLess(script.index("Installing rocm 10.0.0"),
                        script.index("Concretizing gcc 16.2.0"))
        for bad in ({"cuda": "13"}, {"opencl": "latest"}, ["cuda"]):
            with self.subTest(gpu=bad), self.assertRaises(ValueError):
                install.validate(dict(copy.deepcopy(CONFIG), gpu=bad))

    def test_gpu_release_reads_pinned_recipes(self):
        cuda = '    "13.4.1": {\n    "13.3.1": {\n    "12.9.1": {\n'
        hip = '    version("10.0.0", sha256="a")\n    version("7.14.0", sha256="b")\n'
        with patch.object(install, "read_url", return_value=cuda):
            self.assertEqual(install.gpu_release("cuda"), "13.4.1")
        with patch.object(install, "read_url", return_value=hip):
            self.assertEqual(install.gpu_release("rocm"), "10.0.0")

    def test_prune_is_opt_in(self):
        script = install.generate(install.validate(copy.deepcopy(CONFIG)))
        self.assertNotIn("gc -y", script)
        script = install.generate(install.validate(dict(copy.deepcopy(CONFIG), prune=True)))
        self.assertIn("keep_stacks=' gcc-16.2.0-mpich-5.0.2 clang-23.1.2-mpich-5.0.2 "
                      "oneapi-2026.1.1-mpich-5.0.2 '", script)
        self.assertLess(script.rindex("install -j"), script.index("Pruning stacks"))
        with self.assertRaises(ValueError):
            install.validate(dict(copy.deepcopy(CONFIG), prune="yes"))

    def test_prune_removes_only_unconfigured_stacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            envs = root / ".spack/environments"
            paths = {
                "env_keep": envs / "gcc-16.2.0-mpich-5.0.2",
                "env_old_mpich": envs / "gcc-16.2.0-mpich-4.3.0",
                "env_old_gcc": envs / "gcc-13.4.0-mpich-5.0.2",
                "env_python": envs / "python-3.13.13",
                "env_unknown": envs / "custom-mpich-x",
                "stack_keep": root / "opensn/gcc/gcc-16.2.0/mpich-5.0.2",
                "stack_old_mpich": root / "opensn/gcc/gcc-16.2.0/mpich-4.3.0",
                "stack_old_gcc": root / "opensn/gcc/gcc-13.4.0/mpich-5.0.2",
                "compiler_keep": root / "compilers/gcc/16.2.0/view",
                "compiler_old": root / "compilers/gcc/13.4.0/view",
            }
            for path in paths.values():
                path.mkdir(parents=True)
            for name in ("16.2.0", "13.4.0"):
                (root / "modulefiles/opensn/gcc").mkdir(parents=True, exist_ok=True)
                (root / "modulefiles/opensn/gcc" / name).write_text("#%Module1.0\n")
            log = root / "spack.log"
            stub = root / "spack"
            stub.write_text(f'#!/bin/sh\necho "$@" > {log}\n')
            stub.chmod(0o755)
            lines = install.prune_lines(root, envs, ["gcc-16.2.0-mpich-5.0.2"], ["gcc/16.2.0"])
            script = "set -euo pipefail\n" + f"spack={stub}\n" + "\n".join(lines) + "\n"
            subprocess.run(["bash"], input=script, text=True, check=True, capture_output=True)
            for key in ("env_keep", "env_python", "env_unknown", "stack_keep", "compiler_keep"):
                self.assertTrue(paths[key].exists(), key)
            for key in ("env_old_mpich", "env_old_gcc", "stack_old_mpich", "stack_old_gcc",
                        "compiler_old"):
                self.assertFalse(paths[key].exists(), key)
            self.assertFalse((root / "opensn/gcc/gcc-13.4.0").exists())
            self.assertTrue((root / "modulefiles/opensn/gcc/16.2.0").exists())
            self.assertFalse((root / "modulefiles/opensn/gcc/13.4.0").exists())
            gc = log.read_text().split()
            self.assertEqual(gc[:3], ["gc", "-y", "-b"])
            kept = {Path(x).name for x in gc[3:] if x != "-e"}
            self.assertEqual(kept, {"gcc-16.2.0-mpich-5.0.2", "python-3.13.13",
                                    "custom-mpich-x"})

    def test_stack_modules_conflict_and_skip_hipflags_on_nvidia(self):
        script = install.generate(install.validate(CONFIG))
        module = heredoc(script, "/opt/local/modulefiles/opensn/gcc/16.2.0")
        self.assertIn("conflict opensn/gcc opensn/gcc-cuda opensn/clang opensn/oneapi", module)
        preamble = "\n".join(f"proc {x} {{args}} {{}}"
                             for x in ["module-whatis", "conflict", "prepend-path"])
        preamble += "\nproc setenv {name args} { puts $name }"
        for platform, expected in ((None, True), ("amd", True), ("nvidia", False)):
            with self.subTest(platform=platform):
                env = {k: v for k, v in os.environ.items() if k != "HIP_PLATFORM"}
                if platform:
                    env["HIP_PLATFORM"] = platform
                result = subprocess.run(["tclsh"], input=preamble + "\n" + module, text=True,
                                        check=True, capture_output=True, env=env)
                self.assertEqual("HIPFLAGS" in result.stdout.split(), expected)

    def cuda_config(self, **entry):
        config = copy.deepcopy(CONFIG)
        config["gpu"] = {"cuda": "13.4.1"}
        config["compilers"].insert(0, dict({"family": "gcc", "version": "16.2.0",
                                            "cuda_arch": "89",
                                            "dependencies": {"hypre": "3.2.0"}}, **entry))
        return config

    def test_cuda_stack(self):
        resolved = install.validate(self.cuda_config())
        self.assertEqual([(x["family"], "cuda" in x) for x in resolved["compilers"]],
                         [("gcc", False), ("clang", False), ("oneapi", False), ("gcc", True)])
        self.assertEqual(resolved["compilers"][0]["dependencies"]["hypre"], "3.0.0")
        self.assertEqual(resolved["compilers"][-1]["dependencies"]["hypre"], "3.2.0")
        script = install.generate(resolved)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "install.sh"
            path.write_text(script)
            subprocess.run(["bash", "-n", path], check=True)
        env = "/opt/local/.spack/environments/gcc-16.2.0-cuda-13.4.1-mpich-5.0.2/spack.yaml"
        start = script.index(f"cat > {env}")
        manifest = script[start:script.index("OPENSN_EOF", script.index("\n", start) + 1)]
        self.assertIn("    - gcc@16.2.0 languages:=c,c++", manifest)
        self.assertIn("mpich@5.0.2~fortran+cuda cuda_arch=89 %gcc@16.2.0 ^cuda@13.4.1", manifest)
        self.assertIn("caliper@2.15.0+mpi~gotcha~kokkos+cuda cuda_arch=89 %gcc@16.2.0", manifest)
        self.assertIn("+hypre+superlu-dist~fortran+cuda cuda_arch=89 %gcc@16.2.0", manifest)
        self.assertIn("^hypre@3.2.0+cuda cuda_arch=89", manifest)
        self.assertIn("^superlu-dist@9.2.1~fortran+cuda cuda_arch=89", manifest)
        self.assertIn(CUDA_EXTERNAL, manifest)
        # The compiler view belongs to the GCC stack; the CUDA stack has only its own view.
        self.assertNotIn("/opt/local/compilers/gcc/16.2.0/view\n      group: compiler", manifest)
        self.assertIn("root: /opt/local/opensn/gcc/gcc-16.2.0/cuda-13.4.1-mpich-5.0.2/view",
                      manifest)
        self.assertLess(script.index("==> Installing gcc 16.2.0 / MPICH 5.0.2"),
                        script.index("==> Installing gcc 16.2.0 / CUDA 13.4.1 / MPICH 5.0.2"))
        self.assertLess(script.rindex('case "$(uname -m)" in x86_64|aarch64)'), start)
        cuda_section = script[start:]
        self.assertEqual(script.count("--with-cuda"), 1)
        self.assertIn("assert '\"'\"'--with-cuda'\"'\"' in MPI.Get_library_version()",
                      cuda_section)
        plain = script[:script.index("Concretizing clang")]
        self.assertNotIn("+cuda", plain)
        module = heredoc(script, "/opt/local/modulefiles/opensn/gcc-cuda/16.2.0")
        self.assertIn("setenv CUDA_HOME /opt/local/gpu/cuda/13.4.1/view", module)
        self.assertIn("setenv CUDAARCHS 89", module)
        self.assertIn("setenv OPENSN_STACK "
                      "/opt/local/opensn/gcc/gcc-16.2.0/cuda-13.4.1-mpich-5.0.2/view", module)
        self.assertIn("setenv CC /opt/local/compilers/gcc/16.2.0/view/bin/gcc", module)
        preamble = "\n".join(f"proc {x} {{args}} {{}}"
                             for x in ["module-whatis", "conflict", "setenv", "prepend-path"])
        subprocess.run(["tclsh"], input=preamble + "\n" + module, text=True, check=True)
        multi = install.validate(self.cuda_config(cuda_arch="80,90a"))
        self.assertIn("setenv CUDAARCHS 80;90a", install.generate(multi))

    def test_cuda_stack_latest_gcc(self):
        config = self.cuda_config(version="latest")
        config["compilers"].insert(1, {"family": "gcc", "version": "15.3.0"})
        cuda = [x for x in install.validate(config)["compilers"] if "cuda" in x]
        self.assertEqual([x["version"] for x in cuda], ["16.2.0"])

    def test_cuda_stack_invalid(self):
        no_gpu = self.cuda_config()
        del no_gpu["gpu"]
        cases = [no_gpu, self.cuda_config(cuda_arch="sm_89"), self.cuda_config(cuda_arch=89),
                 self.cuda_config(version="15.3.0"), self.cuda_config(family="clang"),
                 self.cuda_config(dependencies={"kokkos": "4.0.0"})]
        for config in cases:
            with self.subTest(config=config["compilers"][0]), self.assertRaises(ValueError):
                install.validate(config)

    def test_hip_nvidia(self):
        config = dict(copy.deepcopy(CONFIG), gpu={"hip_nvidia": "7.1.1", "cuda": "13.4.1"})
        script = install.generate(install.validate(config))
        self.assertIn("  - hip@7.1.1~rocm+cuda ^cuda@13.4.1\n"
                      "  view: /opt/local/gpu/hip-nvidia/7.1.1/view", script)
        self.assertIn(CUDA_EXTERNAL, script)
        self.assertLess(script.index("Installing cuda 13.4.1"),
                        script.index("Installing hip-nvidia 7.1.1"))
        module = heredoc(script, "/opt/local/modulefiles/hip-nvidia/7.1.1")
        for line in ("setenv HIP_PLATFORM nvidia", "setenv HIP_COMPILER nvcc",
                     "unsetenv HIPFLAGS", "setenv HIP_PATH /opt/local/gpu/hip-nvidia/7.1.1/view"):
            self.assertIn(line, module)
        with self.assertRaises(ValueError):
            install.validate(dict(copy.deepcopy(CONFIG), gpu={"hip_nvidia": "7.1.1"}))
        with patch.object(install, "gpu_release", return_value="10.0.0") as latest:
            resolved = install.validate(dict(copy.deepcopy(CONFIG),
                                             gpu={"cuda": "13.4.1", "hip_nvidia": "latest"}))
        latest.assert_called_once_with("rocm", install.DEFAULT_PACKAGES_REF)
        self.assertEqual(resolved["gpu"]["hip_nvidia"], "10.0.0")

    def test_prune_cuda_stack_keeps_gcc_compiler(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            envs = root / ".spack/environments"
            cuda_env = envs / "gcc-16.2.0-cuda-13.4.1-mpich-5.0.2"
            cuda_stack = root / "opensn/gcc/gcc-16.2.0/cuda-13.4.1-mpich-5.0.2"
            plain_stack = root / "opensn/gcc/gcc-16.2.0/mpich-5.0.2"
            compiler = root / "compilers/gcc/16.2.0/view"
            for path in (cuda_env, envs / "gcc-16.2.0-mpich-5.0.2", cuda_stack, plain_stack,
                         compiler):
                path.mkdir(parents=True)
            modules = root / "modulefiles/opensn"
            for module in ("gcc/16.2.0", "gcc-cuda/16.2.0"):
                (modules / module).parent.mkdir(parents=True, exist_ok=True)
                (modules / module).write_text("#%Module1.0\n")
            stub = root / "spack"
            stub.write_text("#!/bin/sh\n")
            stub.chmod(0o755)
            lines = install.prune_lines(root, envs, ["gcc-16.2.0-mpich-5.0.2"], ["gcc/16.2.0"])
            script = "set -euo pipefail\n" + f"spack={stub}\n" + "\n".join(lines) + "\n"
            subprocess.run(["bash"], input=script, text=True, check=True, capture_output=True)
            self.assertFalse(cuda_env.exists())
            self.assertFalse(cuda_stack.exists())
            self.assertFalse((modules / "gcc-cuda/16.2.0").exists())
            for path in (plain_stack, compiler, modules / "gcc/16.2.0"):
                self.assertTrue(path.exists(), path)

    def test_petsc_blas_check(self):
        script = install.generate(install.validate(CONFIG))
        self.assertEqual(script.count("petsc_libs=$(ldd "), 3)
        self.assertLess(script.index("petsc_libs=$(ldd /opt/local/opensn/gcc/gcc-16.2.0/"),
                        script.index("==> Concretizing clang"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env, view, mkl = root / "env", root / "view", root / "store/mkl"
            (mkl / "lib").mkdir(parents=True)
            (view / "lib").mkdir(parents=True)
            (view / "lib/libpetsc.so").write_text("")
            bin_dir = root / "bin"
            bin_dir.mkdir()
            for name in ("libmkl_intel_lp64", "libmkl_sequential", "libmkl_core"):
                (mkl / "lib" / f"{name}.so.2").write_text("")
            mkl_ldd = "".join(f"\t{name}.so.2 => {mkl}/lib/{name}.so.2 (0x0)\n"
                              for name in ("libmkl_intel_lp64", "libmkl_sequential",
                                           "libmkl_core"))
            openblas = "\tlibopenblas.so.0 => /x/libopenblas.so.0 (0x0)\n"
            spack = root / "spack"
            spack.write_text(f"#!/bin/sh\necho {mkl}\n")
            spack.chmod(0o755)
            lines = install.blas_check_lines(env, view, "gcc 16.2.0 / MPICH 5.0.2")
            cases = [("x86_64", mkl_ldd, True), ("x86_64", mkl_ldd + openblas, False),
                     ("x86_64", openblas, False),
                     ("x86_64", mkl_ldd.replace(str(mkl), "/usr/lib"), False),
                     ("aarch64", openblas, True), ("aarch64", mkl_ldd, False)]
            for machine, ldd, ok in cases:
                with self.subTest(machine=machine, ldd=ldd):
                    for name, output in (("uname", machine), ("ldd", ldd)):
                        stub = bin_dir / name
                        stub.write_text(f"#!/bin/sh\nprintf '%s' '{output}'\n")
                        stub.chmod(0o755)
                    script = (f'set -euo pipefail\nexport PATH="{bin_dir}:$PATH"\n'
                              f"spack={spack}\n" + "\n".join(lines) + "\n")
                    result = subprocess.run(["bash"], input=script, text=True,
                                            capture_output=True)
                    self.assertEqual(result.returncode == 0, ok, result.stderr)
                    if not ok:
                        self.assertIn("PETSc in gcc 16.2.0 / MPICH 5.0.2", result.stderr)

    def test_selected_petsc_version(self):
        self.assertEqual(install.DEPENDENCIES["petsc"], "3.26.0")

    def test_petsc_overlay_allows_superlu_dist_without_fortran(self):
        recipe = (install.PROJECT / "spack/packages/petsc/package.py").read_text()
        self.assertIn("class Petsc(BuiltinPetsc):", recipe)
        self.assertIn('"superlu-dist",', recipe)
        self.assertIn('depends_on("fortran", type="build", when="+fortran")', recipe)
        self.assertNotIn("version(", recipe)

    def test_rocm_overlays_drop_generated_fortran_dependency(self):
        for name, cls in (("comgr", "Comgr"), ("hipcc", "Hipcc")):
            with self.subTest(package=name):
                recipe = (install.PROJECT / f"spack/packages/{name}/package.py").read_text()
                self.assertIn(f"class {cls}(Builtin{cls}):", recipe)
                self.assertIn("_is_unconditional_fortran(directive)", recipe)
                self.assertNotIn("version(", recipe)

    def test_llvm_amdgpu_overlay_drops_libquadmath(self):
        recipe = (install.PROJECT / "spack/packages/llvm-amdgpu/package.py").read_text()
        self.assertIn("class LlvmAmdgpu(BuiltinLlvmAmdgpu):", recipe)
        self.assertIn('arg.startswith("-DFLANG_RUNTIME_F128_MATH_LIB")', recipe)
        self.assertNotIn("version(", recipe)

    def test_superlu_dist_overlay_makes_fortran_optional(self):
        recipe = (install.PROJECT / "spack/packages/superlu-dist/package.py").read_text()
        self.assertIn("class SuperluDist(BuiltinSuperluDist):", recipe)
        self.assertIn('variant("fortran", default=False', recipe)
        self.assertIn('define_from_variant("XSDK_ENABLE_Fortran", "fortran")', recipe)
        self.assertIn('depends_on("fortran", type="build", when="+fortran")', recipe)
        self.assertNotIn("version(", recipe)

    def test_mpicpp_lite_declares_compiler_languages(self):
        recipe = install.PROJECT.joinpath("spack/packages/mpicpp-lite/package.py").read_text()
        self.assertIn('depends_on("c", type="build")', recipe)
        self.assertIn('depends_on("cxx", type="build")', recipe)

    def test_scnlib_overlay_disables_all_benchmarks(self):
        recipe = (install.PROJECT / "spack/packages/scnlib/package.py").read_text()
        self.assertIn('self.define("SCN_BENCHMARKS_BUILDTIME", False)', recipe)
        self.assertIn('self.define("SCN_BENCHMARKS_BINARYSIZE", False)', recipe)


if __name__ == "__main__":
    unittest.main()
