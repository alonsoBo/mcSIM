"""
Tools for simulating diffraction from a digital micromirror device (DMD)

The simulate_dmd() function performs a brute force simulation function, but most useful information can be extracted
using more specialized tools also found here, such as simulate_dmd_dft(), find_combined_condition(),
or get_diffracted_output_uvec()

When simulating a periodic pattern such as used in Structured Illumination Microscopy (SIM), the tools found in
dmd_pattern.py may be more suitable.

# ###################
Coordinate systems
# ###################
We adopt a coordinate system with x- and y- axes along the primary axes of the DMD chip (i.e. determined
by the periodic mirror array), and z- direction is positive pointing away from the DMD face. This way the unit
vectors describing the direction of an incoming plane waves has negative z-component, and the unit vector of
an outgoing plane wave has positive z-component. We typically suppose the mirrors swivel about the axis
n = [1, 1, 0]/sqrt(2), i.e. diagonal to the DMD axes, by angle +/- gamma. This ensures that light incident in
the x-y (x minus y) plane stays in plane after diffraction (for the blazed order)

In addition to the xyz coordinate system, we also use two other convenient coordinate systems.
1. the mpz coordinate system:
This coordinate system is convenient for dealing with diffraction from the DMD, as discussed above. Note
that the mirrors swivel about the ep direction
em = (ex - ey) / sqrt(2); ep = (ex + ey) / sqrt(2)
2. the 123 or "mirror" coordinate system:
This coordinate system is specialized to dealing with the blaze condition. Here the unit vector e3 is the normal to the
DMD mirror, e2 is along the (x+y)/sqrt(2) direction, and e1 is orthogonal to these two. Since e3 is normal
to the DMD mirrors this coordinate system depends on the mirror swivel angle.

In whichever coordinate system, if we want to specify directions we have the choice of working with either
unit vectors or an angular parameterization. Typically unit vectors are easier to work with, although angles
may be easier to interpret. We use different angular parameterizations for incoming and outgoing unit vectors.
For example, in the xy coordinate system we use
a = az * [tan(tx_a), tan(ty_a), -1]
b = |bz| * [tan(tb_x), tan(tb_y), 1]

If light is incident towards the DMD as a plane wave from some direction determined by a unit vector, a, then it
is then diffracted into different output directions depending on the spatial frequencies of the DMD pattern.
Call these directions b(f).

If the DMD is tilted, the DMD pattern frequencies f will not exactly match the optical system frequencies.
In particular, although the DMD pattern will have components at f and -f the optical system frequencies will
not be perfectly centered on the optical axis.
"""
import os
import numpy as np
from numpy import fft
import pickle
import joblib
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.widgets
from matplotlib.colors import PowerNorm
from matplotlib.patches import Circle


# main simulation function and important auxiliary functions
def simulate_dmd(pattern, wavelength, gamma_on, gamma_off, dx, dy, wx, wy,
                 uvec_in, uvecs_out, zshifts=None):
    """
    Simulate plane wave diffracted from a digital mirror device (DMD) naively. In most cases this function is not
    the most efficient to use! When working with SIM patterns it is much more efficient to rely on the tools
    found in dmd_patterns

    We assume that the body of the device is in the xy plane with the negative z-unit vector defining the plane's
    normal. This means incident unit vectors have positive z-component, and outgoing unit vectors have negative
    z-component. We suppose the device has rectangular pixels with sides parallel to the x- and y-axes.
    We further suppose a given pixel (centered at (0,0)) swivels about the vector n = [1, 1, 0]/sqrt(2)
    by angle gamma, i.e. the direction x-y is the most interesting one.
 
    :param pattern: an NxM array. Dimensions of the DMD are determined from this. As usual, the upper left
     hand corner if this array represents the smallest x- and y- values
    :param float wavelength: choose any units as long as consistent with dx, dy, wx, and wy.
    :param float gamma_on: DMD mirror angle in radians
    :param float gamma_off:
    :param float dx: spacing between DMD pixels in the x-direction. Same units as wavelength.
    :param float dy: spacing between DMD pixels in the y-direction. Same units as wavelength.
    :param float wx: width of mirrors in the x-direction. Must be <= dx.
    :param float wy: width of mirrors in the y-direction. Must be <= dy.
    :param uvec_in: (ax, ay, az) direction of plane wave input to DMD
    :param uvecs_out: array of arbitrary size x 3. Output unit vectors where diffraction should be computed.
    :param zshifts: if DMD is assumed to be non-flat, give height profile here. Array of the same size as pattern

    :return efields, sinc_efield_on, sinc_efield_off, diffraction_efield:
    """

    # check input arguments are sensible
    if not np.all(np.logical_or(pattern == 0, pattern == 1)):
        raise TypeError('pattern must be binary. All entries should be 0 or 1.')

    if dx < wx or dy < wy:
        raise ValueError('w must be <= d.')

    if zshifts is None:
        zshifts = np.zeros(pattern.shape)

    ny, nx = pattern.shape
    mxmx, mymy = np.meshgrid(range(nx), range(ny))

    # function to do computation for each output unit vector
    def calc_output_angle(bvec):
        # incoming minus outgoing unit vectors
        amb = uvec_in.squeeze() - bvec

        # efield phase for each DMD pixel
        phases = np.exp(1j * 2*np.pi / wavelength * (dx * mxmx * amb[0] + dy * mymy * amb[1] + zshifts * amb[2]))
        diffraction_efield = np.sum(phases)

        # get envelope functions for ON and OFF states
        sinc_efield_on = wx * wy * blaze_envelope(wavelength, gamma_on, wx, wy, amb)
        sinc_efield_off = wx * wy * blaze_envelope(wavelength, gamma_off, wx, wy, amb)

        # multiply by blaze envelope to get full efield
        mask_phases = np.zeros((ny, nx), dtype=complex)
        mask_phases[pattern == 0] = sinc_efield_off
        mask_phases[pattern == 1] = sinc_efield_on
        mask_phases = mask_phases * phases

        efields = np.sum(mask_phases)

        return efields, sinc_efield_on, sinc_efield_off, diffraction_efield

    # get shape want output arrays to be
    output_shape = uvecs_out.shape[:-1]
    # reshape bvecs to iterate over
    bvecs_to_iterate = np.reshape(uvecs_out, [np.prod(output_shape), 3])

    # simulate
    results = joblib.Parallel(n_jobs=-1, verbose=10, timeout=None)(
        joblib.delayed(calc_output_angle)(bvec) for bvec in bvecs_to_iterate)
    # unpack results for all output directions
    efields, sinc_efield_on, sinc_efield_off, diffraction_efield = zip(*results)
    efields = np.asarray(efields).reshape(output_shape)
    sinc_efield_on = np.asarray(sinc_efield_on).reshape(output_shape)
    sinc_efield_off = np.asarray(sinc_efield_off).reshape(output_shape)
    diffraction_efield = np.asarray(diffraction_efield).reshape(output_shape)

    return efields, sinc_efield_on, sinc_efield_off, diffraction_efield


def simulate_dmd_dft(pattern, efield_profile, wavelength, gamma_on, gamma_off, dx, dy, wx, wy, uvec_in, order):
    """
    Simulate DMD diffraction using DFT. These produces peaks at a discrete set of frequencies which are
    (a-b)_x = wavelength / dx * ix / nx for ix = 0, ... nx - 1
    (a-b)_y = wavelength / dy * iy / ny for iy = 0, ... ny - 1
    these contain the full information of the output field. Intermediate values can be generated by (exact)
    interpolation using the DFT analog of the Shannon-Whittaker interpolation formula.

    @param pattern:
    @param efield_profile: illumination profile, which can include intensity and phase errors
    @param wavelength:
    @param gamma_on:
    @param gamma_off:
    @param dx:
    @param dy:
    @param wx:
    @param wy:
    @param uvec_in:
    @param order: (nx, ny)
    @return efields, sinc_efield_on, sinc_efield_off, b:
    """
    ny, nx = pattern.shape
    order_x, order_y = order
    # dft freqs
    fxs = fft.fftshift(fft.fftfreq(nx))
    fys = fft.fftshift(fft.fftfreq(ny))
    fxfx, fyfy = np.meshgrid(fxs, fys)

    # compute output unit vectors along DFT freqs
    amb_x = wavelength / dx * (order_x + fxfx)
    amb_y = wavelength / dy * (order_y + fyfy)
    bx = uvec_in.squeeze()[0] - amb_x
    by = uvec_in.squeeze()[1] - amb_y
    bvec = np.stack((bx, by, np.sqrt(1 - bx**2 - by**2)), axis=2)

    amb = uvec_in - bvec

    # get envelope functions for ON and OFF states
    sinc_efield_on = wx * wy * blaze_envelope(wavelength, gamma_on, wx, wy, amb)
    sinc_efield_off = wx * wy * blaze_envelope(wavelength, gamma_off, wx, wy, amb)

    pattern_dft = fft.fftshift(fft.fft2(fft.ifftshift(pattern * efield_profile)))
    pattern_complement_dft = fft.fftshift(fft.fft2(fft.ifftshift((1 - pattern) * efield_profile)))

    efields = pattern_dft * sinc_efield_on + pattern_complement_dft * sinc_efield_off

    return efields, pattern_dft, pattern_complement_dft, sinc_efield_on, sinc_efield_off, bvec


