# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

import functools

from spack_repo.builtin.packages.superlu_dist.package import SuperluDist as BuiltinSuperluDist

from spack.package import *


class SuperluDist(BuiltinSuperluDist):
    """Make the optional Fortran interface a variant; the builtin recipe always builds it."""

    variant("fortran", default=False, description="Build the Fortran interface")
    depends_on("fortran", type="build", when="+fortran")

    def cmake_args(self):
        return super().cmake_args() + [self.define_from_variant("XSDK_ENABLE_Fortran", "fortran")]


def _is_unconditional_fortran(directive):
    if not isinstance(directive, functools.partial):
        raise TypeError("superlu-dist overlay: unexpected Spack depends_on directive layout")
    return directive.keywords.get("spec") == "fortran" and directive.keywords.get("when") is None


# The builtin recipe declares depends_on("fortran", type="build") unconditionally. Directives
# cannot be removed by a subclass, so drop it from this class's own directive queue.
SuperluDist._directives_to_be_executed["depends_on"] = [
    directive
    for directive in SuperluDist._directives_to_be_executed["depends_on"]
    if not _is_unconditional_fortran(directive)
]
