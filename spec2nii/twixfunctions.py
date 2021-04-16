""" spec2nii module containing functions specific to Siemens TWIX format
Author: William Clarke <william.clarke@ndcn.ox.ac.uk>
Copyright (C) 2020 University of Oxford
"""
import spec2nii.GSL.gslfunctions as GSL
import numpy as np
from spec2nii.dcm2niiOrientation.orientationFuncs import dcm_to_nifti_orientation
from spec2nii import nifti_mrs
from datetime import datetime
from os.path import basename
from spec2nii import __version__ as spec2nii_ver


# Define some default dimension information.
# Default spatial x,y,z is Lin, Phs, Seg in VB but in VE it is Lin, Par, Seg
# In VB set is used as the repetition direction, whilst in VE Ave is used.
# However it appears some CMRR sequences on VE still use the VB.
defaults = {'vb': {'Col': 'time',
                   'Lin': 'x',
                   'Phs': 'y',
                   'Seg': 'z',
                   'Cha': 'DIM_COIL',
                   'Set': 'DIM_DYN',
                   'Rep': 'DIM_DYN'},
            'vd': {'Col': 'time',
                   'Lin': 'x',
                   'Par': 'y',
                   'Seg': 'z',
                   'Cha': 'DIM_COIL',
                   'Ave': 'DIM_DYN',
                   'Set': 'DIM_DYN',
                   'Rep': 'DIM_DYN',
                   'Eco': 'DIM_EDIT'}}


def process_twix(twixObj, base_name_out, name_in, dataKey, dim_overides, quiet=False, verbose=False):
    """Process a twix file. Identify type of MRS and then pass to the relavent function."""

    if twixObj.hdr.Meas.lFinalMatrixSizePhase \
            and twixObj.hdr.Meas.lFinalMatrixSizeRead:
        n_voxels = twixObj.hdr.Meas.lFinalMatrixSizeSlice \
            * twixObj.hdr.Meas.lFinalMatrixSizePhase \
            * twixObj.hdr.Meas.lFinalMatrixSizeRead
    elif twixObj.hdr.Meas.lFinalMatrixSizeSlice:
        n_voxels = twixObj.hdr.Meas.lFinalMatrixSizeSlice
    else:
        # If lFinalMatrixSize{Slice,Phase,Read} are all empty
        # Either unlocalised or unusually filled in headers.
        # Assume 1 voxel for either SVS or unlocalised case.
        # RM's SPECIAL sequence hits this. See https://github.com/wexeee/spec2nii/issues/6.
        n_voxels = 1

    if n_voxels > 1:
        return process_mrsi(twixObj, base_name_out, name_in, dataKey, quiet=quiet, verbose=verbose)
    else:
        return process_svs(twixObj, base_name_out, name_in, dataKey, dim_overides, quiet=quiet, verbose=verbose)


def process_mrsi(twixObj, base_name_out, name_in, dataKey, quiet=False, verbose=False):
    """Identify correct MRSI pathway, either simple internal reconstruction or to ismrmrd"""
    raise NotImplementedError('MRSI pathway not yet implemented.')