def interpolate_dmd_data(pattern, efield_profile, wavelength, gamma_on, gamma_off, dx, dy, wx, wy, uvec_in, order, bvecs_interp):
    """
    Interpolate dmd diffraction DFT data to other output angles using Shannon-Whittaker interpolation formula.

    todo: not really sure this is more efficient than simulate_dmd(), but a useful sanity check

    @param pattern:
    @param efield_profile:
    @param wavelength:
    @param gamma_on:
    @param gamma_off:
    @param dx:
    @param dy:
    @param wx:
    @param wy:
    @param uvec_in:
    @param order:
    @param bvecs_interp:
    @return efields:
    """
    _, pattern_dft, pattern_dft_complement, _, _, bvec = \
          simulate_dmd_dft(pattern, efield_profile, wavelength, gamma_on, gamma_off, dx, dy, wx, wy, uvec_in, order)

    ny, nx = pattern.shape
    # order_x, order_y = order
    # dft freqs
    fxs = fft.fftshift(fft.fftfreq(nx))
    fys = fft.fftshift(fft.fftfreq(ny))

    amb = uvec_in - bvecs_interp
    sinc_efield_on = wx * wy * blaze_envelope(wavelength, gamma_on, wx, wy, amb)
    sinc_efield_off = wx * wy * blaze_envelope(wavelength, gamma_off, wx, wy, amb)

    def interp_x(amb_x):
        arg = (fxs * nx - nx * dx / wavelength * amb_x) / nx
        val = 1/nx * np.sin(np.pi * arg * nx) / np.sin(np.pi * arg) * np.exp(np.pi * 1j * arg * (nx - 1))
        val[np.mod(np.round(arg, 14), 1) == 0] = 1
        return val

    def interp_y(amb_y):
        arg = (fys * ny - ny * dy / wavelength * amb_y) / ny
        val = 1 / ny * np.sin(np.pi * arg * ny) / np.sin(np.pi * arg) * np.exp(np.pi * 1j * arg * (ny - 1))
        val[np.mod(np.round(arg, 14), 1) == 0] = 1
        return val

    def calc(ii):
        ind = np.unravel_index(ii, bvecs_interp.shape[:-1])
        val = np.sum((pattern_dft * sinc_efield_on[ind] + pattern_dft_complement * sinc_efield_off[ind]) *
              np.expand_dims(interp_x(amb[ind, 0]), axis=0) *
              np.expand_dims(interp_y(amb[ind, 1]), axis=1))
        return val

    nvecs = np.prod(bvecs_interp.shape[:-1])
    results = joblib.Parallel(n_jobs=-1, verbose=10, timeout=None)(
        joblib.delayed(calc)(ii) for ii in range(nvecs))
    efields = np.array(results).reshape(bvecs_interp.shape[:-1])

    return efields


def blaze_envelope(wavelength, gamma, wx, wy, a_minus_b, n_vec=(1 / np.sqrt(2), 1 / np.sqrt(2), 0)):
    """
    Compute normalized blaze envelope function. Envelope function has value 1 where the blaze condition is satisfied.
    This is the result of doing the integral
    \int ds dt exp[ ik Rn*(s,t,0) \cdot (a-b)] = \int ds dt exp[ ik * (A_+*s + A_-*t)]

    :param wavelength: wavelength of light. Units are arbitrary, but must be the same for wavelength, wx, and wy
    :param gamma: mirror swivel angle, in radians
    :param wx: mirror width in x-direction. Same units as wavelength.
    :param wy: mirror width in y-direction. Same units as wavelength.
    :param a_minus_b: difference between input (a) and output (b) unit vectors. NumPy array of size N x 3
    :param n_vec: unit vector about which the mirror swivels. Typically (1, 1, 0) / np.sqrt(2)

    :return envelope: same length as a_minus_b
    """

    k = 2*np.pi / wavelength
    envelope = sinc_fn(0.5 * k * wx * blaze_condition_fn(gamma, a_minus_b, 'plus',  n_vec=n_vec)) * \
               sinc_fn(0.5 * k * wy * blaze_condition_fn(gamma, a_minus_b, 'minus', n_vec=n_vec))
    return envelope


def blaze_condition_fn(gamma, amb, mode='plus', n_vec=(1/np.sqrt(2), 1/np.sqrt(2), 0)):
    """
    Return the dimensionsless part of the sinc function argument which determines the Blaze condition,
    which we refer to as A_+ and A_-

    E = (diffraction from different mirrors) x w**2 * sinc(0.5 * k * w * A_+) * sinc(0.5 * k * w * A_-)

    A_\pm = 0.5*(1 \pm cos(gamma)) * (a-b)_x + 0.5*(1 \mp cos(gamma)) * (a-b)_y \mp sin(gamma)/sqrt(2) * (a-b)_z

    :param gamma: angle micro-mirror normal makes with device normal
    :param amb: incoming unit vector - outgoing unit vector, [vx, vy, vz]. Will also accept a matrix of shape
    n0 x n1 x ... x 3
    :param mode: 'plus' or 'minus'
    :param n_vec: unit vector about which the mirror swivels. Typically use (1, 1, 0) / np.sqrt(2)

    :return A:
    """
    nx, ny, nz = n_vec
    if mode == 'plus':
        A = (nx ** 2 * (1 - np.cos(gamma)) + np.cos(gamma)) * amb[..., 0] + \
            (nx * ny * (1 - np.cos(gamma)) + nz * np.sin(gamma)) * amb[..., 1] + \
            (nx * nz * (1 - np.cos(gamma)) - ny * np.sin(gamma)) * amb[..., 2]
    elif mode == 'minus':
        A = (nx * ny * (1 - np.cos(gamma)) - nz * np.sin(gamma)) * amb[..., 0] + \
            (ny ** 2 * (1 - np.cos(gamma)) + np.cos(gamma)) * amb[..., 1] + \
            (ny * nz * (1 - np.cos(gamma)) + nx * np.sin(gamma)) * amb[..., 2]
    else:
        raise ValueError("mode must be 'plus' or 'minus', but was '%s'" % mode)
    return A


def sinc_fn(x):
    """
    Unnormalized sinc function, sinc(x) = sin(x) / x

    :param x:
    :return sinc(x):
    """
    x = np.atleast_1d(x)
    with np.errstate(divide='ignore'):
        y = np.asarray(np.sin(x) / x)
    y[x == 0] = 1
    return y


def get_rot_mat(n_vec, gamma):
    """
    Get matrix which rotates points about the specified axis

    :param n_vec: axis to rotate about, [nx, ny, nz]
    :param gamma: rotation angle in radians
    :return mat:
    """
    nx, ny, nz = n_vec
    mat = np.array([[nx**2 * (1 - np.cos(gamma)) + np.cos(gamma), nx * ny * (1 - np.cos(gamma)) - nz * np.sin(gamma), nx * nz * (1 - np.cos(gamma)) + ny * np.sin(gamma)],
                    [nx * ny * (1 - np.cos(gamma)) + nz * np.sin(gamma), ny**2 * (1 - np.cos(gamma)) + np.cos(gamma), ny * nz * (1 - np.cos(gamma)) - nx * np.sin(gamma)],
                    [nx * nz * (1 - np.cos(gamma)) - ny * np.sin(gamma), ny * nz * (1 - np.cos(gamma)) + nx * np.sin(gamma), nz**2 * (1 - np.cos(gamma)) + np.cos(gamma)]])
    return mat


# convert between coordinate systems
def xyz2mirror(vx, vy, vz, gamma):
    """
    Convert vector with components vx, vy, vz to v1, v2, v3.

    The unit vectors ex, ey, ez are defined along the axes of the DMD body,
    where as the unit vectors e1, e2, e3 are given by
    e1 = (ex - ey) / sqrt(2) * cos(gamma) - ez * sin(gamma)
    e2 = (ex + ey) / sqrt(2)
    e3 = (ex - ey) / sqrt(2) sin(gamma) + ez * cos(gamma)
    which are convenient because e1 points along the direction the micromirrors swivel and
    e3 is normal to the DMD micrmirrors

    :param vx:
    :param vy:
    :param vz:
    :param gamma:
    :return: v1, v2, v3
    """
    v1 = np.cos(gamma) / np.sqrt(2) * (vx - vy) - np.sin(gamma) * vz
    v2 = 1 / np.sqrt(2) * (vx + vy)
    v3 = np.sin(gamma) / np.sqrt(2) * (vx - vy) + np.cos(gamma) * vz
    return v1, v2, v3


def mirror2xyz(v1, v2, v3, gamma):
    """
    Inverse function for xyz2mirror()

    :param v1:
    :param v2:
    :param v3:
    :param gamma:
    :return:
    """
    vx = np.cos(gamma) / np.sqrt(2) * v1 + 1 / np.sqrt(2) * v2 + np.sin(gamma) / np.sqrt(2) * v3
    vy = -np.cos(gamma) / np.sqrt(2) * v1 + 1 / np.sqrt(2) * v2 - np.sin(gamma) / np.sqrt(2) * v3
    vz = -np.sin(gamma) * v1 + np.cos(gamma) * v3
    return vx, vy, vz


def xyz2mpz(vx, vy, vz):
    """
    Convert from x, y, z coordinate system to m = (x-y)/sqrt(2), p = (x+y)/sqrt(2), z

    @param vx:
    @param vy:
    @param vz:
    @return vm, vp, vz:
    """
    vp = np.array(vx + vy) / np.sqrt(2)
    vm = np.array(vx - vy) / np.sqrt(2)
    vz = np.array(vz, copy=True)

    return vm, vp, vz


def mpz2xyz(vm, vp, vz):
    """
    Convert from m = (x-y)/sqrt(2), p = (x+y)/sqrt(2), z coordinate system to x, y, z
    @param vm:
    @param vp:
    @param vz:
    @return, vx, vy, vz:
    """
    vx = np.array(vm + vp) / np.sqrt(2)
    vy = np.array(vp - vm) / np.sqrt(2)
    vz = np.array(vz, copy=True)

    return vx, vy, vz

