import os
import shutil

from setuptools import Extension, Distribution
import numpy
from Cython.Build import cythonize
from Cython.Distutils.build_ext import new_build_ext as cython_build_ext


def build() -> None:
    # if running in RTD, skip compilation
    if os.environ.get("READTHEDOCS") == "True":
        return

    extensions = [
        Extension(
            'pyobs_qhyccd.qhyccddriver',
            ['pyobs_qhyccd/qhyccddriver.pyx'],
            library_dirs=['lib/usr/local/lib/'],
            libraries=['qhyccd', 'cfitsio'],
            include_dirs=[numpy.get_include()],
            extra_compile_args=['-fPIC']
        )
    ]
    ext_modules = cythonize(extensions)

    distribution = Distribution(
        {
            "name": "extended",
            "ext_modules": ext_modules,
            "cmdclass": {
                "build_ext": cython_build_ext,
            },
        }
    )

    distribution.run_command("build_ext")

    # copy to source
    build_ext_cmd = distribution.get_command_obj("build_ext")
    for ext in build_ext_cmd.extensions:
        filename = build_ext_cmd.get_ext_filename(ext.name)
        shutil.copyfile(os.path.join(build_ext_cmd.build_lib, filename), filename)


if __name__ == "__main__":
    build()
