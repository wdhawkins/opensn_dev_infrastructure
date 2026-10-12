# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

import functools

from spack_repo.builtin.packages.comgr.package import Comgr as BuiltinComgr

from spack.package import *


class Comgr(BuiltinComgr):
    """Build AMD's code object manager without a Fortran compiler; it contains no Fortran."""


def _is_unconditional_fortran(directive):
    if not isinstance(directive, functools.partial):
        raise TypeError("comgr overlay: unexpected Spack depends_on directive layout")
    return directive.keywords.get("spec") == "fortran" and directive.keywords.get("when") is None


# The builtin recipe declares a generated depends_on("fortran", type="build") unconditionally.
# Directives cannot be removed by a subclass, so drop it from this class's own directive queue.
Comgr._directives_to_be_executed["depends_on"] = [
    directive
    for directive in Comgr._directives_to_be_executed["depends_on"]
    if not _is_unconditional_fortran(directive)
]
