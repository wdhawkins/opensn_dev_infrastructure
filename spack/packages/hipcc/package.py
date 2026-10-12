# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

import functools

from spack_repo.builtin.packages.hipcc.package import Hipcc as BuiltinHipcc

from spack.package import *


class Hipcc(BuiltinHipcc):
    """Build the HIP compiler driver without a Fortran compiler; it contains no Fortran."""


def _is_unconditional_fortran(directive):
    if not isinstance(directive, functools.partial):
        raise TypeError("hipcc overlay: unexpected Spack depends_on directive layout")
    return directive.keywords.get("spec") == "fortran" and directive.keywords.get("when") is None


# The builtin recipe declares a generated depends_on("fortran", type="build") unconditionally.
# Directives cannot be removed by a subclass, so drop it from this class's own directive queue.
Hipcc._directives_to_be_executed["depends_on"] = [
    directive
    for directive in Hipcc._directives_to_be_executed["depends_on"]
    if not _is_unconditional_fortran(directive)
]
