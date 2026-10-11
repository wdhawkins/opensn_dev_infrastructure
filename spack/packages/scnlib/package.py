# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

from spack_repo.builtin.packages.scnlib.package import Scnlib as BuiltinScnlib


class Scnlib(BuiltinScnlib):
    """Disable auxiliary benchmarks omitted by the pinned builtin recipe."""

    def cmake_args(self):
        return super().cmake_args() + [
            self.define("SCN_BENCHMARKS_BUILDTIME", False),
            self.define("SCN_BENCHMARKS_BINARYSIZE", False),
        ]
