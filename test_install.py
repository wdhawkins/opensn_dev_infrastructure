# SPDX-FileCopyrightText: 2026 The OpenSn Authors <https://open-sn.github.io/opensn/>
# SPDX-License-Identifier: MIT
import copy
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
        self.assertIn("- cmake@4.4.4", common)
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
        self.assertEqual(script.count('spec: "cmake@4.4.4"'), 3)
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

    def test_selected_petsc_version(self):
        self.assertEqual(install.DEPENDENCIES["petsc"], "3.26.0")

    def test_petsc_overlay_allows_superlu_dist_without_fortran(self):
        recipe = (install.PROJECT / "spack/packages/petsc/package.py").read_text()
        self.assertIn("class Petsc(BuiltinPetsc):", recipe)
        self.assertIn('"superlu-dist",', recipe)
        self.assertIn('depends_on("fortran", type="build", when="+fortran")', recipe)
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
