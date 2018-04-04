# -*- coding: utf-8 -*-
import argparse as ap
import sys
import scipy.constants as sc
import numpy as np
import matplotlib.pyplot as plt
from numba import jit
import timeit


#################################
#  PARSING COMMAND LINE INPUTS  #
##########################################################################
parser = ap.ArgumentParser(description=(
    """
    Script numerically solves half space of symmetric PBE between two charged
    plates, with 1:1 ionic solution. One sided variable dielectric profile,
    PMFs for the anions and cations, as well as additional charge distributions
    can be specified and will be symmetrized.
    """), formatter_class=ap.ArgumentDefaultsHelpFormatter)
parser.add_argument('-D', dest='distance', type=float, default=1,
                    help='plate separation [in nm]')
parser.add_argument('-b', dest='bins', type=float, default=100,
                    help='number of bins used for numerical solution, '
                    'should match length of supplied profiles')
parser.add_argument('-sig', dest='sigma', type=float, default=0,
                    help='surface charge on the walls [in e/nm^2]')
parser.add_argument('-z', dest='valency', type=int, default=1,
                    help='valency of the ions')
parser.add_argument('-c', dest='c_0', type=float, default=1,
                    help='bulk concentration of the ionic solution [in mol/l]')
parser.add_argument('-T', dest='temp', type=float, default=300,
                    help='system temperatur [in K]')
parser.add_argument('-eps', dest='epsilon', type=str, default=80,
                    help='supply file containing dielectric profile, '
                    'if a number is supplied, this will set epsilon in entire domain')
parser.add_argument('-rho', dest='rho', type=str, default=None,
                    help='supply file containing charge density [in e/m^3]')
parser.add_argument('-pmf_+', dest='pmf_cat', type=str, default=None,
                    help='supply file for cation PMF [in kT]')
parser.add_argument('-pmf_-', dest='pmf_an', type=str, default=None,
                    help='supply file for anion PMF [in kT]')
parser.add_argument('-out', dest='path_out', type=str, default='Desktop',
                    help='set directory to store computed data in')
parser.add_argument('-v', dest='verbose', action='store_true',
                    help='verbose mode, norm of residual will be printed to screen')

# get command line arguments
args = parser.parse_args()
verb = args.verbose  # setting verbose mode if wanted

# detecting home directory on system
if sys.platform == "darwin":  # folder for mac
    home = '/Users/woldeaman/'
elif sys.platform.startswith("linux"):  # folder for linux
    home = '/home/amanuelwk/'
if args.path_out is 'Desktop':  # determine save path
    path_out = home+'/Desktop'
else:
    path_out = args.path_out
##########################################################################

################################
#    SETTING UP ENVIRONMENT    #
##########################################################################
# discretization setup
N = int(args.bins)  # number of discretization bins
zz = np.linspace(0, args.distance/2, N)  # bin vector [in nm], for half space

# gather supplied profiles for epsilon, rho & pmfs
profiles = []  # storing profiles
files = [args.epsilon, args.rho, args.pmf_cat, args.pmf_an]  # supplied paths to files
defaults = [1, 0, 0, 0]  # default values in domain if no data is supplied
for path, default in zip(files, defaults):
    if path is not None:
        try:  # see if argument is a constant value
            const = float(path)
            dat = np.ones(zz.size)*const  # if so, set constant profiles
        except ValueError:
            dat = np.loadtxt(path, comments=['#', '@'])  # else read profiles
            assert dat.size == zz.size, ('ERROR: Supplied profile does not have '
                                         'the same length as discretization vector!\n%s'
                                         % path)
    else:  # if nothing supplied set profiles to defaults
        dat = np.ones(zz.size)*default
    profiles.append(dat)
# save loaded profiles
eps, rho, pmf_cat, pmf_an = profiles[0], profiles[1], profiles[2], profiles[3]

# now make unit conversion
beta = 1/(sc.Boltzmann*args.temp)  # thermodynamic beta
nm_to_m = 1E-9
c_0 = sc.Avogadro*args.c_0*1E3  # bulk concentration in particles per m^3
sigma = args.sigma*sc.elementary_charge/(nm_to_m**2)  # surface charge in SI
rho = rho*sc.elementary_charge/(nm_to_m**3)  # external charge density in SI

# compute rescaled variables
kappa = (sc.elementary_charge*args.valency *  # modified debye length
         np.sqrt(beta*c_0/sc.epsilon_0))  # actual l_b would be sqrt(2/eps)*kappa
zz_hat = np.linspace(0, args.distance/2, N)*nm_to_m*kappa  # rescaled z-distance
dz_hat = abs(zz_hat[0]-zz_hat[1])  # rescaled discretization width
sigma_hat = sigma*np.sqrt(beta)/np.sqrt(sc.epsilon_0*c_0)  # rescaled surface charge
rho_hat = rho/(sc.elementary_charge*args.valency*c_0)  # rescaled surface charge
dpsi_bc = (2*dz_hat*sigma_hat)/eps[0]  # surface charge term for bc
##########################################################################