def process_svs(twixObj, base_name_out, name_in, dataKey, dim_overides, quiet=False, verbose=False):
    """Process a twix file into a NIfTI MRS file.
    Inputs:
        twixObj: object from mapVBVD.
        base_name_out: Core string of output file.
        name_in: name of input file.
        dataKey: eval info flag name,
        quire: True to suppress text output.
    """

    # Set squeeze data
    twixObj[dataKey].flagRemoveOS = False
    twixObj[dataKey].squeeze = True
    squeezedData = twixObj[dataKey]['']

    if not quiet:
        print(f'Found data of size {squeezedData.shape}.')

    # Conjugate the data from the twix file to match the phase conventions of the format
    squeezedData = squeezedData.conj()

    # Perform Orientation calculations
    # 1) Calculate dicom like imageOrientationPatient,imagePositionPatient,pixelSpacing and slicethickness
    orient = twix2DCMOrientation(twixObj['hdr'], verbose=verbose)
    imageOrientationPatient, imagePositionPatient, pixelSpacing, slicethickness = orient

    # 2) In the style of dcm2niix calculate the affine matrix
    orientation = dcm_to_nifti_orientation(imageOrientationPatient,
                                           imagePositionPatient,
                                           np.append(pixelSpacing, slicethickness),
                                           (1, 1, 1),
                                           verbose=verbose)

    # # 2) in style of dcm2niix
    # #   a) calculate Q44
    # xyzMM = np.append(pixelSpacing, slicethickness)
    # Q44 = nifti_dicom2mat(imageOrientationPatient, imagePositionPatient, xyzMM, verbose=verbose)

    # #   b) calculate nifti quaternion parameters
    # Q44[:2, :] *= -1

    # # 3) place in data class for nifti orientation parameters
    # orientation = NIFTIOrient(Q44)

    # Extract dwellTime
    dwellTime = twixObj['hdr']['MeasYaps'][('sRXSPEC', 'alDwellTime', '0')] / 1E9

    # Extract metadata
    meta_obj = extractTwixMetadata(twixObj['hdr'], basename(twixObj[dataKey].filename))

    # Identify what those indicies are
    # If cha is one: loop over 3rd and higher dims and make 2D images
    # If cha isn't present one: loop over 2nd and higher dims and make 1D images
    # Don't write here, just fill up class property lists for later writing
    if base_name_out:
        mainStr = base_name_out
    else:
        mainStr = name_in.split('.')[0]

    dims = twixObj[dataKey].sqzDims
    if dims[0] != 'Col':
        # This is very unlikely to occur but would cause complete failure.
        raise ValueError('Col is expected to be the first dimension in the Twix file, it is not.')

    curr_defaults = defaults[twixObj[dataKey].softwareVersion]

    dim_order = twixObj[dataKey].sqzDims[1:]
    dim_tags = []
    unknown_counter = 0
    for do in dim_order:
        if do in curr_defaults.keys():
            dim_tags.append(curr_defaults[do])
        else:
            dim_tags.append(f'DIM_USER_{unknown_counter}')
            unknown_counter += 1

    # Now process the user specified order
    for dim_index in range(3):
        if dim_overides['dims'][dim_index]:
            if dim_overides['dims'][dim_index] in dim_order:
                curr_index = dim_order.index(dim_overides['dims'][dim_index])
                dim_order[dim_index], dim_order[curr_index] = dim_order[curr_index], dim_order[dim_index]
                dim_tags[dim_index], dim_tags[curr_index] = dim_tags[curr_index], dim_tags[dim_index]
            else:
                dim_order.insert(dim_index, dim_overides['dims'][0])
                if dim_overides['dims'][dim_index] in curr_defaults.keys():
                    dim_tags.insert(dim_index, curr_defaults['tags'][dim_overides['dims'][dim_index]])
                else:
                    dim_tags.insert(dim_index, f'DIM_USER_{unknown_counter}')
                    unknown_counter += 1

    # Override with any of the specified tags
    for idx, tag in enumerate(dim_overides['tags']):
        if tag:
            dim_tags[idx] = tag

    # Permute the order of dimension in the data
    orignal = list(range(1, squeezedData.ndim))
    new = [twixObj[dataKey].sqzDims.index(dd) for dd in dim_order]
    reord_data = np.moveaxis(squeezedData, orignal, new)

    # Now assemble data
    nifit_mrs_out = []
    filename_out = []
    if reord_data.ndim <= 4:
        # Pad with three singleton dimensions (x,y,z)
        newshape = (1, 1, 1) + reord_data.shape

        nifit_mrs_out.append(assemble_nifti_mrs(reord_data.reshape(newshape),
                                                dwellTime,
                                                orientation,
                                                meta_obj,
                                                dim_tags))

        filename_out.append(mainStr)

    else:
        # loop over any dimensions over 4
        for index in np.ndindex(reord_data.shape[4:]):
            modIndex = (slice(None), slice(None), slice(None), slice(None)) + index

            # Pad with three singleton dimensions (x,y,z)
            newshape = (1, 1, 1) + reord_data[modIndex].shape

            nifit_mrs_out.append(
                assemble_nifti_mrs(reord_data[modIndex].reshape(newshape),
                                   dwellTime,
                                   orientation,
                                   meta_obj,
                                   dim_tags))

            # Create strings
            out_name = f'{mainStr}'
            for idx, ii in enumerate(index):
                indexStr = dim_order[3 + idx]
                out_name += f'_{indexStr}{ii :03d}'

            filename_out.append(out_name)

    return nifit_mrs_out, filename_out


