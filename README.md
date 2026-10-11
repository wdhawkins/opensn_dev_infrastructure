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
compiler, `flock`, normal build tools, network access, and writable `root` and
`work` directories. It never invokes an OS package manager or sudo. Spack stages
builds in `work/spack-stage` rather than the shared `/tmp/$USER/spack-stage`,
and a lock in `root/.spack` makes a second concurrent run against the same
`root` exit immediately instead of interleaving builds with the first. Intel's
offline installers clean up files under `/tmp/$USER`, including other packages'
Spack stages, so each stack installs `intel-oneapi-compilers` (oneAPI only) and,
on x86_64, `intel-oneapi-mkl` on their own before building the rest.

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
a GCC or different-Clang stack. The stacks contain no Fortran: GCC is built
with only C and C++, LLVM is built without Flang, and the modules set no `FC`,
`F77`, or `MPIFC`. The oneAPI compiler package always installs ifx, but no stack
package uses it. The oneAPI module uses Intel's installed ``compiler/latest/bin`` entry
point, while GCC and LLVM expose their drivers directly in the view's ``bin``
directory. Clang and oneAPI environments contain an additional bootstrap group for
their selected GCC toolchain. The already installed GCC view is registered in
those manifests as an external compiler with explicit C and C++ paths. This gives Spack an eligible compiler for building LLVM or the oneAPI
compiler while keeping unrestricted cross-stack reuse disabled; compiler
mixing remains disabled. MPICH, PETSc, Hypre, SuperLU_DIST, and Scotch are built
`~fortran`. The `opensn_toolchains`
repository subclasses two builtin recipes so they follow the pinned
`packages_ref`: `petsc` defines `superlu-dist` without the builtin `+fortran`
condition, and `superlu-dist` adds a `fortran` variant (default off) that sets
`XSDK_ENABLE_Fortran` instead of always building the Fortran interface. Both
overlays also make the builtin recipes' unconditional Fortran build dependency
conditional on `+fortran`. Spack
installs no Python application
packages. Pip installs the packages in `python-requirements.txt` once in the
shared environment. It also installs `documentation-requirements.txt` by
default for Sphinx documentation and notebook tutorials. Each stack has a small
virtual environment where pip builds `mpi4py` from source with that stack's
`mpicc`; a `.pth` file makes the shared packages available there. CUDA and ROCm
are excluded. Clang optionally includes X86 and NVPTX. Each stack manifest
requires PETSc, Hypre, and SuperLU_DIST to use oneMKL or OpenBLAS for BLAS and
LAPACK, and requires oneMKL on x86_64 targets (sequential, LP64, no Fortran
interface layer). oneMKL exists only for x86_64 Linux, so other architectures
use `openblas~fortran`, which builds an f2c-converted LAPACK.

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

## Maintenance

### Running the private Spack

Maintainers sometimes need to inspect or rebuild a stack by hand. Always use the
installer's private Spack and configuration; a `spack` found on `PATH` has a
different configuration and fails with `Unknown namespace: opensn_toolchains`.
For `root=/opt/local`:

```sh
export SPACK_USER_CONFIG_PATH=/opt/local/.spack/config
export SPACK_USER_CACHE_PATH=/opt/local/.spack/cache
spack=/opt/local/.spack/spack/bin/spack
"$spack" --version
```

The environments are under `/opt/local/.spack/environments`:
`FAMILY-X.Y.Z-mpich-M.Y.Z` for each stack, `python-P.Y.Z` for the shared
Python environment, and `doxygen-X.Y.Z` and `pandoc-X.Y.Z` for the tools.

```sh
env=/opt/local/.spack/environments/gcc-16.2.0-mpich-5.0.2
"$spack" -e "$env" find              # installed root specs
"$spack" -e "$env" find -c           # concretized but not yet installed
"$spack" -e "$env" install -p 1 PKG  # rebuild one package without parallel builds
```

The generated script rewrites these manifests, so change the JSON
configuration and regenerate the script rather than editing a `spack.yaml`.

### Changing a package version