# convert between different angular or unit vector representations of input and output directions
def angle2xy(tp, tm):
    """
    Convert angle projections along the x and y axis to angle projections along the p=(x+y)/sqrt(2)
    and m=(x-y)/sqrt(2) axis.

    :param tp:
    :param tm:
    :return tx, ty:
    """

    tx = np.arctan((np.tan(tp) + np.tan(tm)) / np.sqrt(2))
    ty = np.arctan((np.tan(tp) - np.tan(tm)) / np.sqrt(2))

    return tx, ty


def angle2pm(tx, ty):
    """
    Convert angle projections along the the p=(x+y)/sqrt(2) and m=(x-y)/sqrt(2) to x and y axes.

    :param tx:
    :param ty:
    :return tp, tm:
    """

    tm = np.arctan((np.tan(tx) - np.tan(ty)) / np.sqrt(2))
    tp = np.arctan((np.tan(tx) + np.tan(ty)) / np.sqrt(2))

    return tp, tm


def uvector2txty(vx, vy, vz):
    """
    Convert unit vector from components to theta_x, theta_y representation. Inverse function for get_unit_vector()

    NOTE: tx and ty are defined differently depending on the sign of the z-component of the unit vector
    :param vx:
    :param vy:
    :param vz:
    :return:
    """
    norm_factor = np.abs(1 / vz)
    tx = np.arctan(vx * norm_factor)
    ty = np.arctan(vy * norm_factor)

    return tx, ty


def uvector2tmtp(vx, vy, vz):
    tx, ty = uvector2txty(vx, vy, vz)
    tp, tm = angle2pm(tx, ty)
    return tp, tm


def pm2uvector(tm, tp, mode="in"):
    tx, ty = angle2xy(tp, tm)
    return get_unit_vector(tx, ty, mode=mode)


def get_unit_vector(tx, ty, mode='in'):
    """
    Get incoming or outgoing unit vector of light propagation parametrized by angles tx and ty

    Let a represent an incoming vector, and b and outgoing one. We parameterize these by
    a = az * [tan(tx_a), tan(ty_a), -1]
    b = |bz| * [tan(tb_x), tan(tb_y), 1]
    choosing negative z component for outgoing vectors is effectively taking a different
    conventions for the angle between b and the z axis (compared with a and
    the z-axis). We do this so that e.g. the law of reflection would give
    theta_a = theta_b, instead of theta_a = -theta_b, which would hold if we
    defined everything symmetrically.

    :param tx: arbitrary size
    :param ty: same size as tx
    :param mode: "in" or "out" depending on whether representing a vector pointing in the negative
     or positive z-direction

    :return uvec: unit vectors, array of size tx.size x 3
    """
    tx = np.atleast_1d(tx)
    ty = np.atleast_1d(ty)
    norm = np.sqrt(np.tan(tx)**2 + np.tan(ty)**2 + 1)
    if mode == 'in':
        ux = np.tan(tx)
        uy = np.tan(ty)
        uz = -np.ones(tx.shape)
    elif mode == 'out':
        ux = np.tan(tx)
        uy = np.tan(ty)
        uz = np.ones(tx.shape)
    else:
        raise ValueError("mode must be 'in' or 'out', but was '%s'" % mode)

    uvec = np.stack((ux, uy, uz), axis=-1) / np.expand_dims(norm, axis=-1)

    return uvec


# diffraction directions for different pattern frequencies
def freq2uvec(uvec_out_dc, fx, fy, wavelength, dx, dy):
    """
    Determine the output diffraction vector b(f) given the output vector b(0) and the
    spatial frequency f = [fx, fy] in 1/mirrors.

    @param uvec_out_dc: main diffraction output unit vector, i.e. DC diffraction component output direction
    @param fx: 1/mirror
    @param fy: 1/mirror
    @param wavelength: distance units
    @param dx: same units as wavelength
    @param dy: same units as wavelength
    @return bfx, bfy, bfz:
    """
    bfx = uvec_out_dc[0] + wavelength / dx * fx
    bfy = uvec_out_dc[1] + wavelength / dy * fy
    bfz = np.sqrt(1 - bfx**2 - bfy**2)

    return bfx, bfy, bfz


def uvec2freq(uvec_out_dc, uvec_f, wavelength, dx, dy):
    """
    Inverse function of freq2uvec

    @param uvec_out_dc:
    @param uvec_f:
    @param wavelength:
    @param dx:
    @param dy:
    @return fx, fy:
    """
    fx = (uvec_f[..., 0] - uvec_out_dc[0]) * dx / wavelength
    fy = (uvec_f[..., 1] - uvec_out_dc[1]) * dy / wavelength
    return fx, fy


# Fourier plane mapping
def get_fourier_plane_basis(optical_axis_uvec):
    """
    Get basis vectors which are orthogonal to a given optical axis. This is useful when
    we suppose that a lens has been placed one focal length after the DMD and we are interested
    in computing the optical field in the back focal plane of the lens (i.e. the Fourier plane) or
    determining the relative angles between diffraction directions and the optical axis.

    This basis is chosen such that xb would point along the x-axis and yb would point
    along the y-axis if optical_axis_uvec = (0, 0, 1).

    @param optical_axis_uvec: unit vector defining the optical axis
    @return xb, yb:
    """
    xb = np.array([optical_axis_uvec[2], 0, -optical_axis_uvec[0]]) / np.sqrt(optical_axis_uvec[0] ** 2 + optical_axis_uvec[2] ** 2)
    yb = np.cross(optical_axis_uvec, xb)

    return xb, yb


def dmd_frqs2axis_frqs(fx, fy, bvec, optical_axis_vec, dx, dy, wavelength):
    """
    Given a set of DMD frequencies, determine what effective frequencies the diffracted orders travel along
    relative to the optical axis
    @param fx: 1/mirrors
    @param fy: 1/mirrors
    @param bvec:
    @param optical_axis_vec:
    @param dx:
    @param dy:
    @param wavelength:
    @return fxs_oaxis, fys_oaxis: in 1/distance units. Where dx, dy, and wavelength are in distance units
    """
    bf_xp, bf_yp, bf_zp = dmd_frqs2fourier_plane(fx, fy, bvec, optical_axis_vec, dx, dy, wavelength)
    fxs_oaxis = bf_xp / wavelength
    fys_oaxis = bf_yp / wavelength

    return fxs_oaxis, fys_oaxis


def dmd_frqs2fourier_plane(fx, fy, bvec, opt_axis_vec, dx, dy, wavelength):
    """
    todo: rename dmd_frqs2optical_axis_angles()

    Convert from DMD pattern frequencies to (dimensionless) Fourier plane coordinates. These are dimensionless
    in the sense that they must be multiplied by the lens focal length (and index of refraction)
    to give the actual Fourier plane coordinates.

    This is useful when we suppose that a lens has been placed one focal length after the DMD and we are interested
    in computing the optical field in the back focal plane of the lens (i.e. the Fourier plane).

    :param fx: 1/mirror
    :param fy: 1/mirror
    :param bvec: main diffraction order output angle, which is the angle a flat pattern (i.e. a pattern of
    frequency fx=0, fy=0) is diffracted into.
    :param opt_axis_vec: unit vector pointing along the optical axis of the Fourier plane
    :param dx: DMD pitch
    :param dy: DMD pitch
    :param wavelength: same units as DMD pitch

    :return bf_xp, bf_yp, bf_zp: vector components in the pupil plane and along the optical axis. In most cases
    bf_zp is not useful. But bf_xp and bf_yp may be converted to pupil spatial coordinates by multiplying them
    with the lens focal length.
    """
    if np.abs(np.linalg.norm(bvec) - 1) > 1e-12:
        raise ValueError("bvec was not a unit vector")

    if np.abs(np.linalg.norm(opt_axis_vec) - 1) > 1e-12:
        raise ValueError("pvec was not a unit vector")


    fx = np.atleast_1d(fx)
    fy = np.atleast_1d(fy)

    bf_xs, bf_ys, bf_zs = freq2uvec(bvec, fx, fy, wavelength, dx, dy)

    # pupil basis
    xp, yp = get_fourier_plane_basis(opt_axis_vec)

    # convert bfs to pupil coordinates
    # bf_xp = b(f) \dot x_p = bx * x \dot x_p + by * y \dot y_p + bz * z \dot z_p
    bf_xp = bf_xs * xp[0] + bf_ys * xp[1] + bf_zs * xp[2]
    bf_yp = bf_xs * yp[0] + bf_ys * yp[1] + bf_zs * yp[2]
    bf_zp = bf_xs * opt_axis_vec[0] + bf_ys * opt_axis_vec[1] + bf_zs * opt_axis_vec[2]

    # note that there many other ways of thinking about this problem.
    # another natural way is to being with b(f) and zp. Construct an orthogonal coordinate system with
    # v2 = zp \cross b(f) / norm = (b_xp * yp - b_yp * xp) / sqrt(b_xp**2 + b_yp**2)
    # v1 = v2 \cross zp / norm = (b_xp * xp + b_yp * yp) / sqrt(b_xp**2 + b_yp**2)
    # then the position in the pupil plane is
    # r = v1 * fl * sin(theta) = (b_xp * xp + b_yp * yp) * fl
    # which is just what we get from the above...

    return bf_xp, bf_yp, bf_zp


