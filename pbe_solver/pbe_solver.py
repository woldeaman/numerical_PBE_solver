# -*- coding: utf-8 -*-
import argparse as ap
import os
import scipy.constants as sc
import numpy as np
import matplotlib.pyplot as plt
from numba import jit
import timeit


###########################
#       FUNCTIONS        #
##########################################################################
def parse_command_line():
    parser = ap.ArgumentParser(description=(
        """
        Script numerically solves half space of symmetric PBE between two charged
        plates with a salt ionic solution. One sided variable dielectric profile,
        PMFs for the anions and cations, as well as additional charge distributions
        can be specified and will be symmetrized."""), formatter_class=ap.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-D', dest='distance', type=float, default=1,
                        help='plate separation [in nm]')
    parser.add_argument('-b', dest='bins', type=float, default=100,
                        help='number of bins used for numerical solution, '
                        'should match length of supplied profiles')
    parser.add_argument('-sig', dest='sigma', type=float, default=0,
                        help='surface charge on the walls [in e/nm^2]')
    parser.add_argument('-z', dest='valency', type=int, default=[1], nargs='*',
                        help='valency of the ions\nif a list is supplied, first argument is cation valency')
    parser.add_argument('-c', dest='c_0', type=float, default=1,
                        help='bulk concentration of the ionic solution [in mol/l]')
    parser.add_argument('-c_imp', dest='c_imp', type=float, default=0,
                        help='concentration of impurities [in nmol/l]')
    parser.add_argument('-T', dest='temp', type=float, default=300,
                        help='system temperatur [in K]')
    # NOTE: epsilon cannot be actually zero because of division by zero...
    parser.add_argument('-eps', dest='epsilon', type=str, default=1/80,
                        help='supply file containing inverse dielectric profile, '
                        'if a number is supplied, this will set the value in the entire domain')
    parser.add_argument('-rho', dest='rho', type=str, default=None,
                        help='supply file containing charge density [in e/m^3]')
    parser.add_argument('-pmf_+', dest='pmf_cat', type=str, default=None,
                        help='supply file for cation PMF [in kT]')
    parser.add_argument('-pmf_-', dest='pmf_an', type=str, default=None,
                        help='supply file for anion PMF [in kT]')
    # NOTE: impurities are always monovalent
    parser.add_argument('-pmf_imp_-', dest='pmf_imp_an', type=str, default=None,
                        help='supply file for PMF for impurities [in kT]')
    parser.add_argument('-pmf_imp_+', dest='pmf_imp_cat', type=str, default=None,
                        help='supply file for PMF for impurity counter ions [in kT]')
    parser.add_argument('-out', dest='path_out', type=str, default='current directory',
                        help='set directory to store computed data in')
    parser.add_argument('-v', dest='verbose', action='store_true',
                        help='verbose mode, norm of residual will be printed to screen')

    # get command line arguments
    args = parser.parse_args()
    verb = args.verbose  # setting verbose mode if wanted

    if args.path_out in 'current directory':  # determine save path
        path_out = os.getcwd()
    else:
        path_out = args.path_out

    # setting up environment
    N = int(args.bins)  # number of discretization bins
    zz = np.linspace(0, args.distance/2, N)  # computing z-vector

    # gather supplied profiles for epsilon, rho & pmfs
    profiles = []  # storing profiles
    files = [args.epsilon, args.rho, args.pmf_cat, args.pmf_an, args.pmf_imp_cat, args.pmf_imp_an]  # supplied paths to files
    defaults = [1, 0, 0, 0, 0, 0]  # default values in domain if no data is supplied
    for path, default in zip(files, defaults):
        if path is not None:
            try:  # see if argument is a constant value
                const = float(path)
                dat = np.ones(N)*const  # if so, set constant profiles
            except ValueError:
                dat = np.loadtxt(path, comments=['#', '@'])  # else read profiles
                assert dat.size == N, ('ERROR: Supplied profile does not have '
                                       'the same length as discretization vector!\n%s'
                                       % path)
        else:  # if nothing supplied set profiles to defaults
            dat = np.ones(N)*default
        profiles.append(dat)
    # save loaded profiles
    eps, rho, pmf_cat, pmf_an, pmf_imp_cat, pmf_imp_an = profiles[0], profiles[1], profiles[2], profiles[3], profiles[4], profiles[5]
    # set valencies for cation and anion seperately
    assert len(args.valency) <= 2, ('ERROR: List for ion valencies can only have two entries [val_cation, val_anion]!')
    val_cat, val_an = [args.valency[0]]*2 if len(args.valency) == 1 else args.valency

    return (path_out, verb, N, zz, eps, rho, pmf_cat, pmf_an, pmf_imp_cat, pmf_imp_an, args.sigma,
            args.temp, args.distance, val_cat, val_an, args.c_0, args.c_imp)


