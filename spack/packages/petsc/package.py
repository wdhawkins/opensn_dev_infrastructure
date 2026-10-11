# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

import functools

from spack_repo.builtin.packages.petsc.package import Petsc as BuiltinPetsc

from spack.package import *


class Petsc(BuiltinPetsc):
    """Allow SuperLU_DIST without Fortran; the builtin recipe defines it only when +fortran."""

    variant(
        "superlu-dist",
        default=False,
        description="Activates support for superlu-dist (only parallel)",
    )
    depends_on("fortran", type="build", when="+fortran")


def _is_unconditional_fortran(directive):
    if not isinstance(directive, functools.partial):
        raise TypeError("petsc overlay: unexpected Spack depends_on directive layout")
    return directive.keywords.get("spec") == "fortran" and directive.keywords.get("when") is None


# The builtin recipe declares depends_on("fortran", type="build") unconditionally, although
# ~fortran configures with --with-fc=0. Directives cannot be removed by a subclass, so drop it
# from this class's own directive queue.
Petsc._directives_to_be_executed["depends_on"] = [
    directive
    for directive in Petsc._directives_to_be_executed["depends_on"]
    if not _is_unconditional_fortran(directive)
]