# #####################
# functions for solving blaze + diffraction conditions
# #####################
def get_diffraction_order_limits(wavelength, d, gamma):
    """
    Find the maximum and minimum diffraction orders consistent with given parameters and the blaze condition.
    Note that only diffraction orders of the form (n, -n) can satisfy the Blaze condition, hence only the value
    n is returned and not a 2D diffraction order tuple.

    :param wavelength: wavelength of light
    :param d: mirror pitch (in same units as wavelength)
    :param gamma: mirror angle
    :return nmax: maximum index of diffraction order
    :return nmin: minimum index of diffraction order
    """

    # # solution for maximum order
    if gamma > 0:
        nmax = int(np.floor(d / wavelength * np.sqrt(2) * np.sin(gamma)))
        nmin = 1
    elif gamma <= 0:
        nmax = -1
        nmin = int(np.ceil(d / wavelength * np.sqrt(2) * np.sin(gamma)))
    else:
        raise ValueError()

    return np.array([nmin, nmax], dtype=int)


def solve_1color_1d(wavelength, d, gamma, order):
    """
    Solve for the input and output angles satisfying both the diffraction condition and blaze angle for a given
    diffraction order (if possible). These function assumes that the input and output beams are in the x-y plane,
    and the angles are given relative to the DMD normal.

    The two conditions to be solved are
    (1) theta_in - theta_out = 2*gamma
    (2) sin(theta_in) - sin(theta_out) = sqrt(2) * wavelength / d * n

    This function is a wrapper for solve_combined_condition() simplified for the 1D geometry.

    :param float wavelength: wavelength of light
    :param float d: mirror pitch (in same units as wavelength)
    :param float gamma: angle mirror normal makes with DMD body normal
    :param int order: diffraction order index. Full order index is (nx, ny) = (order, -order)

    :return uvecs_in: list of input angle solutions as unit vectors
    :return uvecs_out: list of output angle solutions as unit vectors
    """
    afn, bfn, _ = solve_combined_condition(d, gamma, wavelength, order)
    # 1D solutions are the solutions where a_{x+y} = a2 = 0
    uvecs_in = np.array([afn(0, True), afn(0, False)])
    uvecs_out = np.array([bfn(0, True), bfn(0, False)])

    return uvecs_in, uvecs_out


def solve_blaze_output(uvecs_in, gamma):
    """
    Find the output angle which satisfies the blaze condition for arbitrary input angle.

    :param uvecs_in: N x 3 array of unit vectors (ax, ay, az)
    :param float gamma: DMD mirror angle in radians
    :return uvecs_out: unit vectors giving output directions
    """

    uvecs_in = np.atleast_2d(uvecs_in)
    # convert to convenient coordinates and apply blaze
    a1, a2, a3 = xyz2mirror(uvecs_in[..., 0], uvecs_in[..., 1], uvecs_in[..., 2], gamma)
    bx, by, bz = mirror2xyz(a1, a2, -a3, gamma)
    uvecs_out = np.stack((bx, by, bz), axis=-1)

    return uvecs_out


def solve_blaze_input(uvecs_out, gamma):
    """
    Find the input angle which satisfies the blaze condition for arbitrary output angle.

    @param uvecs_out:
    @param float gamma:
    @return uvecs_in:
    """
    return solve_blaze_output(uvecs_out, gamma)


def solve_diffraction_input(uvecs_out, dx, dy, wavelength, order):
    """
    Solve for the input direction which will be diffracted into the given output direction by
    the given diffraction order of the DMD

    :param uvecs_out:
    :param float dx:
    :param float dy:
    :param float wavelength:
    :param order: (order_x, order_y). Typically order_y = -order_x, as otherwise the blaze condition cannot
    also be satisfied
    :return avecs:
    """
    uvecs_out = np.atleast_2d(uvecs_out)

    ax = uvecs_out[..., 0] + wavelength / dx * order[0]
    ay = uvecs_out[..., 1] + wavelength / dy * order[1]
    az = -np.sqrt(1 - ax**2 - ay**2)
    uvecs_in = np.stack((ax, ay, az), axis=-1)

    return uvecs_in


def solve_diffraction_output(uvecs_in, dx, dy, wavelength, order):
    """
    Solve for the output direction into which the given input direction will be diffracted by the given
    order of the DMD

    :param uvecs_in:
    :param dx:
    :param dy:
    :param wavelength:
    :param order: (nx, ny)
    :return uvecs_out:
    """
    uvecs_in = np.atleast_2d(uvecs_in)

    bx = uvecs_in[..., 0] - wavelength / dx * order[0]
    by = uvecs_in[..., 1] - wavelength / dy * order[1]
    with np.errstate(invalid="ignore"):
        bz = np.sqrt(1 - bx**2 - by**2)

    # these points have no solution
    bx[np.isnan(bz)] = np.nan
    by[np.isnan(bz)] = np.nan

    # tx_out, ty_out = uvector2txty(bx, by, bz)
    uvecs_out = np.stack((bx, by, bz), axis=-1)

    return uvecs_out


def solve_combined_condition(d, gamma, wavelength, order):
    """
    Return functions for the simultaneous blaze/diffraction condition solution as a function of a_{x+y} = a_2.

    :param float d: DMD mirror pitch
    :param float gamma: DMD mirror angle along the x-y direction in radians
    :param float wavelength: wavelength in same units as DMD mirror pitch
    :param int order: (nx, ny) = (order, -order). Note that there are no solutions to this joint problem for nx != - ny
    :return a_fn: function which accepts a_2 as argument and returns (ax, ay, az). Input unit-vector direction solutions
    Takes two arguments a_fn(a2, positive), where positive is boolean. If True, returns positive root, if false returns
    negative. To get all solutions must take both
    :return b_fn: function which accepts a_2 as argument and returns (bx, by, bz). Output unit-vector direction solutions
    :return a2_bounds: [a2_min, a2_max], maximum and minimum allowed values for a_2
    """

    a3 = 1 / np.sqrt(2) / np.sin(gamma) * wavelength / d * order
    # due to rounding issues sometimes a1_positive_fn() gives nans at the end points
    a2_bounds = np.array([-np.sqrt(1 - a3**2), np.sqrt(1 - a3**2)])

    def a1_positive_fn(a2): return np.sqrt(1 - a2**2 - a3**2)

    def ax_fn(a2, positive=True):
        a1 = a1_positive_fn(a2)
        if not positive:
            a1 = -a1
        return np.cos(gamma) / np.sqrt(2) * a1 + 1 / np.sqrt(2) * a2 + np.sin(gamma) / np.sqrt(2) * a3

    def ay_fn(a2, positive=True):
        a1 = a1_positive_fn(a2)
        if not positive:
            a1 = -a1
        return -np.cos(gamma) / np.sqrt(2) * a1 + 1 / np.sqrt(2) * a2 - np.sin(gamma) / np.sqrt(2) * a3

    def az_fn(a2, positive=True):
        a1 = a1_positive_fn(a2)
        if not positive:
            a1 = -a1
        return -np.sin(gamma) * a1 + np.cos(gamma) * a3

    # b functions
    def bx_fn(a2, positive=True):
        a1 = a1_positive_fn(a2)
        if not positive:
            a1 = -a1
        return np.cos(gamma) / np.sqrt(2) * a1 + 1 / np.sqrt(2) * a2 - np.sin(gamma) / np.sqrt(2) * a3

    def by_fn(a2, positive=True):
        a1 = a1_positive_fn(a2)
        if not positive:
            a1 = -a1
        return -np.cos(gamma) / np.sqrt(2) * a1 + 1 / np.sqrt(2) * a2 + np.sin(gamma) / np.sqrt(2) * a3

    def bz_fn(a2, positive=True):
        a1 = a1_positive_fn(a2)
        if not positive:
            a1 = -a1
        return -np.sin(gamma) * a1 - np.cos(gamma) * a3

    def a_fn(a2, positive=True): return ax_fn(a2, positive), ay_fn(a2, positive), az_fn(a2, positive)

    def b_fn(a2, positive=True): return bx_fn(a2, positive), by_fn(a2, positive), bz_fn(a2, positive)

    return a_fn, b_fn, a2_bounds


