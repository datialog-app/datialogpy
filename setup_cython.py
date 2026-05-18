from setuptools import setup
from Cython.Build import cythonize

setup(
    ext_modules=cythonize(
        [
            "datialog/server.py",
            "datialog/license_manager.py",
        ],
        compiler_directives={"language_level": "3"},
        annotate=False,
    )
)
