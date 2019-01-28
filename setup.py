#!/usr/bin/env python
# -*- coding: utf-8 -*-
from setuptools import setup, find_packages


if __name__ == "__main__":
    # poission boltzmann solver
    setup(name='pbe_solver',
          packages=find_packages(),
          version="0.1",
          license='MIT',
          description=('Numerical solver for the generalized Poisson–Boltzmann equation'),
          author="Amanuel Wolde-Kidan",
          author_email="amanuel.wolde-kidan@fu-berlin.de",
          include_package_data=True,
          zip_safe=False,
          requires=['numpy (>=1.10.4)', 'numba (>=0.37.0)', 'matplotlib (>=2.2.2)', 'scipy (>=1.0.1)'],
          install_requires=['numpy>=1.10.4', 'numba>=0.37.0', 'matplotlib>=2.2.2', 'scipy>=1.0.1'],
          entry_points={'console_scripts': ['pbe_solver=pbe_solver.pbe_solver:main', ],},)