def solve_2color_on_off(d, gamma_on, wavelength_on, n_on, wavelength_off, n_off):
    """
    Solve overlap for two wavelengths, one incident on the "on" mirrors and the other on the
     "off" mirrors

    :param d: mirror pitch
    :param gamma_on: mirror angle in ON state in radians. Assume that gamma_off = -gamma_on
    :param wavelength_on: wavelength of light incident on ON mirrors. Must be in same units as d
    :param n_on: diffraction order for ON mirrors
    :param wavelength_off: wavelength of light incident on OFF mirrors. Must be in same units as d
    :param n_off: diffraction order for OFF mirrors

    :return b_vecs: output unit vectors. Two solution vectors, size 2 x 3
    :return a_vecs_on: input unit vectors for ON mirrors
    :return b_vecs_on: input unit vectors for OFF mirrors
    """

    b3_on = -1 / np.sqrt(2) / np.sin(gamma_on) * wavelength_on / d * n_on
    b3_off = 1 / np.sqrt(2) / np.sin(gamma_on) * wavelength_off / d * n_off

    # equate b_on and b_off, and solve for bz, bx, by
    # (1) b3_on + b3_off = 2 * cos(gamma) * bz
    # (2) b3_on - b3_off = np.sqrt(2) * np.sin(gamma) * (bx - by)
    bz = 0.5 / np.cos(gamma_on) * (b3_on + b3_off)

    # quadratic equation for bx from (2)
    c1 = 1
    c2 = -(b3_on - b3_off) / np.sqrt(2) / np.sin(gamma_on)
    c3 = 0.5 * (bz**2 + (b3_on - b3_off)**2 / 2 / np.sin(gamma_on)**2 - 1)

    bxs = np.array([0.5 * (-c2 + np.sqrt(c2**2 - 4 * c3)) / c1,
                    0.5 * (-c2 - np.sqrt(c2**2 - 4 * c3)) / c1])

    # apply eq. (2) again to get by (since lost information when we squared it to get quadratic eqn)
    bys = bxs - (b3_on - b3_off) / np.sqrt(2) / np.sin(gamma_on)

    # assemble b-vector
    b_vecs = np.array([[bxs[0], bys[0], bz], [bxs[1], bys[1], bz]])

    for ii in range(b_vecs.shape[0]):
        if np.any(np.isnan(b_vecs[ii])):
            b_vecs[ii, :] = np.nan

    # get input unit vectors
    a_vecs_on = np.zeros(b_vecs.shape)
    a_vecs_off = np.zeros(b_vecs.shape)
    for ii in range(b_vecs.shape[0]):
        b1_on, b2_on, b3_on = xyz2mirror(b_vecs[ii, 0], b_vecs[ii, 1], b_vecs[ii, 2], gamma_on)
        a1_on = b1_on
        a2_on = b2_on
        a3_on = -b3_on
        a_vecs_on[ii] = mirror2xyz(a1_on, a2_on, a3_on, gamma_on)

        b1_off, b2_off, b3_off = xyz2mirror(b_vecs[ii, 0], b_vecs[ii, 1], b_vecs[ii, 2], -gamma_on)
        a1_off = b1_off
        a2_off = b2_off
        a3_off = -b3_off
        a_vecs_off[ii] = mirror2xyz(a1_off, a2_off, a3_off, -gamma_on)

    return b_vecs, a_vecs_on, a_vecs_off

# ###########################
# convenient simulation functions for considering multiple wavelengths in a variety of situations
# ###########################
# 1D simulation in x-y plane
def simulate_1d(pattern, wavelengths, gamma_on, gamma_off, dx, dy, wx, wy,
                tm_ins, tm_out_offsets=None, ndiff_orders=10):
    """
    Simulate various colors of light incident on a DMD, assuming the DMD is oriented so that the mirrors swivel in
    the same plane the incident light travels in and that this plane makes a 45 degree angle with the principle axes
    of the DMD. For more detailed discussion DMD parameters see the function simulate_dmd()

    :param pattern: binary pattern of arbitrary size
    :param wavelengths: list of wavelengths to compute
    :param gamma_on: mirror angle in ON position, relative to the DMD normal
    :param gamma_off:
    :param dx: spacing between DMD pixels in the x-direction. Same units as wavelength.
    :param dy: spacing between DMD pixels in the y-direction. Same units as wavelength.
    :param wx: width of mirrors in the x-direction. Must be < dx.
    :param wy: width of mirrors in the y-direction. Must be < dy.
    :param tm_ins: input angles in the plane of incidence
    :param tm_out_offsets: output angles relative to the angle satisfying the blaze condition
    :return data: dictionary storing simulation results
    """

    if isinstance(tm_ins, (float, int)):
        tm_ins = np.array([tm_ins])
    ninputs = len(tm_ins)

    if tm_out_offsets is None:
        tm_out_offsets = np.linspace(-45, 45, 2400) * np.pi / 180
    noutputs = len(tm_out_offsets)

    if isinstance(wavelengths, float):
        wavelengths = [wavelengths]
    n_wavelens = len(wavelengths)

    # input angles
    tx_ins, ty_ins = angle2xy(0, tm_ins)
    uvecs_in = get_unit_vector(tx_ins, ty_ins, "in")

    # blaze condition
    bvec_blaze_on = solve_blaze_output(uvecs_in, gamma_on)
    bvec_blaze_off = solve_blaze_output(uvecs_in, gamma_off)

    # variables to store simulation output data
    uvecs_out = np.zeros((ninputs, noutputs, 3))
    efields = np.zeros((ninputs, noutputs, n_wavelens), dtype=complex)
    sinc_efield_on = np.zeros(efields.shape, dtype=complex)
    sinc_efield_off = np.zeros(efields.shape, dtype=complex)

    # diffraction order predictions
    nxs = np.array(range(-ndiff_orders, ndiff_orders + 1))
    nys = -nxs
    diff_uvec_out = np.zeros((ninputs, n_wavelens, len(nxs), 3))

    # loop over input directions
    for kk in range(ninputs):
        # #########################
        # output angles track input angle
        # #########################
        _, tms_blaze_on = uvector2tmtp(*bvec_blaze_on[kk])
        tms_out = tms_blaze_on + tm_out_offsets
        txs_out, tys_out = angle2xy(np.zeros(tms_out.shape), tms_out)
        uvecs_out[kk] = get_unit_vector(txs_out, tys_out, "out")

        # #########################
        # do simulation
        # #########################
        for ii in range(n_wavelens):
            efields[kk, :, ii], sinc_efield_on[kk, :, ii], sinc_efield_off[kk, :, ii], _ \
             = simulate_dmd(pattern, wavelengths[ii], gamma_on, gamma_off, dx, dy, wx, wy, uvecs_in, uvecs_out[kk])

            # get diffraction orders. Orders we want are along the antidiagonal
            for aa in range(len(nxs)):
                diff_uvec_out[kk, ii, aa] = solve_diffraction_output(uvecs_in[kk], dx, dy, wavelengths[ii], (nxs[aa], nys[aa]))

    # store data
    data = {'pattern': pattern, 'wavelengths': wavelengths,
            'gamma_on': gamma_on, 'gamma_off': gamma_off, 'dx': dx, 'dy': dy, 'wx': wx, 'wy': wy,
            'uvecs_in': uvecs_in, 'uvecs_out': uvecs_out,
            'uvec_out_blaze_on': bvec_blaze_on, 'uvec_out_blaze_off': bvec_blaze_off,
            'diff_uvec_out': diff_uvec_out, 'diff_nxs': nxs, 'diff_nys': nys,
            'efields': efields, 'sinc_efield_on': sinc_efield_on, 'sinc_efield_off': sinc_efield_off}

    return data


