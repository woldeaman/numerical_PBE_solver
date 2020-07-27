# PBE Solver

A powerful solver for the generalized Poisson–Boltzmann equation in the form:
```math
  \frac{d\varphi}{dz}\frac{d\varepsilon^{-1}_\perp}{dz} - \varepsilon^{-1}_\perp(z)\frac{d^2\varphi}{dz^2} = \varepsilon_0^{-1}\varepsilon^{-2}_\perp(z)
  \left[\rho_{\text{ex}} + e c_0\left(z_+e^{-z_+e\beta\varphi-\beta PMF^{+}} - z_-e^{+z_-e\beta\varphi-\beta PMF^{-}} \right)\right]
```

# Installation

## Prerequisites

You'll need [Python3](https://www.python.org) with the [numba package](http://numba.pydata.org/) installed.

## Linux/MacOS

``python3 setup.py install``