def convert_units(bins, temp, dist, sig, rho, valency, c_0, c_imp):
    """
    Convert physical variables to dimensionless variables to solve PBE with.
    """

    # now make unit conversion
    beta = 1/(sc.Boltzmann*temp)  # thermodynamic beta
    nm_to_m = 1E-9
    c_0 = sc.Avogadro*c_0*1E3  # bulk concentration in particles per m^3
    c_imp = sc.Avogadro*c_imp*1E-6/(c_0*valency)  # relative impurity concentration
    sigma = sig*sc.elementary_charge/(nm_to_m**2)  # surface charge in SI
    rho = rho*sc.elementary_charge/(nm_to_m**3)  # external charge density in SI

    # compute rescaled variables
    kappa = (sc.elementary_charge * valency *  # modified debye length
             np.sqrt(beta*c_0/sc.epsilon_0))  # actual l_b would be sqrt(2/eps)*kappa
    zz_hat = np.linspace(0, dist/2, bins)*nm_to_m*kappa  # rescaled z-distance
    dz_hat = abs(zz_hat[0]-zz_hat[1])  # rescaled discretization width
    sigma_hat = sigma*np.sqrt(beta)/np.sqrt(sc.epsilon_0*c_0)  # rescaled surface charge
    rho_hat = rho/(sc.elementary_charge*c_0*valency)  # rescaled charge density

    return (zz_hat, kappa, c_0, c_imp, beta, dz_hat, sigma_hat, rho_hat)


@jit(nopython=True)  # iterative loop compiled by numba
def iteration_loop(psi_start, omega, dz_hat, val_cat, val_an, sigma_hat, rho_hat,
                   eps, pmf_cat, pmf_an, pmf_imp_cat, pmf_imp_an, c_imp, tol=1E-10):
    # setting start values
    psi = psi_start
    N = psi.size  # gather number of discretization bins
    psi_prev = np.zeros(N)
    for i in range(N):  # copy values for previous solution intially
        psi_prev[i] = psi_start[i]
    rel_err = tol + 1  # initially error is larger than tolerance

    while rel_err > tol:  # iterate until convergence
        # start with value at left boundary, using neumann BCs
        rho_imp_0 = c_imp*(np.exp(-psi[0]-pmf_imp_cat[0]) - np.exp(psi[0]-pmf_imp_an[0]))
        rho_0 = (np.exp(-val_cat*psi[0]-pmf_cat[0]) - np.exp(val_an*psi[0]-pmf_an[0]) +
                 rho_hat[0] + rho_imp_0)
        psi_0 = (psi[1] +  # constant field due to surface charge bc
                 2*dz_hat*sigma_hat * (eps[1] + 3*eps[0])/8 +
                 rho_0 * (dz_hat**2)*eps[0]/2)
        psi[0] = (1 - omega)*psi_prev[0] + omega*psi_0  # over relaxation

        # now compute internal values inside domain
        for i in range(1, N-1):
            rho_imp_i = c_imp*(np.exp(-psi[i]-pmf_imp_cat[i]) - np.exp(psi[i]-pmf_imp_an[i]))  # charge density due to impurities
            rho_i = (np.exp(-val_cat*psi[i]-pmf_cat[i]) - np.exp(val_an*psi[i]-pmf_an[i]) +
                     rho_hat[i] + rho_imp_i)  # ion charge distribution + extra charges
            psi_i = (psi[i+1]*(-eps[i+1] + 4*eps[i] + eps[i-1])/(8*eps[i]) +
                     psi[i-1]*(eps[i+1] + 4*eps[i] - eps[i-1])/(8*eps[i]) +
                     rho_i * (dz_hat**2)*eps[i]/2)
            psi[i] = (1 - omega)*psi_prev[i] + omega*psi_i

        # now compute value at right boundary
        rho_imp_N = c_imp*(np.exp(-psi[-1]-pmf_imp_cat[-1]) - np.exp(psi[-1]-pmf_imp_an[-1]))
        rho_N = (np.exp(-val_cat*psi[-1]-pmf_cat[-1]) - np.exp(val_an*psi[-1]-pmf_an[-1]) +
                 rho_hat[-1] + rho_imp_N)
        psi_N = (psi[-2] +  # no field in bulk bc
                 rho_N * (dz_hat**2)*eps[-1]/2)
        psi[-1] = (1 - omega)*psi_prev[-1] + omega*psi_N

        # TODO: maybe implement chebishev acceleration for omega ...

        # wrapping up loop iteration
        rel_err = 0  # compute averaged deviation from previous iteration
        for i in range(N):
            rel_err += (psi[i] - psi_prev[i])**2
        rel_err = np.sqrt(rel_err/(N-1))

        for i in range(N):  # store previous solution for next itreation
            psi_prev[i] = psi[i]

    return psi