def assemble_nifti_mrs(data, dwellTime, orientation, meta_obj, dim_tags):

    for idx, dt in zip(range(data.ndim - 4), dim_tags):
        meta_obj.set_dim_info(idx, dt)

    return nifti_mrs.NIfTI_MRS(data, orientation.Q44, dwellTime, meta_obj)


def twix2DCMOrientation(mapVBVDHdr, verbose=False):
    """ Convert twix orientation information to DICOM equivalent.

    Convert orientation to DICOM imageOrientationPatient, imagePositionPatient,
    pixelSpacing and sliceThickness field values.

    Args:
        mapVBVDHdr (dict): Header info interpreted by pymapVBVD
        verbose (bool,optionl)
    Returns:
        imageOrientationPatient
        imagePositionPatient
        pixelSpacing
        sliceThickness

    """
    # Orientation information
    if ('sSpecPara', 'sVoI', 'sNormal', 'dSag') in mapVBVDHdr['MeasYaps']:
        NormaldSag = mapVBVDHdr['MeasYaps'][('sSpecPara', 'sVoI', 'sNormal', 'dSag')]
    else:
        NormaldSag = 0.0

    if ('sSpecPara', 'sVoI', 'sNormal', 'dCor') in mapVBVDHdr['MeasYaps']:
        NormaldCor = mapVBVDHdr['MeasYaps'][('sSpecPara', 'sVoI', 'sNormal', 'dCor')]
    else:
        NormaldCor = 0.0

    if ('sSpecPara', 'sVoI', 'sNormal', 'dTra') in mapVBVDHdr['MeasYaps']:
        NormaldTra = mapVBVDHdr['MeasYaps'][('sSpecPara', 'sVoI', 'sNormal', 'dTra')]
    else:
        NormaldTra = 0.0

    if ('sSpecPara', 'sVoI', 'dInPlaneRot') in mapVBVDHdr['MeasYaps']:
        inplaneRotation = mapVBVDHdr['MeasYaps'][('sSpecPara', 'sVoI', 'dInPlaneRot')]
    else:
        inplaneRotation = 0.0

    TwixSliceNormal = np.array([NormaldSag, NormaldCor, NormaldTra], dtype=float)

    RoFoV = mapVBVDHdr['MeasYaps'][('sSpecPara', 'sVoI', 'dReadoutFOV')]
    PeFoV = mapVBVDHdr['MeasYaps'][('sSpecPara', 'sVoI', 'dPhaseFOV')]

    dColVec_vector, dRowVec_vector = GSL.calc_prs(TwixSliceNormal, inplaneRotation, verbose)

    imageOrientationPatient = np.stack((dRowVec_vector, dColVec_vector), axis=0)

    pixelSpacing = np.array([PeFoV, RoFoV])  # [RoFoV PeFoV];
    sliceThickness = mapVBVDHdr['MeasYaps'][('sSpecPara', 'sVoI', 'dThickness')]

    # Position info (including table position)
    if ('sSpecPara', 'sVoI', 'sPosition', 'dSag') in mapVBVDHdr['MeasYaps']:
        PosdSag = mapVBVDHdr['MeasYaps'][('sSpecPara', 'sVoI', 'sPosition', 'dSag')]
    else:
        PosdSag = 0.0

    if ('sSpecPara', 'sVoI', 'sPosition', 'dCor') in mapVBVDHdr['MeasYaps']:
        PosdCor = mapVBVDHdr['MeasYaps'][('sSpecPara', 'sVoI', 'sPosition', 'dCor')]
    else:
        PosdCor = 0.0

    if ('sSpecPara', 'sVoI', 'sPosition', 'dTra') in mapVBVDHdr['MeasYaps']:
        PosdTra = mapVBVDHdr['MeasYaps'][('sSpecPara', 'sVoI', 'sPosition', 'dTra')]
    else:
        PosdTra = 0.0

    if ('lScanRegionPosSag',) in mapVBVDHdr['MeasYaps']:
        PosdSag += mapVBVDHdr['MeasYaps'][('lScanRegionPosSag',)]
    if ('lScanRegionPosCor',) in mapVBVDHdr['MeasYaps']:
        PosdCor += mapVBVDHdr['MeasYaps'][('lScanRegionPosCor',)]
    if ('lScanRegionPosTra',) in mapVBVDHdr['MeasYaps']:
        PosdTra += mapVBVDHdr['MeasYaps'][('lScanRegionPosTra',)]

    basePosition = np.array([PosdSag, PosdCor, PosdTra], dtype=float)
    imagePositionPatient = basePosition
    if verbose:
        print(f'imagePositionPatient is {imagePositionPatient.ravel()}')
        print(f'imageOrientationPatient is \n{imageOrientationPatient}')
        print(f'{imageOrientationPatient.ravel()}')
        print(f'pixelSpacing is {pixelSpacing}')

    return imageOrientationPatient, imagePositionPatient, pixelSpacing, sliceThickness