1. List the versions that the pinned recipe knows about. `--safe` shows only
   checksummed versions, which are the only ones the installer can use:

   ```sh
   "$spack" versions --safe petsc
   "$spack" info petsc                  # also shows variants and dependencies
   ```

   Without an existing installation, read the recipe at the pinned commit
   instead:
   `https://github.com/spack/spack-packages/blob/PACKAGES_REF/repos/spack_repo/builtin/packages/NAME/package.py`.
   Recipe directories use underscores (`superlu_dist`), while specs and JSON
   keys use the package name (`superlu-dist`).
2. Set the new version in your configuration file. Keys in `dependencies` are
   Spack package names. Python and MPICH are top-level keys (`python`, `mpich`,
   or a per-compiler `mpich`), and compilers are entries in `compilers`. A
   `latest-3` GCC or Clang entry follows `spack.packages_ref` automatically;
   other compiler versions are exact.
3. Regenerate the script and run it again:

   ```sh
   python3 install.py /tmp/opensn-toolchains.json \
     --output /tmp/install-opensn-toolchains.sh
   bash /tmp/install-opensn-toolchains.sh
   ```

   Each stack is reconcretized. Packages whose specs are unchanged are reused
   from the store; the changed package and everything that depends on it are
   rebuilt, and the views are regenerated. Earlier builds remain in the private
   store.

To change a project default rather than only your own configuration, update the
value in both `DEPENDENCIES` in `install.py` and `example.json`, then run the
tests. A version that the pinned recipe does not know about requires either a
newer `spack.packages_ref` (below) or a `version(...)` entry in a subclass under
`spack/packages`, following the existing overlays.

### Changing the Spack version

`spack.ref` must be a Spack release tag or branch, such as `v1.2.2`, because the
installer clones it with `git clone --depth 1 --branch`. The installer clones
Spack only when `root/.spack/spack` does not exist yet, so changing `spack.ref`
does not update an existing root. Update the checkout yourself, then regenerate
and run the script:

```sh
git -C /opt/local/.spack/spack fetch --depth 1 origin tag v1.2.3
git -C /opt/local/.spack/spack checkout v1.2.3
```

Removing `root/.spack/spack` also works: the package store, environments, and
configuration live in sibling directories, so the next run clones the new
release and reuses installed packages whose specs are unchanged. A new Spack release must
support the package API of the pinned spack-packages commit; `"$spack" repo
list` shows the builtin repository's API version, which must lie in the range
the Spack release supports. Read the release notes for configuration
changes, such as the installer or concretizer options this project relies on.

### Changing the spack-packages commit

`spack.packages_ref` is a full commit hash from
`https://github.com/spack/spack-packages`. Each run moves the builtin repository
to exactly that commit with `spack repo update --commit`, and `latest-3`
compiler entries are resolved against the same commit when the script is
generated. To update it:

1. Choose a commit, normally the head of `develop` or a release branch such as
   `releases/v2026.06`. It must be compatible with `spack.ref`.
2. Check that every version in `dependencies` and the selected compiler versions
   still exist in the new recipes, using `"$spack" versions --safe NAME` after
   the update or the recipe links above.
3. Review the local overlays under `spack/packages`. They subclass the builtin
   recipes, so they follow upstream automatically, but each one exists to work
   around a specific upstream behavior:
   - `petsc` makes `superlu-dist` available without `+fortran`.
   - `superlu-dist` makes its Fortran interface optional.
   - `scnlib` disables two benchmark targets.

   If upstream has fixed one of these, delete that overlay. The `petsc` and
   `superlu-dist` overlays also remove an inherited unconditional `fortran`
   build dependency through Spack internals; if those internals change, Spack
   reports a `TypeError` from the overlay when it loads the recipe.
   `"$spack" info petsc` and `"$spack" info superlu-dist` load both overlays.
4. Set the new hash in your configuration (and in `DEFAULT_PACKAGES_REF` and
   `example.json` for a project default), regenerate, and run the script.
   Packages whose recipes changed, and everything that depends on them, are
   rebuilt.

## Validation and limits

```sh
python3 -m unittest discover -s . -p 'test_*.py' -v
flake8 install.py test_install.py
```

Offline tests cover configuration, Bash syntax, stack isolation, shared Python,
and Tcl parsing. Full concretization and source builds require the target Linux
system.
