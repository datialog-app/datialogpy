"""
Setup for building platform-specific wheel with compiled .pyd files.
Author: Ivan Pastor Sanz · CC BY-NC 4.0
"""
import sys
import glob
import shutil
import os
from setuptools import setup
from setuptools.dist import Distribution


class BinaryDistribution(Distribution):
    def has_ext_modules(self):
        return True
    def is_pure(self):
        return False


# Read version
import re
with open("pyproject.toml") as f:
    version_match = re.search(r'version = "([^"]+)"', f.read())
    version = version_match.group(1) if version_match else "1.3.2"

# Collect all compiled files
pyd_files = glob.glob("datialog/*.pyd") + glob.glob("datialog/*.so")
print(f"[setup_wheel] Found compiled files: {pyd_files}", flush=True)

if not pyd_files:
    print("[setup_wheel] ERROR: No .pyd or .so files found!", flush=True)
    sys.exit(1)

# Collect static files
static_files = []
for root, dirs, files in os.walk("datialog/static"):
    for f in files:
        static_files.append(os.path.join(root, f).replace("datialog/", "").replace("datialog\\", ""))

print(f"[setup_wheel] Static files: {static_files}", flush=True)

setup(
    name="datialog",
    version=version,
    author="Ivan Pastor Sanz",
    author_email="licencias@datialog.app",
    description="Natural AI Data Explorer — analyze datasets in plain language, locally and privately",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    url="https://datialog.app",
    packages=["datialog"],
    package_dir={"datialog": "datialog"},
    package_data={
        "datialog": [
            "*.pyd",
            "*.so",
            "static/*",
            "static/**/*",
        ]
    },
    data_files=[
        ("datialog", pyd_files),
    ],
    include_package_data=True,
    distclass=BinaryDistribution,
    entry_points={
        "console_scripts": [
            "datialog=datialog.cli:main",
        ]
    },
    install_requires=[
        "fastapi>=0.110.0",
        "uvicorn[standard]>=0.29.0",
        "pandas>=2.0.0",
        "numpy>=1.24.0",
        "matplotlib>=3.7.0",
        "seaborn>=0.12.0",
        "plotly>=5.18.0",
        "openpyxl>=3.1.0",
        "pyarrow>=14.0.0",
        "requests>=2.31.0",
        "python-multipart>=0.0.9",
        "pystray>=0.19.5",
        "Pillow>=10.0.0",
        "psutil>=5.9.0",
    ],
    python_requires=">=3.10",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: Other/Proprietary License",
        "Operating System :: Microsoft :: Windows",
        "Topic :: Scientific/Engineering :: Information Analysis",
    ],
)
