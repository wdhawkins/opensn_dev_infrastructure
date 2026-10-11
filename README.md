# OpenSn Linux development stacks

This standalone project installs the compiler and dependency stacks used to
develop OpenSn. It does not require an OpenSn source checkout or installation.

`install.py` generates a reviewable Linux installer. Spack is private: the
generated script checks out a pinned Spack, installs shared Python, installs
compiler-specific OpenSn dependency stacks, installs Python packages with pip,
installs shared Doxygen and Pandoc tools, validates each `mpi4py`, and writes
public Tcl modulefiles. It does not build or install OpenSn.

## Generate and run

```sh
cp example.json /tmp/opensn-toolchains.json
python3 install.py /tmp/opensn-toolchains.json \
  --output /tmp/install-opensn-toolchains.sh
bash -n /tmp/install-opensn-toolchains.sh
less /tmp/install-opensn-toolchains.sh
bash /tmp/install-opensn-toolchains.sh
```

`root` controls the installation, and each compiler may override the default
MPICH version. The installer updates Spack's builtin package repository to the
exact commit in `spack.packages_ref`. Generation resolves `latest-3` GCC and
Clang entries against that same commit, rather than selecting versions absent
from the installed recipes. Every direct OpenSn build dependency and each
numerically significant PETSc dependency has an exact version in the required
`dependencies` JSON object. To upgrade one, change its JSON value and regenerate
the installer. The selected version must exist in the corresponding Spack
package recipe at `spack.packages_ref` (or in this project's local overlay).
Installation requires Linux, Git, Python, a bootstrap C/C++
compiler, normal build tools, network access, and writable `root` and `work`
directories. It never invokes an OS package manager or sudo.

Before concretization, the installer asks Spack to detect compatible system
packages tagged as build tools and records them in its private user
configuration. Detected tools remain buildable, so Spack falls back to its own
package whenever the external version cannot satisfy a dependency. Python,
CMake, GNU Make, Python packages, and the small number of libraries carrying a
build-tool tag are excluded from automatic detection. Perl is also excluded:
executable-based detection cannot establish that a system Perl includes core
modules such as `FindBin`, which OpenSSL's configuration requires. Curl is
excluded because finding its executable does not establish that its development
headers and library are installed, which CMake requires. Python, CMake, and GNU
Make are managed by the shared common environment; libraries, compilers, MPI,
and the OpenSn dependency stack remain under explicit version and ABI control.
The installer deliberately does not use broad `external find --all` discovery.
It also removes Perl and Curl entries that an earlier installer may have written
to its private configuration before detecting the remaining tools.

## Layout

For `root=/opt/local`, packages live in a private hash-addressed store. Stable
views and modules hide that store from users:

```text
/opt/local/.spack/                         private Spack and package store
/opt/local/python/python-P.Y.Z/            shared Python/CMake/GNU Make view
/opt/local/python/common-P.Y.Z/            shared pip environment
/opt/local/tools/TOOL/X.Y.Z/view/          shared Doxygen or Pandoc view
/opt/local/compilers/FAMILY/X.Y.Z/view/    compiler view
/opt/local/opensn/FAMILY/FAMILY-X.Y.Z/
    mpich-M.Y.Z/view/                      MPI and OpenSn dependencies
    mpich-M.Y.Z/venv/                      stack-specific mpi4py environment
/opt/local/modules/FAMILY/X.Y.Z            public modulefile
/opt/local/modules/TOOL/X.Y.Z              public tool modulefile
```

Each compiler and its dependency stack are separate Spack spec groups in one
environment. The stack group explicitly depends on the compiler group, so Spack
solves the compiler first and makes only that result available to the stack
solve. After installation, the script explicitly regenerates every named view;
this also repairs views removed by forced reconcretization when every package is
already installed and the install itself is a no-op. Unrestricted reuse is
disabled, preventing an already installed stack from a different compiler from
enlarging or contaminating the next solve. Reuse is
instead filtered to the exact bootstrap and target compiler versions for each
environment. Thus LLVM can reuse prerequisites already built with its GCC
bootstrap compiler, while a Clang dependency stack cannot reuse libraries from
a GCC or different-Clang stack. GCC includes
C, C++, and Fortran because the pinned SuperLU_DIST recipe declares all three
build languages. LLVM includes Flang, and
oneAPI includes ifx, so every stack has a coherent C, C++, and Fortran compiler
set. The oneAPI module uses Intel's installed ``compiler/latest/bin`` entry
point, while GCC and LLVM expose their drivers directly in the view's ``bin``
directory. Clang and oneAPI environments contain an additional bootstrap group for
their selected GCC toolchain. The already installed GCC view is registered in
those manifests as an external compiler with explicit C, C++, and Fortran
paths. This gives Spack an eligible compiler for building LLVM or the oneAPI
compiler while keeping unrestricted cross-stack reuse disabled. MPICH's
Fortran bindings are enabled because SuperLU_DIST builds its
Fortran interface against `mpif.h`; compiler mixing remains disabled. PETSc and
Hypre themselves remain `~fortran`. Spack installs no Python application
packages. Pip installs the packages in `python-requirements.txt` once in the
shared environment. It also installs `documentation-requirements.txt` by
default for Sphinx documentation and notebook tutorials. Each stack has a small
virtual environment where pip builds `mpi4py` from source with that stack's
`mpicc`; a `.pth` file makes the shared packages available there. CUDA and ROCm
are excluded. Clang optionally includes X86 and NVPTX. oneAPI selects oneMKL
for PETSc.

GCC build environments override inherited GCC externals with an empty list.
This prevents a compiler discovered from a previously generated module or view
from replacing the internally built GCC root during forced reconcretization.
Clang and oneAPI environments retain their explicit GCC external entry.

Python, CMake, and GNU Make are installed once in the common Spack view and
registered as non-buildable externals in every compiler environment. They are
tooling rather than ABI-bearing OpenSn libraries, so rebuilding them for each
compiler would consume space without increasing compiler coverage. Libraries
linked into OpenSn remain compiler-specific.

Doxygen and Pandoc are installed once in independent Spack environments. Their
modulefiles do not select a compiler or MPI stack, so the tools can be loaded
with any OpenSn development stack and upgraded independently.

The public module preloads the selected GCC toolchain's ``libstdc++``. Binary
Python packages in the shared environment can contain an RPATH to the older
compiler runtime used to build their wheels. Without the preload, importing one
of those packages before a newer-compiler ``pyopensn`` module can select an old
``libstdc++`` that lacks the required ``GLIBCXX`` symbols. The newer GCC runtime
is backward compatible with those shared Python packages and is also the C++
runtime selected by the GCC bootstrap toolchain for Clang and oneAPI stacks.

VTK's OpenGL dependency brings in Mesa. Mesa is constrained to `~llvm` because
OpenSn uses VTK for data structures and file I/O, not Mesa's LLVM-based software
rasterizer. This also prevents Spack from selecting ROCm's `llvm-amdgpu` as a
provider of Mesa's virtual `libllvm` dependency in an otherwise CPU-only stack.
The local scnlib overlay disables its separate build-time and binary-size
benchmark targets. They are not installed, and scnlib 4.0.1 otherwise enables
them by default even when its main runtime benchmark option is disabled.

The generated environments do not contain the `opensn` or `opensn-develop`
Spack packages. Instead, the packages named in `dependencies` are independent
roots of the stack group. Consequently, installation does not require an
OpenSn package recipe or source checkout. Spack still resolves and versions
incidental transitive build dependencies that are not part of the documented
OpenSn/PETSc interface.

Documentation packages are installed by default. Set `"docs": false` only for
a reduced installation that does not need to build the manuals or execute the
notebook tutorials.

## Use

Users need only Environment Modules or Lmod:

```sh
module use /opt/local/modules
module load gcc/16.2.0
module load doxygen/1.17.0 pandoc/3.7.0.2
cmake -S . -B build-gcc -DOPENSN_WITH_PYTHON_MODULE=ON \
  -DPython3_EXECUTABLE="$Python3_EXECUTABLE"
cmake --build build-gcc -j4
build-gcc/test/opensn-unit
test/run_tests -d test/python --exe "$PWD/build-gcc/python/opensn" -j4 -v1 -w3
```

Use a separate OpenSn build directory for every module. The module selects the
stack virtual environment and its matching `mpi4py`; users never run Spack or
activate a Python or Spack environment.

## Validation and limits

```sh
python3 -m unittest discover -s . -p 'test_*.py' -v
flake8 install.py test_install.py
```

Offline tests cover configuration, Bash syntax, stack isolation, shared Python,
and Tcl parsing. Full concretization and source builds require the target Linux
system.