def showData(zz, psi, pmf_cat, pmf_an, pmf_imp_cat, pmf_imp_an, val_max, c_0, c_imp, beta, val_cat, val_an, sigma_hat, plot=False):
    """
    Plots and prints computed data if in verbose mode.
    """
    # compute cation and anion bulk density
    c_cat, c_an = [c_0*val_max/val for val in [val_cat, val_an]]
    c_imp = c_imp*c_0*val_max
    # compute ion densities from potential and pmfs
    rho_ion_p = 1E-27*c_cat*np.exp(-val_cat*psi-pmf_cat)  # cation density in nm^-3
    rho_ion_n = 1E-27*c_an*np.exp(val_an*psi-pmf_an)  # anion density in nm^-3
    rho_imp_p = 1E-27*c_imp*np.exp(-psi-pmf_imp_cat)  # impurity cation density in nm^-3
    rho_imp_n = 1E-27*c_imp*np.exp(psi-pmf_imp_an)  # impurity anion density in nm^-3

    # convert psi to physical units [mV]
    psi_to_phi = 1E3/(sc.elementary_charge*beta*val_max)
    # symmetrize profiles
    symm_psi = psi_to_phi*np.concatenate((psi, psi[::-1]))
    symm_dens_p = np.concatenate((rho_ion_p, rho_ion_p[::-1]))
    symm_dens_n = np.concatenate((rho_ion_n, rho_ion_n[::-1]))
    symm_dens_imp_p = np.concatenate((rho_imp_p, rho_imp_p[::-1]))
    symm_dens_imp_n = np.concatenate((rho_imp_n, rho_imp_n[::-1]))
    symm_zz = np.concatenate((zz, zz+zz[-1]))
    # make and show plot
    if plot:
        make_plot(symm_zz, symm_psi, symm_dens_p, symm_dens_n)
        # see if ion charge density balances out surface charge
        sig = np.trapz(val_cat*rho_ion_p - val_an*rho_ion_n + rho_imp_p - rho_imp_n, zz)  # excess surface charge
        sigma_units = np.sqrt(sc.epsilon_0*c_0)/(sc.elementary_charge*1E18*np.sqrt(beta))
        print("Surface charge: %.5f e/nm^2" % (sigma_hat*sigma_units))
        print("Excess System charge: %.5f e/nm^2" % sig)

    return symm_zz, symm_psi, symm_dens_p, symm_dens_n, symm_dens_imp_p, symm_dens_imp_n