###########################
#       FUNCTIONS        #
##########################################################################
@jit(nopython=True)  # iterative loop ported to c by numba
def iteration_loop(psi_start, omega, tol=1E-10):
    # setting start values
    psi = psi_start
    # copy values for previous solution intially
    psi_prev = np.zeros(N)
    for i in range(N):
        psi_prev[i] = psi_start[i]
    rel_err = tol + 1  # initially error is larger than tolerance

    while rel_err > tol:  # iterate until convergence
        # start with value at left boundary, using neumann BCs
        rho_0 = (np.exp(-psi[0]-pmf_cat[0]) - np.exp(psi[0]-pmf_an[0]) +
                 rho_hat[0])
        psi_0 = (psi[1] +  # constant field due to surface charge bc
                 4*dz_hat*sigma_hat/(eps[1]+3*eps[0]) +
                 2*(dz_hat**2)*rho_0/(eps[1]+3*eps[0]))
        psi[0] = (1 - omega)*psi_prev[0] + omega*psi_0  # possible over relaxation

        # now compute internal values inside the domain
        for i in range(1, N-1):
            rho_i = (np.exp(-psi[i]-pmf_cat[i]) - np.exp(psi[i]-pmf_an[i]) +
                     rho_hat[i])  # ion charge distribution + extra charges
            psi_i = (psi[i+1]*(eps[i+1] + eps[i]) +
                     psi[i-1]*(eps[i-1] + eps[i]) +
                     2*(dz_hat**2)*rho_i) / (eps[i+1] + 2*eps[i] + eps[i-1])
            psi[i] = (1 - omega)*psi_prev[i] + omega*psi_i

        # now compute value at right boundary
        rho_N = (np.exp(-psi[-1]-pmf_cat[-1]) - np.exp(psi[-1]-pmf_an[-1]) +
                 rho_hat[-1])
        psi_N = (psi[-2] +  # no field in bulk bc
                 2*(dz_hat**2)*rho_N/(eps[-2]+3*eps[-1]))
        psi[-1] = (1 - omega)*psi_prev[-1] + omega*psi_N

        # TODO: maybe implement chebishev acceleration for omega ...

        # wrapping up loop iteration
        rel_err = 0  # compute averaged deviation from previous iteration
        for i in range(N):
            rel_err += abs(psi[i] - psi_prev[i])
        rel_err = rel_err/np.sqrt(N)
        if verb:  # if wanted residual norm will be printed
            print(rel_err)

        for i in range(N):  # store previous solution for next itreation
            psi_prev[i] = psi[i]

    return psi


def saveData(zz, psi):
    """
    Saves computed data to supplied path.
    """

    # compute ion densities from potential and pmfs
    dens_neg = 1E-27*c_0*np.exp(psi-pmf_an)  # anion density
    dens_pos = 1E-27*c_0*np.exp(-psi-pmf_cat)  # cation density
    # convert psi to physical units [mV]
    psi_to_phi = 1E3*sc.Boltzmann*args.temp/sc.elementary_charge*args.valency

    head_dens = (("density for bulk concentration c_0 = %.2f mol/l\n" % args.c_0) +
                 "col 1: z-distance [nm]\ncol 2: density [1/nm^3]\n")
    head_psi = (("electrostatic potential for l_debye = %.2f nm\n" % (1E9/kappa)) +
                "col 1: z-distance [nm]\ncol 2: potential [mV]\n")

    np.savetxt(path_out+'/dens_neg.txt', np.c_[zz, dens_neg],
               header='anion '+head_dens)
    np.savetxt(path_out+'/dens_pos.txt', np.c_[zz, dens_pos],
               header='cation '+head_dens)
    np.savetxt(path_out+'/psi.txt', np.c_[zz, psi*psi_to_phi], header=head_psi)


def showData(zz, psi):
    """
    Plots and prints computed data if in verbose mode.
    """

    # compute ion densities from potential and pmfs
    rho_ion_n = 1E-3*c_0*np.exp(psi-pmf_an)/sc.Avogadro  # anion density
    rho_ion_p = 1E-3*c_0*np.exp(-psi-pmf_cat)/sc.Avogadro  # cation density
    # see if this balances out surface charge
    dens_to_charge = sc.Avogadro*args.valency*1E-24
    sig = np.trapz(dens_to_charge*(rho_ion_p - rho_ion_n), zz)  # excess surface charge
    print("Surface charge: %.5f e/nm^2" % args.sigma)
    print("Excess System charge: %.5f e/nm^2" % sig)

    # convert psi to physical units [mV]
    psi_to_phi = 1E3*sc.Boltzmann*args.temp/sc.elementary_charge*args.valency
    # symmetrize profiles
    symm_psi = psi_to_phi*np.concatenate((psi, psi[::-1]))
    symm_dens_p = np.concatenate((rho_ion_p, rho_ion_p[::-1]))
    symm_dens_n = np.concatenate((rho_ion_n, rho_ion_n[::-1]))
    symm_zz = np.concatenate((zz, zz+zz[-1]))

    # plot data, potential first
    plt.plot(symm_zz, symm_psi, 'k-')
    plt.xlabel('z-distance [nm]')
    plt.ylabel('Potential [mV]', color='k')
    plt.twinx()  # now plot density on opposite axis
    plt.ylabel('Density [mol/l]', color='b')
    plt.plot(symm_zz, symm_dens_n, 'b-', label='-')
    plt.plot(symm_zz, symm_dens_p, 'b--', label='+')
    plt.tick_params('y', colors='b')
    plt.legend(frameon=False)
    plt.tight_layout()
    plt.show()
##########################################################################


#####################
#       MAIN        #
##########################################################################
def main():
    # compute gouy chapman solution to start with
    eps_avg = np.average(eps)  # average epsilon
    psi_start = (sigma_hat/eps_avg)*np.exp(-zz_hat)  # gouy chapman solution
    # TODO: implement correct formula, probably also depends on eps, pmfs, rho ...
    omega = 2/(1 + np.sqrt(np.pi/N))  # omega parameter for SOR

    # call iteration procedure
    psi = iteration_loop(psi_start, omega)
    if verb:  # plot and print data if in verbos mode
        showData(zz, psi)

    # save computed potential and ion distributions
    saveData(zz, psi)


if __name__ == "__main__":
    start = timeit.default_timer()
    main()
    stop = timeit.default_timer()
    print("Time: %.3f s" % (stop - start))
##########################################################################