def examineTwix(twixObj, fileName, mraid):
    """ Print formated twix contents"""

    print(f'Contents of file: {fileName}')

    if isinstance(twixObj, list):
        print(f'Multiraid file, {len(twixObj)} files found.')
        print(f'Selecting file {mraid}. Use -m option to change.')
        twixObj = twixObj[mraid - 1]

    evalInfoFlags = twixObj.keys()
    evalInfoFlags = [i for i in evalInfoFlags if i != 'hdr']

    print('The file contains these evalinfo flags with dimensions and sizes as follows:')
    for ev in evalInfoFlags:
        twixObj[ev].flagRemoveOS = False
        twixObj[ev].squeeze = True
        tmpSqzSize = twixObj[ev].sqzSize
        tmpSqzDims = ', '.join(twixObj[ev].sqzDims)
        print(f'{ev: <15}:\t{tmpSqzDims: <20}\t{tmpSqzSize}')


def extractTwixMetadata(mapVBVDHdr, orignal_file):
    """ Extract information from the pymapVBVD header to insert into the json sidecar.

    Args:
        dcmdata (dict): Twix headers
    Returns:
        obj (hdr_ext): NIfTI MRS hdr ext object.
    """

    # Extract required metadata and create hdr_ext object
    obj = nifti_mrs.hdr_ext(mapVBVDHdr['Meas'][('Frequency')] / 1E6,
                            mapVBVDHdr['Meas'][('ResonantNucleus')])

    # Standard defined metadata
    # # 5.1 MRS specific Tags
    # 'EchoTime'
    obj.set_standard_def('EchoTime', mapVBVDHdr['Phoenix'][('alTE', '0')] * 1E-6)
    # 'RepetitionTime'
    if ('TR_Time') in mapVBVDHdr['Meas']:
        tr = mapVBVDHdr['Meas'][('TR_Time')] / 1E6
    else:
        tr = mapVBVDHdr['Meas'][('TR')] / 1E6
    obj.set_standard_def('RepetitionTime', float(tr))
    # 'InversionTime'
    if ('InversionTime') in mapVBVDHdr['Meas']:
        obj.set_standard_def('InversionTime', float(mapVBVDHdr['Meas'][('TI_Time')]))
    # 'MixingTime'
    # 'ExcitationFlipAngle'
    obj.set_standard_def('ExcitationFlipAngle', float(mapVBVDHdr['Meas'][('FlipAngle')]))
    # 'TxOffset'
    obj.set_standard_def('TxOffset', empty_str_to_0float(mapVBVDHdr['Meas'][('dDeltaFrequency')]))
    # 'VOI'
    # 'WaterSuppressed'
    # TO DO
    # 'WaterSuppressionType'
    # 'SequenceTriggered'
    # # 5.2 Scanner information
    # 'Manufacturer'
    obj.set_standard_def('Manufacturer', mapVBVDHdr['Dicom'][('Manufacturer')])
    # 'ManufacturersModelName'
    obj.set_standard_def('ManufacturersModelName', mapVBVDHdr['Dicom'][('ManufacturersModelName')])
    # 'DeviceSerialNumber'
    obj.set_standard_def('DeviceSerialNumber', str(mapVBVDHdr['Dicom'][('DeviceSerialNumber')]))
    # 'SoftwareVersions'
    obj.set_standard_def('SoftwareVersions', mapVBVDHdr['Dicom'][('SoftwareVersions')])
    # 'InstitutionName'
    obj.set_standard_def('InstitutionName', mapVBVDHdr['Dicom'][('InstitutionName')])
    # 'InstitutionAddress'
    obj.set_standard_def('InstitutionAddress', mapVBVDHdr['Dicom'][('InstitutionAddress')])
    # 'TxCoil'
    # 'RxCoil'
    rx_coil_1 = ('sCoilSelectMeas', 'aRxCoilSelectData', '0', 'asList', '0', 'sCoilElementID', 'tCoilID')
    rx_coil_2 = ('asCoilSelectMeas', '0', 'asList', '0', 'sCoilElementID', 'tCoilID')
    if rx_coil_1 in mapVBVDHdr['MeasYaps']:
        obj.set_standard_def('RxCoil', mapVBVDHdr['MeasYaps'][rx_coil_1])
    elif rx_coil_2 in mapVBVDHdr['MeasYaps']:
        obj.set_standard_def('RxCoil', mapVBVDHdr['MeasYaps'][rx_coil_2])
    # # 5.3 Sequence information
    # 'SequenceName'
    obj.set_standard_def('SequenceName', mapVBVDHdr['Meas'][('tSequenceString')])
    # 'ProtocolName'
    obj.set_standard_def('ProtocolName', mapVBVDHdr['Dicom'][('tProtocolName')])
    # # 5.4 Sequence information
    # 'PatientPosition'
    obj.set_standard_def('PatientPosition', mapVBVDHdr['Meas'][('PatientPosition')])
    # 'PatientName'
    obj.set_standard_def('PatientName', mapVBVDHdr['Meas'][('PatientName')])
    # 'PatientID'
    # 'PatientWeight'
    obj.set_standard_def('PatientWeight', mapVBVDHdr['Meas'][('flUsedPatientWeight')])
    # 'PatientDoB'
    obj.set_standard_def('PatientDoB', str(mapVBVDHdr['Meas'][('PatientBirthDay')]))
    # 'PatientSex'
    if mapVBVDHdr['Meas'][('PatientSex')] == 1:
        sex_str = 'M'
    elif mapVBVDHdr['Meas'][('PatientSex')] == 2:
        sex_str = 'F'
    else:
        sex_str = 'O'
    obj.set_standard_def('PatientSex', sex_str)
    # # 5.5 Provenance and conversion metadata
    # 'ConversionMethod'
    obj.set_standard_def('ConversionMethod', f'spec2nii v{spec2nii_ver}')
    # 'ConversionTime'
    conversion_time = datetime.now().isoformat(sep='T', timespec='milliseconds')
    obj.set_standard_def('ConversionTime', conversion_time)
    # 'OriginalFile'
    obj.set_standard_def('OriginalFile', [orignal_file, ])
    # # 5.6 Spatial information
    # 'kSpace'
    obj.set_standard_def('kSpace', [False, False, False])

    # Some additional information
    obj.set_user_def(key='PulseSequenceFile',
                     value=mapVBVDHdr['Config'][('SequenceFileName')],
                     doc='Sequence binary path.')
    obj.set_user_def(key='IceProgramFile',
                     value=mapVBVDHdr['Meas'][('tICEProgramName')],
                     doc='Reconstruction binary path.')

    return obj


def empty_str_to_0float(value):
    if value == '':
        return 0.0
    else:
        return value


def _try_int(value):
    try:
        return int(value)
    except ValueError:
        return value