def make_plot(symm_zz, symm_psi, symm_dens_p, symm_dens_n):
    """Make plot of computed data."""
    # plot data, potential first
    plt.plot(symm_zz, symm_psi, 'k-')
    plt.xlabel('z-distance [nm]')
    plt.ylabel('Potential [mV]', color='k')
    plt.twinx()  # now plot density on opposite axis
    plt.ylabel('c [nm$^{-3}$]', color='b')
    plt.plot(symm_zz, symm_dens_n, 'b-', label='-')
    plt.plot(symm_zz, symm_dens_p, 'b--', label='+')
    plt.tick_params('y', colors='b')
    plt.legend(frameon=False)
    plt.tight_layout()
    plt.show()


def saveData(symm_zz, symm_psi, symm_dens_p, symm_dens_n, symm_imp_p, symm_imp_n, c_0, c_imp, kappa, path_out):
    """
    Saves computed data to supplied path.
    """
    head_dens = (("density for bulk concentration c_0 = %.2f mol/l\n"
                  % (1E-3*c_0/sc.Avogadro)) +
                 "col 1: z-distance [nm]\ncol 2: density [1/nm^3]\n")
    head_imp = (("impurity density for concentration c_imp = %.2f nmol/l\n"
                 % (1E6*c_imp*c_0/sc.Avogadro)) +
                "col 1: z-distance [nm]\ncol 2: density [1/nm^3]\n")
    head_psi = (("electrostatic potential for l_debye = %.2f nm\n" % (1E9/kappa)) +
                "col 1: z-distance [nm]\ncol 2: potential [mV]\n")

    np.savetxt(path_out+'/dens_pos.txt', np.c_[symm_zz, symm_dens_p],
               header='cation '+head_dens)
    np.savetxt(path_out+'/dens_neg.txt', np.c_[symm_zz, symm_dens_n],
               header='anion '+head_dens)
    np.savetxt(path_out+'/imp_pos.txt', np.c_[symm_zz, symm_imp_p],
               header='cation '+head_imp)
    np.savetxt(path_out+'/imp_neg.txt', np.c_[symm_zz, symm_imp_n],
               header='anion '+head_imp)
    np.savetxt(path_out+'/psi.txt', np.c_[symm_zz, symm_psi], header=head_psi)
##########################################################################


#####################
#       MAIN        #
##########################################################################
def main():
    # read from command line
    (path_out, verb, bins, zz, eps, rho, pmf_cat, pmf_an, pmf_imp_cat, pmf_imp_an, sigma,
     temp, distance, val_cat, val_an, c_0_pre, c_imp_pre) = parse_command_line()
    # largest valency is used for normalization
    val_max = np.max([val_cat, val_an])
    # convert units
    (zz_hat, kappa, c_0, c_imp, beta, dz_hat, sigma_hat, rho_hat) = convert_units(
        bins, temp, distance, sigma, rho, val_max, c_0_pre, c_imp_pre)

    # compute gouy chapman solution to start with
    eps_avg = 1/np.average(eps)  # average epsilon
    psi_start = (sigma_hat/eps_avg)*np.exp(-(zz_hat))  # gouy chapman solution
    # TODO: implement correct formula, probably also depends on eps, pmfs, rho ...
    omega = 2/(1 + np.sqrt(np.pi/bins))  # omega parameter for SOR

    # call iteration procedure
    psi = iteration_loop(psi_start, omega, dz_hat, val_cat, val_an,
                         sigma_hat, rho_hat, eps, pmf_cat, pmf_an, pmf_imp_cat, pmf_imp_an, c_imp)
    (symm_zz, symm_psi,  # compute physical data and plot if in verbos mode
     symm_dens_p, symm_dens_n, symm_imp_p, symm_imp_n) = showData(zz, psi, pmf_cat, pmf_an, pmf_imp_cat, pmf_imp_an, val_max, c_0, c_imp, beta,
                                                                  val_cat, val_an, sigma_hat, plot=verb)

    # save computed potential and ion distributions
    saveData(symm_zz, symm_psi, symm_dens_p, symm_dens_n, symm_imp_p, symm_imp_n, c_0, c_imp*val_max, kappa, path_out)
    return verb


if __name__ == "__main__":
    start = timeit.default_timer()
    verbose = main()
    stop = timeit.default_timer()
    if verbose:
        print("Time: %.3f s" % (stop - start))
##########################################################################