def plot_1d_sim(data, colors=None, plot_log=False, save_dir=None, figsize=(18, 14)):
    """
    Plot and optionally save results of simulate_1d()

    :param dict data: dictionary output from simulate_1d()
    :param list colors: list of colors, or None to use defaults
    :param bool plot_log: boolean
    :param str save_dir: directory to save data and figure results in. If None, then do not save
    :param figsize:
    :return fighs, fig_names: lists of figure handles and figure names
    """

    # save data
    if save_dir is not None:
        # unique file name
        fname = os.path.join(save_dir, 'simulation_data.pkl')
        with open(fname, 'wb') as f:
            pickle.dump(data, f)

    # ##############################
    # unpack data
    # ##############################
    pattern = data['pattern']
    wavelengths = data['wavelengths']
    n_wavelens = len(wavelengths)
    gamma_on = data['gamma_on']
    gamma_off = data['gamma_off']
    dx = data['dx']
    dy = data['dy']
    wx = data['wx']
    wy = data['wy']
    uvec_ins = data["uvecs_in"]
    uvec_outs = data["uvecs_out"]
    efields = data['efields']
    sinc_efield_on = data['sinc_efield_on']
    sinc_efield_off = data['sinc_efield_off']
    diff_uvec_out = data['diff_uvec_out']
    diff_n = data['diff_nxs']
    iz = np.where(diff_n == 0)

    # get colors if not provided
    if colors is None:
        cmap = matplotlib.cm.get_cmap('jet')
        colors = [cmap(ii / (n_wavelens - 1)) for ii in range(n_wavelens)]

    #decide how to scale plot
    if plot_log:
        scale_fn = lambda I: np.log10(I)
    else:
        scale_fn = lambda I: I

    # ##############################
    # Plot results, on different plot for each input angle
    # ##############################
    figs = []
    fig_names = []
    for kk in range(len(uvec_ins)):
        # compute useful angle data for plotting
        tx_in, ty_in = uvector2txty(uvec_ins[kk, 0], uvec_ins[kk, 1], uvec_ins[kk, 2])
        tp_in, tm_in = uvector2tmtp(uvec_ins[kk, 0], uvec_ins[kk, 1], uvec_ins[kk, 2])
        _, tms_out = uvector2tmtp(uvec_outs[kk, :, 0], uvec_outs[kk, :, 1], uvec_outs[kk, :, 2])
        _, tms_blaze_on = uvector2tmtp(*data['uvec_out_blaze_on'][kk])
        _, tms_blaze_off = uvector2tmtp(*data['uvec_out_blaze_off'][kk])

        figh = plt.figure(figsize=figsize)
        grid = plt.GridSpec(2, 2, hspace=0.5)

        # title
        param_str = 'spacing = %0.2fum, w=%0.2fum, gamma (on,off)=(%.1f, %.1f) deg\n' \
                    'theta in = (%0.2f, %0.2f)deg = %0.2f deg (x-y)\ninput unit vector = (%0.4f, %0.4f, %0.4f)' \
                    '\n theta blaze (on,off)=(%.2f, %.2f) deg in x-y dir' % \
                    (dx * 1e6, wx * 1e6, gamma_on * 180 / np.pi, gamma_off * 180 / np.pi,
                     tx_in * 180 / np.pi, ty_in * 180 / np.pi, tm_in * 180 / np.pi,
                     uvec_ins[kk, 0], uvec_ins[kk, 1], uvec_ins[kk, 2],
                     tms_blaze_on * 180 / np.pi, tms_blaze_off * 180 / np.pi)

        plt.suptitle(param_str)

        # ######################################
        # plot diffracted output field
        # ######################################
        ax = plt.subplot(grid[0, 0])

        for ii in range(n_wavelens):
            # get intensities
            intensity = np.abs(efields[kk, :, ii])**2
            intensity_sinc_on = np.abs(sinc_efield_on[kk, :, ii]) ** 2

            # normalize intensity to sinc
            im = np.argmax(np.abs(intensity))
            norm = intensity[im] / (intensity_sinc_on[im] / wx**2 / wy**2)

            # plot intensities
            plt.plot(tms_out * 180 / np.pi, scale_fn(intensity / norm), color=colors[ii])
            plt.plot(tms_out * 180 / np.pi, scale_fn(intensity_sinc_on / (wx*wy)**2), color=colors[ii], ls=':')
            plt.plot(tms_out * 180 / np.pi, scale_fn(np.abs(sinc_efield_off[kk, :, ii]) ** 2 / (wx*wy)**2), color=colors[ii], ls='--')

        ylim = ax.get_ylim()

        # plot blaze condition locations
        plt.plot([tms_blaze_on * 180 / np.pi, tms_blaze_on * 180 / np.pi], ylim, 'k:')
        plt.plot([tms_blaze_off * 180 / np.pi, tms_blaze_off * 180 / np.pi], ylim, 'k--')

        # plot diffraction peaks
        _, diff_tms = uvector2tmtp(diff_uvec_out[kk,..., 0], diff_uvec_out[kk, ..., :, 1], diff_uvec_out[kk, ..., :, 2])
        for ii in range(n_wavelens):
            plt.plot(np.array([diff_tms[ii], diff_tms[ii]]) * 180 / np.pi, ylim, color=colors[ii], ls='-')
        plt.plot(diff_tms[0, iz] * 180 / np.pi, diff_tms[0, iz] * 180 / np.pi, ylim, 'm')

        ax.set_ylim(ylim)
        ax.set_xlim([tms_blaze_on * 180 / np.pi - 7.5, tms_blaze_on * 180 / np.pi + 7.5])
        ax.set_xlabel(r'$\theta_m$ (deg)')
        ax.set_ylabel('intensity (arb)')
        ax.set_title('diffraction pattern')

        # ###########################
        # plot sinc functions and wider angular range
        # ###########################
        ax = plt.subplot(grid[0, 1])

        for ii in range(n_wavelens):
            plt.plot(tms_out * 180 / np.pi, scale_fn(np.abs(sinc_efield_on[kk, :, ii]/ wx / wy)**2),
                     color=colors[ii], ls=':', label="%.0f" % (1e9 * wavelengths[ii]))
            plt.plot(tms_out * 180 / np.pi, scale_fn(np.abs(sinc_efield_off[kk, :, ii] / wx / wy)**2), color=colors[ii], ls='--')

        # get xlim, ylim, set back to these at the end
        ylim = ax.get_ylim()
        xlim = ax.get_xlim()

        # plot expected blaze conditions
        plt.plot([tms_blaze_on * 180 / np.pi, tms_blaze_on * 180 / np.pi], ylim, 'k:', label="blaze on")
        plt.plot([tms_blaze_off * 180 / np.pi, tms_blaze_off * 180 / np.pi], ylim, 'k--', label="blaze off")

        # plot expected diffraction conditions
        for ii in range(n_wavelens):
            plt.plot(np.array([diff_tms[ii], diff_tms[ii]]) * 180 / np.pi, ylim, color=colors[ii], ls='-')
        plt.plot(diff_tms[0, iz] * 180 / np.pi, diff_tms[0, iz] * 180 / np.pi, ylim, 'm', label="0th diffraction order")
        ax.set_xlim(xlim)
        ax.set_ylim(ylim)

        plt.legend()
        ax.set_xlabel(r'$\theta_m$ (deg)')
        ax.set_ylabel('intensity (arb)')
        ax.set_title('blaze envelopes')

        # ###########################
        # plot pattern
        # ###########################
        plt.subplot(grid[1, 0])
        plt.imshow(pattern, origin="lower", cmap="bone")

        plt.title('DMD pattern')
        plt.xlabel('mx')
        plt.ylabel('my')

        # ###########################
        # add figure to list
        # ###########################
        fname = 'dmd_sim_theta_in=%0.3fdeg' % (tm_in * 180 / np.pi)
        fig_names.append(fname)
        figs.append(figh)

        # ###########################
        # saving
        # ###########################
        if save_dir is not None:
            fname = os.path.join(save_dir, fname + '.png')
            figh.savefig(fname)
            plt.close(figh)

    return figs, fig_names


# 2D simulation
def simulate_2d(pattern, wavelengths, gamma_on, gamma_off, dx, dy, wx, wy, tx_in, ty_in, tout_offsets=None,
                ndiff_orders=7):
    """
    Simulate light incident on a DMD to determine output diffraction pattern. See simulate_dmd() for more information.

    Generally one wants to simulate many output angles but only a few input angles/wavelengths.

    :param pattern: binary pattern of arbitrary size
    :param wavelengths: list of wavelengths to compute
    :param gamma_on: mirror angle in ON position, relative to the DMD normal
    :param gamma_off:
    :param dx: spacing between DMD pixels in the x-direction. Same units as wavelength.
    :param dy: spacing between DMD pixels in the y-direction. Same units as wavelength.
    :param wx: width of mirrors in the x-direction. Must be < dx.
    :param wy: width of mirrors in the y-direction. Must be < dy.
    :param tx_in:
    :param ty_in:
    :param tout_offsets: offsets from the blaze condition to solve problem
    :return data: dictionary storing simulation results
    """

    if tout_offsets is None:
        tout_offsets = np.linspace(-25, 25, 50) * np.pi / 180
    txtx_out_offsets, tyty_out_offsets = np.meshgrid(tout_offsets, tout_offsets)

    if isinstance(wavelengths, float):
        wavelengths = [wavelengths]

    if isinstance(tx_in, (float, int)):
        tx_in = np.array([tx_in])
    if isinstance(ty_in, (float, int)):
        ty_in = np.array([ty_in])

    n_wavelens = len(wavelengths)

    # input directions
    txtx_in, tyty_in = np.meshgrid(tx_in, ty_in)
    uvecs_in = get_unit_vector(txtx_in, tyty_in, "in")

    # shape information
    input_shape = txtx_in.shape
    ninputs = np.prod(input_shape)
    output_shape = txtx_out_offsets.shape

    # store results
    efields = np.zeros((n_wavelens,) + input_shape + output_shape, dtype=complex)
    sinc_efield_on = np.zeros(efields.shape, dtype=complex)
    sinc_efield_off = np.zeros(efields.shape, dtype=complex)
    uvecs_out = np.zeros(input_shape + output_shape + (3,))
    # blaze condition predictions
    uvec_out_blaze_on = np.zeros(input_shape + (3,))
    uvec_out_blaze_off = np.zeros(input_shape + (3,))
    # diffraction order predictions
    diff_nx, diff_ny = np.meshgrid(range(-ndiff_orders, ndiff_orders + 1), range(-ndiff_orders, ndiff_orders + 1))
    uvec_out_diff = np.zeros((n_wavelens,) + input_shape + diff_nx.shape + (3,))

    for ii in range(ninputs):
        input_ind = np.unravel_index(ii, input_shape)

        # solve blaze condition (does not depend on wavelength)
        uvec_out_blaze_on[input_ind] = solve_blaze_output(uvecs_in[input_ind], gamma_on)
        uvec_out_blaze_off[input_ind] = solve_blaze_output(uvecs_in[input_ind], gamma_off)

        # get output directions
        tx_blaze_on, ty_blaze_on = uvector2txty(*uvec_out_blaze_on[input_ind])
        tx_outs = tx_blaze_on + txtx_out_offsets
        ty_outs = ty_blaze_on + tyty_out_offsets

        uvecs_out[input_ind] = get_unit_vector(tx_outs, ty_outs, mode="out")

        for kk in range(n_wavelens):
            # solve diffraction orders
            for aa in range(diff_nx.size):
                diff_ind = np.unravel_index(aa, diff_nx.shape)
                uvec_out_diff[kk][input_ind][diff_ind] = solve_diffraction_output(uvecs_in[input_ind], dx, dy,
                                                                                  wavelengths[kk], (diff_nx[diff_ind], diff_ny[diff_ind]))

            # solve diffracted fields
            efields[kk][input_ind], sinc_efield_on[kk][input_ind], sinc_efield_off[kk][input_ind], _ = \
                simulate_dmd(pattern, wavelengths[kk], gamma_on, gamma_off, dx, dy, wx, wy,
                             uvecs_in[input_ind], uvecs_out[input_ind])

    data = {'pattern': pattern, 'wavelengths': wavelengths,
            'gamma_on': gamma_on, 'gamma_off': gamma_off, 'dx': dx, 'dy': dy, 'wx': wx, 'wy': wy,
            'uvecs_in': uvecs_in, 'uvecs_out': uvecs_out,
            'uvec_out_blaze_on': uvec_out_blaze_on, 'uvec_out_blaze_off': uvec_out_blaze_off,
            'diff_uvec_out': uvec_out_diff, 'diff_nxs': diff_nx, 'diff_nys': diff_ny,
            'efields': efields, 'sinc_efield_on': sinc_efield_on, 'sinc_efield_off': sinc_efield_off}

    return data


