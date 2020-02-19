from setuptools import setup, Extension
import os
import numpy
from Cython.Build import cythonize

# define extension
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

# setup
setup(
    name='pyobs-qhyccd',
    version='0.8',
    description='pyobs component for QHYCCD cameras',
    packages=['pyobs_qhyccd'],
    ext_modules=cythonize(extensions),
    install_requires=[
        'cython',
        'numpy',
        'astropy'
    ]
)
