"""spec2nii module containing functions specific to interpreting various formats
Contains text and LCModel formats.
Author: William Clarke <william.clarke@ndcn.ox.ac.uk>
Copyright (C) 2020 University of Oxford
"""
import numpy as np
from spec2nii.nifti_orientation import NIFTIOrient
from spec2nii import nifti_mrs
from datetime import datetime
from os.path import basename, splitext


def text(args):
    '''Processing for simple ascii formatted columns of data.'''
    # Read text from file
    data = np.loadtxt(args.file)
    data = data[:, 0] + 1j * data[:, 1]

    newshape = (1, 1, 1) + data.shape
    data = data.reshape(newshape)

    # Interpret required arguments (frequency and bandwidth)
    dwelltime = 1.0 / args.bandwidth

    meta = nifti_mrs.hdr_ext(args.imagingfreq,
                             args.nucleus)

    meta.set_standard_def('ConversionMethod', 'spec2nii')
    conversion_time = datetime.now().isoformat(sep='T', timespec='milliseconds')
    meta.set_standard_def('ConversionTime', conversion_time)
    meta.set_standard_def('OriginalFile', [basename(args.file), ])

    # Read optional affine file
    if args.affine:
        affine = np.loadtxt(args.affine)
    else:
        tmp = np.array([10000, 10000, 10000, 1])
        affine = np.diag(tmp)

    nifti_orientation = NIFTIOrient(affine)

    img_out = [nifti_mrs.NIfTI_MRS(data,
                                   nifti_orientation.Q44,
                                   dwelltime,
                                   meta), ]

    # File names
    if args.fileout:
        fname_out = [args.fileout, ]
    else:
        fname_out = [splitext(basename(args.file))[0], ]

    # Place in data output format
    return img_out, fname_out


def lcm_raw(args):
    '''Processing for LCModel .RAW (and .H2O) files.
    Currently only handles one FID per file.
    '''
    # Read data from file
    data, header = readLCModelRaw(args.file, conjugate=True)

    newshape = (1, 1, 1) + data.shape
    data = data.reshape(newshape)

    # meta
    dwelltime = header['dwelltime']

    meta = nifti_mrs.hdr_ext(header['centralFrequency'],
                             args.nucleus)

    meta.set_standard_def('ConversionMethod', 'spec2nii')
    conversion_time = datetime.now().isoformat(sep='T', timespec='milliseconds')
    meta.set_standard_def('ConversionTime', conversion_time)
    meta.set_standard_def('OriginalFile', [basename(args.file), ])

    # Read optional affine file
    if args.affine:
        affine = np.loadtxt(args.affine)
    else:
        tmp = np.array([10000, 10000, 10000, 1])
        affine = np.diag(tmp)

    nifti_orientation = NIFTIOrient(affine)

    img_out = [nifti_mrs.NIfTI_MRS(data,
                                   nifti_orientation.Q44,
                                   dwelltime,
                                   meta), ]

    # File names
    if args.fileout:
        fname_out = [args.fileout, ]
    else:
        fname_out = [splitext(basename(args.file))[0], ]

    # Place in data output format
    return img_out, fname_out


def readLCModelRaw(filename, conjugate=True):
    """
    Read .RAW (or.H2O) format file
    Parameters
    ----------
    filename : string
        Name of .RAW file

    Returns
    -------
    array-like
        Complex data
    dict
        Header information

    """
    header = []
    data   = []
    in_header = False
    with open(filename, 'r') as f:
        for line in f:
            if (line.find('$') > 0):
                in_header = True
            if in_header:
                header.append(line)
            else:
                data.append(list(map(float, line.split())))

            if line.find('$END') > 0:
                in_header = False

    # Reshape data
    data = np.concatenate([np.array(i) for i in data])
    data = (data[0::2] + 1j * data[1::2]).astype(np.complex)

    # LCModel-specific conjugation
    if conjugate:
        data = np.conj(data)

    # Tidy header info
    header = unpackHeader(header)

    return data, header


def unpackHeader(header):
    """
       Extracts useful info from header into dict

       Including central frequency, dwelltime, echotime
    """

    def tidy(x):
        return x.lower().replace(',', '')

    tidy_header = dict()
    tidy_header['centralFrequency'] = None
    tidy_header['bandwidth'] = None
    tidy_header['echotime'] = None
    for line in header:
        if line.lower().find('hzpppm') > 0:
            tidy_header['centralFrequency'] = float(tidy(line).split()[-1]) * 1E6
        if line.lower().find('dwelltime') > 0:
            tidy_header['dwelltime'] = float(tidy(line).split()[-1])
            tidy_header['bandwidth'] = 1 / float(tidy(line).split()[-1])
        if line.lower().find('deltat') > 0:
            tidy_header['dwelltime'] = float(tidy(line).split()[-1])
            tidy_header['bandwidth'] = 1 / float(tidy(line).split()[-1])
        if line.lower().find('echot') > 0:
            tidy_header['echotime'] = float(tidy(line).split()[-1]) / 1e3
        if line.lower().find('badelt') > 0:
            tidy_header['dwelltime'] = float(tidy(line).split()[-1])
            tidy_header['bandwidth'] = 1 / float(tidy(line).split()[-1])

    return tidy_header