def plot_2d_sim(data, save_dir='dmd_simulation', figsize=(18, 14), gamma=0.1):
    """
    Plot results from simulate_2d()

    :param dict data: dictionary object produced by simulate_2d()
    :param str save_dir:
    :param figsize:
    :return figs, fig_names:
    """

    # physical parameters
    pattern = data['pattern']
    ny, nx = pattern.shape
    wavelengths = data['wavelengths']
    dx = data['dx']
    dy = data['dy']
    wx = data['wx']
    wy = data['wy']
    gamma_on = data['gamma_on']
    gamma_off = data['gamma_off']

    # input directions
    uvecs_in = data["uvecs_in"]
    uvecs_out = data["uvecs_out"]
    uvecs_out_blaze_on = data["uvec_out_blaze_on"]
    uvecs_out_blaze_off = data["uvec_out_blaze_off"]

    # diffraction orders
    uvecs_out_diff = data["diff_uvec_out"]
    diff_nx = data['diff_nxs']
    diff_ny = data['diff_nys']
    iz = np.where(np.logical_and(diff_nx == 0, diff_ny == 0))

    # simulation results
    intensity = np.abs(data['efields'])**2
    sinc_on = np.abs(data["sinc_efield_on"])**2
    sinc_off = np.abs(data["sinc_efield_off"])**2

    # plot results
    figs = []
    fig_names = []

    input_shape = uvecs_in.shape[:-1]
    ninput = np.prod(input_shape)
    for kk in range(len(wavelengths)):
        for ii in range(ninput):
            input_ind = np.unravel_index(ii, input_shape)

            # compute all angles of interest
            tx_in, ty_in = uvector2txty(*uvecs_in[input_ind])
            tp_in, tm_in = angle2pm(tx_in, ty_in)
            tx_blaze_on, ty_blaze_on = uvector2txty(*uvecs_out_blaze_on[input_ind])
            tx_blaze_off, ty_blaze_off = uvector2txty(*uvecs_out_blaze_off[input_ind])
            diff_tx_out, diff_ty_out = uvector2txty(uvecs_out_diff[kk][input_ind][..., 0],
                                                    uvecs_out_diff[kk][input_ind][..., 1],
                                                    uvecs_out_diff[kk][input_ind][..., 2])

            param_str = 'wavelength=%dnm, dx=%0.2fum, w=%0.2fum, gamma (on,off)=(%.2f,%.2f) deg\n' \
                        'input (tx,ty)=(%.2f, %.2f)deg (m,p)=(%0.2f, %.2f)deg\n' \
                        'input unit vector = (%0.4f, %0.4f, %0.4f)' % \
                        (int(wavelengths[kk] * 1e9), dx * 1e6, wx * 1e6,
                         gamma_on * 180 / np.pi, gamma_off * 180 / np.pi,
                         tx_in * 180 / np.pi, ty_in * 180 / np.pi,
                         tm_in * 180 / np.pi, tp_in * 180/np.pi,
                         uvecs_in[input_ind][0], uvecs_in[input_ind][1], uvecs_in[input_ind][2])

            tx_out, ty_out = uvector2txty(uvecs_out[input_ind][..., 0], uvecs_out[input_ind][..., 1], uvecs_out[input_ind][..., 2])
            dtout = tx_out[0, 1] - tx_out[0, 0]
            extent = [(tx_out.min() - 0.5 * dtout) * 180/np.pi,
                      (tx_out.max() + 0.5 * dtout) * 180/np.pi,
                      (ty_out.min() - 0.5 * dtout) * 180/np.pi,
                      (ty_out.max() + 0.5 * dtout) * 180/np.pi]

            # Fourier plane positions, assuming that diffraction order closest to blaze condition
            # is along the optical axis
            diff_ind = np.nanargmin(np.linalg.norm(uvecs_out_diff[kk][input_ind] - uvecs_out_blaze_on[input_ind], axis=-1))
            diff_2d_ind = np.unravel_index(diff_ind, uvecs_out_diff[kk][input_ind].shape[:-1])

            # get fourier plane positions for intensity output angles
            opt_axis = uvecs_out_diff[kk][input_ind][diff_2d_ind]
            fx, fy = uvec2freq(opt_axis, uvecs_out[input_ind], wavelengths[kk], dx, dy)
            xf, yf, _ = dmd_frqs2fourier_plane(fx, fy, opt_axis, opt_axis, dx, dy, wavelengths[kk])

            # get fourier plane positions for blaze conditions
            fx_blaze_on, fy_blaze_on = uvec2freq(opt_axis, uvecs_out_blaze_on[input_ind], wavelengths[kk], dx, dy)
            xf_blaze_on, yf_blaze_on, _ = dmd_frqs2fourier_plane(fx_blaze_on, fy_blaze_on, opt_axis, opt_axis, dx, dy, wavelengths[kk])

            fx_blaze_off, fy_blaze_off = uvec2freq(opt_axis, uvecs_out_blaze_off[input_ind], wavelengths[kk], dx, dy)
            xf_blaze_off, yf_blaze_off, _ = dmd_frqs2fourier_plane(fx_blaze_off, fy_blaze_off, opt_axis, opt_axis, dx, dy, wavelengths[kk])

            # get fourier plane positions for diffraction peaks
            fx_diff, fy_diff = uvec2freq(opt_axis, uvecs_out_diff[kk][input_ind], wavelengths[kk], dx, dy)
            xf_diff, yf_diff, _ = dmd_frqs2fourier_plane(fx_diff, fy_diff, opt_axis, opt_axis, dx, dy, wavelengths[kk])

            fig = plt.figure(figsize=figsize)
            grid = plt.GridSpec(2, 3)
            plt.suptitle(param_str)

            # ##################
            # intensity patterns, angular space
            # ##################
            ax = plt.subplot(grid[0, 0])
            ax.set_xlabel(r'$\theta_x$ outgoing (deg)')
            ax.set_ylabel(r'$\theta_y$ outgoing (deg)')
            ax.set_title('I / (wx*wy*nx*ny)**2 vs. output angle')

            ax.imshow(intensity[kk][input_ind] / (dx*dy*nx*ny)**2, extent=extent, norm=PowerNorm(gamma=gamma),
                       cmap="bone", origin="lower")
            # get xlim and ylim, we will want to keep these...
            xlim = ax.get_xlim()
            ylim = ax.get_ylim()

            # blaze condition
            ax.add_artist(Circle((tx_blaze_on * 180 / np.pi, ty_blaze_on * 180 / np.pi),
                           radius=1, color='r', fill=0, ls='-'))

            ax.add_artist(Circle((tx_blaze_off * 180 / np.pi, ty_blaze_off * 180 / np.pi),
                           radius=1, color='g', fill=0, ls='-'))

            # diffraction peaks
            ax.scatter(diff_tx_out * 180 / np.pi, diff_ty_out * 180 / np.pi, edgecolor='y', facecolor='none')
            # diffraction zeroth order
            ax.scatter(diff_tx_out[iz] * 180 / np.pi, diff_ty_out[iz] * 180 / np.pi, edgecolor='m', facecolor='none')

            ax.set_xlim(xlim)
            ax.set_ylim(ylim)

            # ##################
            # intensity patterns, fourier plane
            # ##################
            ax = plt.subplot(grid[1, 0])
            ax.set_xlabel(r'$x$ (1 / lens focal len um)')
            ax.set_ylabel(r'$y$ (1 / lens focal len um)')
            ax.set_title('I / (wx*wy*nx*ny)**2 (fourier plane)')
            ax.axis("equal")

            ax.set_facecolor("k")
            ax.scatter(xf, yf, c=intensity[kk][input_ind] / (dx * dy * nx * ny) ** 2,
                       cmap="bone", norm=PowerNorm(gamma=gamma))

            # get xlim and ylim, we will want to keep these...
            xlim = ax.get_xlim()
            ylim = ax.get_ylim()

            # blaze condition
            ax.add_artist(Circle((xf_blaze_on, yf_blaze_on), radius=0.02, color='r', fill=0, ls='-'))

            ax.add_artist(Circle((xf_blaze_off, yf_blaze_off), radius=0.02, color='g', fill=0, ls='-'))

            # diffraction peaks
            ax.scatter(xf_diff, yf_diff, edgecolor='y', facecolor='none')
            # diffraction zeroth order
            ax.scatter(xf_diff[iz], yf_diff[iz], edgecolor='m', facecolor='none')

            # rest bounds
            ax.set_xlim(xlim)
            ax.set_ylim(ylim)

            # ##################
            # blaze envelopes
            # ##################
            ax = plt.subplot(grid[0, 1])
            ax.set_xlabel(r'$\theta_x$ outgoing')
            ax.set_ylabel(r'$\theta_y$ outgoing')
            ax.set_title('blaze condition sinc envelope (angular)')

            plt.imshow(sinc_on[kk][input_ind] / (wx*wy)**2, extent=extent,
                       norm=PowerNorm(gamma=1), cmap="bone", origin="lower")
            xlim = ax.get_xlim()
            ylim = ax.get_ylim()

            # blaze condition
            ax.add_artist(Circle((tx_blaze_on * 180 / np.pi, ty_blaze_on * 180 / np.pi),
                                 radius=1, color='r', fill=0, ls='-'))

            ax.add_artist(Circle((tx_blaze_off * 180 / np.pi, ty_blaze_off * 180 / np.pi),
                                 radius=1, color='g', fill=0, ls='-'))

            # diffraction peaks
            plt.scatter(diff_tx_out * 180 / np.pi, diff_ty_out * 180 / np.pi, edgecolor='y', facecolor='none')
            # diffraction zeroth order
            plt.scatter(diff_tx_out[iz] * 180 / np.pi, diff_ty_out[iz] * 180 / np.pi, edgecolor='m', facecolor='none')

            ax.set_xlim(xlim)
            ax.set_ylim(ylim)

            # ##################
            # blaze envelope, fourier plane
            # ##################
            ax = plt.subplot(grid[1, 1])
            ax.set_xlabel(r'$x$ (1 / lens focal len um)')
            ax.set_ylabel(r'$y$ (1 / lens focal len um)')
            ax.set_title('blaze condition sinc envelope (fourier plane)')
            ax.axis("equal")
            ax.set_facecolor("k")
            ax.scatter(xf, yf, c=sinc_on[kk][input_ind] / (wx*wy)**2, cmap="bone", norm=PowerNorm(gamma=1))
            # get xlim and ylim, we will want to keep these...
            xlim = ax.get_xlim()
            ylim = ax.get_ylim()

            # blaze condition
            ax.add_artist(Circle((xf_blaze_on, yf_blaze_on), radius=0.02, color='r', fill=0, ls='-'))

            ax.add_artist(Circle((xf_blaze_off, yf_blaze_off), radius=0.02, color='g', fill=0, ls='-'))

            # diffraction peaks
            ax.scatter(xf_diff, yf_diff, edgecolor='y', facecolor='none')
            # diffraction zeroth order
            ax.scatter(xf_diff[iz], yf_diff[iz], edgecolor='m', facecolor='none')

            ax.set_xlim(xlim)
            ax.set_ylim(ylim)

            # ##################
            # DMD pattern
            # ##################
            ax = plt.subplot(grid[0, 2])
            ax.set_title('DMD pattern')
            ax.set_xlabel("x-position (mirrors)")
            ax.set_xlabel("y-position (mirrors)")

            ax.imshow(pattern, origin="lower", cmap="bone")

            fname = 'tx_in=%0.2f_ty_in=%0.2f_wl=%.0fnm.png' % (tx_in, ty_in, int(wavelengths[kk] * 1e9))
            figs.append(fig)
            fig_names.append(fname)

            # ##################
            # save results
            # ##################
            if save_dir is not None:
                if not os.path.exists(save_dir):
                    os.mkdir(save_dir)

                fpath = os.path.join(save_dir, fname)
                fig.savefig(fpath)

    return figs, fig_names


