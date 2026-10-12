# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

from spack_repo.builtin.packages.llvm_amdgpu.package import LlvmAmdgpu as BuiltinLlvmAmdgpu

from spack.package import *


class LlvmAmdgpu(BuiltinLlvmAmdgpu):
    """Build AMD's LLVM without libquadmath, which only GCC's Fortran support provides.

    The builtin recipe sets FLANG_RUNTIME_F128_MATH_LIB=libquadmath for ROCm 7 and later, so
    flang-rt requires quadmath.h. Leaving it unset uses flang-rt's default: no libquadmath
    wrapper for REAL(16) math. HIP does not use Flang.
    """

    def cmake_args(self):
        return [
            arg
            for arg in super().cmake_args()
            if not arg.startswith("-DFLANG_RUNTIME_F128_MATH_LIB")
        ]