def simulate_2d_angles(wavelengths, gamma, dx, dy, tx_ins, ty_ins, ndiff_orders=15):
    """
    Determine Blaze and diffraction angles in 2D for provided input angles. For each input angle, identify the
    diffraction order which is closest to the blaze condition.

    In practice, want to use different input angles, but keep output angle fixed.
    Want to sample output angles...

    :param list[float] wavelengths: list of wavelength, in um
    :param float gamma: micromirror angle in "on" position, in radians
    :param float dx: x-mirror pitch, in microns
    :param float dy: y-mirror pitch, in microns
    :param tx_ins: NumPy array of input angles. Output results will simulate all combinations of x- and y- input angles
    :param ty_ins: NumPy array of output angles.
    :param int ndiff_orders:

    :return data: dictionary object containing simulation results
    """

    if isinstance(wavelengths, float):
        wavelengths = [wavelengths]

    n_wavelens = len(wavelengths)

    # diffraction orders to compute
    nxs, nys = np.meshgrid(range(-ndiff_orders, ndiff_orders + 1), range(-ndiff_orders, ndiff_orders + 1))

    # input angles
    txtx_in, tyty_in = np.meshgrid(tx_ins, ty_ins)
    uvec_in = get_unit_vector(txtx_in, tyty_in, mode="in")

    # get output angles
    uvec_out_diff = np.zeros((n_wavelens, txtx_in.shape[0], txtx_in.shape[1], 2 * ndiff_orders + 1, 2 * ndiff_orders + 1, 3))
    uvecs_out_blaze = np.zeros(txtx_in.shape + (3,))
    # loop over input angles
    for ii in range(txtx_in.size):
        ind = np.unravel_index(ii, txtx_in.shape)
        uvecs_out_blaze[ind] = solve_blaze_output(uvec_in[ind], gamma)

        # loop over wavelengths
        for jj in range(n_wavelens):
            # loop over diffraction orders
            for aa in range(nxs.shape[0]):
                for bb in range(nys.shape[1]):
                    uvec_out_diff[jj][ind][aa, bb] = solve_diffraction_output(uvec_in, dx, dy, wavelengths[jj],
                                                                              order=(nxs[aa, bb], nys[aa, bb]))

    data = {'wavelengths': wavelengths, 'gamma': gamma, 'dx': dx, 'dy': dy,
            'uvecs_in': uvec_in, 'uvecs_out_blaze': uvecs_out_blaze, 'diff_uvec_out': uvec_out_diff
            }

    return data


def interactive_display_2d(wavelengths, gamma, dx, max_diff_order=7, colors=None, angle_increment=0.1, figsize=(16, 8)):
    """
    Create manipulatable plot to explore DMD diffraction for different input angles in several colors

    :param wavelengths: list of wavelengths (in um)
    :param gamma: DMD mirror angle in radians
    :param dx: DMD mirror pitch (in um)
    :param max_diff_order: maximum diffraction order to simulate
    :param colors: list of colors to plot various wavelengths in
    :param angle_increment: angle increment for sliders, in degrees
    :param figsize:
    :return figh:
    """
    # turn interactive mode off, or have problems with plot freezing
    plt.ioff()

    if not isinstance(wavelengths, list):
        wavelengths = list(wavelengths)
    n_wavelens = len(wavelengths)

    if colors is None:
        cmap = matplotlib.cm.get_cmap('jet')
        if n_wavelens > 1:
            colors = [cmap(ii / (n_wavelens - 1)) for ii in range(n_wavelens)]
        else:
            colors = ["k"]

    # diffraction orders to compute
    norders = 2 * max_diff_order + 1
    nxs, nys = np.meshgrid(range(-max_diff_order, max_diff_order + 1), range(-max_diff_order, max_diff_order + 1))

    # plot showing diffraction orders for each input angle, with a moveable slider
    figh = plt.figure(figsize=figsize)
    plt.suptitle("Diffraction output and blaze condition versus input angle")

    # build sliders
    axcolor = 'lightgoldenrodyellow'
    slider_axes_x = []
    sliders_x = []
    slider_axes_y = []
    sliders_y = []
    slider_height = 0.03
    slider_width = 0.65
    slider_hspace = 0.02
    slider_hstart = 0.1
    for ii in range(n_wavelens):
        slider_axes_x.append(plt.axes([0.5 * (1 - slider_width), slider_hstart + 2 * ii * (slider_hspace + slider_height), slider_width, slider_height], facecolor=axcolor))
        sliders_x.append(matplotlib.widgets.Slider(slider_axes_x[ii], 'tx in %dnm' % (wavelengths[ii] * 1e3), -90, 90, valinit=0, valstep=angle_increment))

        slider_axes_y.append(plt.axes([0.5 * (1 - slider_width), slider_hstart + (2 * ii + 1) * (slider_hspace + slider_height), slider_width, slider_height], facecolor=axcolor))
        sliders_y.append(matplotlib.widgets.Slider(slider_axes_y[ii], 'ty in %dnm' % (wavelengths[ii] * 1e3), -90, 90, valinit=0, valstep=angle_increment))

    # plt.subplots_adjust(left=0.25, bottom=0.25)

    # build main axis
    # [left, bottom, width, height]
    hsep = 0.05
    ax = plt.axes([0.2, slider_hstart + (2 * n_wavelens + 1) * (slider_hspace + slider_height) + hsep, 0.6, 0.4])

    # function called when sliders are moved on plot
    def update(val):
        ax.clear()

        # plot along main line
        ax.plot([-90, 90], [90, -90], 'k')
        # get slider values and plot diffraction orders
        for jj in range(n_wavelens):
            # read input angles from sliders
            tx_in = sliders_x[jj].val * np.pi/180
            ty_in = sliders_y[jj].val * np.pi/180
            uvec_in = get_unit_vector(tx_in, ty_in, mode="in")

            # solve diffraction output
            uvec_out_diff = np.zeros((norders, norders, 3))
            for aa in range(norders):
                for bb in range(norders):
                    uvec_out_diff[aa, bb] = solve_diffraction_output(uvec_in, dx, dx, wavelengths[jj],
                                                                     order=(nxs[aa, bb], nys[aa, bb]))

            tx_out_diff, ty_out_diff = uvector2txty(uvec_out_diff[..., 0], uvec_out_diff[..., 1], uvec_out_diff[..., 2])
            ax.scatter(tx_out_diff.ravel() * 180 / np.pi, ty_out_diff.ravel() * 180 / np.pi,
                       edgecolor=colors[jj], facecolor='none')

            # solve blaze output for gamma
            uvec_out_blaze_on = solve_blaze_output(uvec_in, gamma)
            tx_out, ty_out = uvector2txty(*uvec_out_blaze_on.squeeze())
            ax.scatter(tx_out * 180 / np.pi, ty_out * 180 / np.pi, color=colors[jj])

            # solve blaze output for -gamma
            uvec_out_blaze_off = solve_blaze_output(uvec_in, -gamma)
            tx_out, ty_out = uvector2txty(*uvec_out_blaze_off.squeeze())
            ax.scatter(tx_out * 180 / np.pi, ty_out * 180 / np.pi, marker='x', color=colors[jj])

        ax.set_xlabel('tx out (deg)')
        ax.set_ylabel('ty out (deg)')
        ax.set_xlim([-90, 90])
        ax.set_ylim([-90, 90])

        figh.canvas.draw_idle()

    for txs in sliders_x:
        txs.on_changed(update)
    for tys in sliders_y:
        tys.on_changed(update)

    # call once to ensure displays something
    update(0)

    plt.show()

    return figh
