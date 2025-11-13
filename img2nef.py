#!/usr/bin/env python3
"""
img2nef.py
This app converts image files into Nikon lossless compressed NEF raw files, which can then be used
anywhere Nikon raw files can be viewed and processed. Some uses for this include Nikon's in-camera
multi-exposure feature, which lets you specify an existing raw file as the first image of a
multi-exposure composite - using this app expands the possibilities of image files you can use as
the first image beyond just images taken with the camera. For example, you can use this feature to
implement custom framing guides by creating them in your favorite imaging app and then converting
them to NEF's for use in the camera's multi-exposure feature.

Creating NEFs from images is also useful for scientific and research purposes, for example in developing
and testing raw image development software

This app is written in both Python and 'C' - nefencode.c contains the optimized code to compress a bayered
image into Nikon's proprietary NEF lossless compression.

"""

#
# verify python version early, before executing any logic that relies on features not available in all versions
#
import sys
if (sys.version_info.major < 3) or (sys.version_info.minor < 10):
    print("Requires Python v3.10 or later but you're running v{}.{}.{}".format(sys.version_info.major, sys.version_info.minor, sys.version_info.micro))
    sys.exit(1)

#
# standard Python module imports
#
import argparse
import ctypes
from   dataclasses import dataclass
from   enum import Enum
from   functools import partial
import importlib
from   io import BytesIO
import math
import os
import platform
import re
import struct
import subprocess
import sys
import time
import types
from   typing import Any, Callable, List, NamedTuple, Tuple, Type


#
# types
#
class Alignment(Enum): CENTER=0; TOP=1; LEFT=2; BOTTOM=3; RIGHT=4
class ResizeGeom(Enum): NONE=0; MINIMUM=1; FULL=2
class IfFileExists(Enum): ADDSUFFIX=0; OVERWRITE=1; EXIT=2
class Verbosity(Enum): SILENT=0; WARNING=1; INFO=2; VERBOSE=3; DEBUG=4
class Endian(Enum): LITTLE=0; BIG=1
class OutputFilenameMethod(Enum): TEMPLATENEF_AND_INPUTFILE=0; TEMPLATENEF=1; INPUTFILE=2; NONE=3

Coordinate = NamedTuple('Coordinate', [('x', int), ('y', int)])
Dimensions = NamedTuple('Dimensions', [('columns', int), ('rows', int)])
Rect = NamedTuple('Rect', [('startx', int), ('starty', int), ('endx', int), ('endy', int)]) # ending values are exclusive
SrcGeomAdjustments = NamedTuple('SrcGeomAdjustments', [('resizeDimensions', Dimensions), ('posInTgt', Coordinate), ('cropRect', Rect)])
WhiteBalanceMultipliers = NamedTuple('WhiteBalanceMultipliers', [('red', float), ('blue', float)])
NikonCropArea = NamedTuple('NikonCropArea', [('left', int), ('top', int), ('columns', int), ('rows', int)])
EmbeddedJpgExifInfo = NamedTuple('EmbeddedJpg', [('exifName', str), ('start', int), ('length', int), ('offsetToLengthField', int)])


#
# module data
#
AppName = "img2nef"
AppVersion = "1.00"
ResizeAlgoNames = ['LANCZOS4', 'CUBIC', 'AREA', 'LINEAR', 'NEAREST']
AlignmentStrs = [x.name for x in Alignment]
ResizeGeomStrs = [x.name for x in ResizeGeom]
IfFileExistsStrs = [x.name for x in IfFileExists]
OutputFilenameMethodStrs = [x.name for x in OutputFilenameMethod]
VerbosityStrs = [x.name for x in Verbosity]
Config = types.SimpleNamespace()
ImgFloatType = "float32"
EmbeddedJpgExifNames = ["JpgFromRaw", "OtherImage", "PreviewImage", "Thumbnail"]

#
# verify all optional modules we need are installed before we attempt to import them.
# this allows us to display a user-friendly message for the missing modules instead of the
# python-generated error message for missing imports
#
if __name__ == "__main__":
    def verifyRequiredModulesInstalled():
        RequiredModule = NamedTuple('RequiredModule', [('importName', str), ('pipInstallName', str)])
        requiredModules = [
            RequiredModule(importName="cv2", pipInstallName="opencv-python"),
            RequiredModule(importName="PIL", pipInstallName="pillow"),
            RequiredModule(importName="numpy", pipInstallName="numpy"),
        ]
        missingModules = list()
        for requiredModule in requiredModules:
            try:
                importlib.import_module(requiredModule.importName)
            except ImportError:
                missingModules.append(requiredModule)
        if missingModules:
            print(f"Run the following commands to install required modules before using {AppName}:\n")
            for requiredModule in missingModules:
                print(f"\tpip install {requiredModule.pipInstallName}")
            print("")
            sys.exit(1)

    verifyRequiredModulesInstalled()


#
# import optional modules now we've established they're available
#
import cv2
from   PIL import Image, ImageDraw, ImageFont
import numpy as np


#
# methods to handle conditional printing based on user-specified verbosity level
#
def isVerbose() -> bool:
    return Config.args.verbosity.value >= Verbosity.VERBOSE.value
def printA(string: str): # print "always"
    print(string)
def printIfVerbosityAllows(string: str, requiredVerbosityLevel: Verbosity) -> None:
    if hasattr(Config, "args"):
        if Config.args.verbosity.value >= requiredVerbosityLevel.value:
            printA(string)
    else:
        # called before we've initialized Config.args
        printA(string)
def printE(string: str): # print error
    printA(f"ERROR: {string}")
def printW(string: str): # print warnings, if verbosity config allows
    printIfVerbosityAllows(f"WARNING: {string}", Verbosity.WARNING)
def printI(string: str): # print "informational" messages, if verbosity config allows
    printIfVerbosityAllows(f"INFO: {string}", Verbosity.INFO)
def printV(string: str): # print "verbose" messages, if verbosity config allows
    printIfVerbosityAllows(f"VERBOSE: {string}", Verbosity.VERBOSE)
def printD(string: str): # print "debug" messages, if verbosity config allows
    printIfVerbosityAllows(f"DEBUG: {string}", Verbosity.DEBUG)


def getScriptDir() -> str:

    """
    Returns absolute path to the directory this script is running in

    :return: Absolute dirctory
    """

    return os.path.dirname(os.path.realpath(__file__))


def openFileInOS(filename: str) -> bool:

    """
    Opens a file in the OS's default viewer/editor/handler for file

    :param filename: Filename to open
    :return: False if successful, TRUE if error
    """
    printV(f"Opening \"{os.path.realpath(filename)}\" in default system image viewer")
    try:
        if platform.system() == "Windows":
            os.startfile(filename)
        else: # both Linux and Darwin (aka Mac) use "open"
            subprocess.call(['open', filename])
    except Exception as e:
        printW(f"Unable to open file \"{filename}\" in your OS's file viewer, error: {e}")
        return True
    return False


def processCmdLine() -> argparse.Namespace:

    """
    Processes the command line

    :return: False if successful, True if error
    """

    # custom ArgumentParser that throws exception on parsing error
    class ArgumentParserError(Exception): pass # from http://stackoverflow.com/questions/14728376/i-want-python-argparse-to-throw-an-exception-rather-than-usage
    class ArgumentParserWithException(argparse.ArgumentParser):
        def error(self, message):
            raise ArgumentParserError(message)

    # converts string value like "True", "T", "No", etc... to boolean
    def strValueToBool(string: str) -> bool:
        if string is None:
            return True
        if string.upper() in ['1', 'TRUE', 'T', 'YES', 'Y']:
            return True
        if string.upper() in ['0', 'FALSE', 'F', 'NO', 'N']:
            return False
        raise argparse.ArgumentTypeError(f"Boolean value expected but '{string}' was specified")

    # converts comma-separated string to a list of floats
    def commaSeparatedFloatListForArg(string: str) -> List[float]:
        return [float(item.strip()) for item in string.split(',')]

    # converts comma-separated string to a list of ints
    def commaSeparatedIntListForArg(string: str) -> List[int]:
        return [int(item.strip()) for item in string.split(',')]

    # converts string to hex value
    def strToHex(string: str) -> int:
        string = string.lstrip("#")
        return int(string, 16)

    # removes one nesting of list. Ex: [[1.0, 0.5, 1.0]] -> [1.0, 0.5, 1.0]
    def flattenList(listToFlatten: List) -> List:
        flattenedList = list()
        for item in listToFlatten:
            flattenedList.extend(item)
        return flattenedList

    # arg parser that throws exceptions on errors
    parser = ArgumentParserWithException(fromfile_prefix_chars='!',\
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description='Converts an image into a Nikon Raw NEF (written by Horshack)',\
        epilog="Options can also be specified from a file. Use !<filename>. Each word in the file must be on its own line.\n\nYou "\
            "can abbreviate any argument name provided you use enough characters to uniquely distinguish it from other argument names.\n")

    parser.add_argument('templatenef', metavar="<Camera Model> or <Template NEF filename>", help="""Required: Camera model name, or filename of an existing Nikon NEF lossless compressed raw file to use as the template. If a camera model
        is specified then the NEF file located at ./templatenef/<camera model>.NEF will be used. Template NEFs are used by this app to form the skeleton of the new NEF generated - we read the template NEF into memory and overwrite the raw data
        inside it with the raw data generated from your source image, storing the result as a new NEF, leaving the skeleton NEF untouched. Template NEFs for most Nikon Z models are included with this app. If your camera model
        isn't included then you'll need to provide a template NEF. See the readme at the GitHub page for best practices on creating template NEFs.""")
    parser.add_argument('inputfilename', metavar="<image filename>", help="Required: Input file, typically an image (ex: TIF, JPG, PNG) but Numpy (.npy) files of certain shapes are also supported.")
    parser.add_argument('outputfilename', nargs="?", metavar="<output filename>", help="Optional - If not specified, name will be automatically generated using the the method defined by --outputfilenamemethod.")
    parser.add_argument('--embeddedimg', metavar="<image filename>", type=str, help="Use a different image for the embedded jpgs. Default is to use the image data from <inputfilename>, ie same image that's used to generated the raw data.", required=False)
    parser.add_argument('--openinviewer', type=strValueToBool, nargs='?', default=False, const=True, metavar="yes/no", help="Open generated NEF in default image editor after creating. Default is %(default)s.")
    parser.add_argument('--outputdir', type=str, metavar="<path>", help="Directory to store image/file(s) to.  Default is current directory. If path contains any spaces enclose it in double quotes. Example: --outputdir \"c:\\My Documents\"", default=None, required=False)
    parser.add_argument('--outputfilenamemethod', type=str.upper, choices=OutputFilenameMethodStrs, default='TEMPLATENEF_AND_INPUTFILE', required=False, help="""Method used to automatically generate output filename when not explicitly specified.
        Default is \"%(default)s\", which means the template NEF + input filenames will be concatenated together to form the output filename, with the result stored in the input filename's directory (unless --outputdir is specified).""")
    parser.add_argument('--ifexists', type=str.upper, choices=IfFileExistsStrs, default='ADDSUFFIX', required=False, help="""Action to take if the output file already exists. Default is \"%(default)s\", which means a suffix is
        added to the output filename to create a unique filename.""")

    sourceImgOptions = parser.add_argument_group("Source Image Processing", "These options control how the source image is processed into bayered raw data. They are not supported for Numpy (.npy) sources.")
    sourceImgOptions.add_argument('--src.hsl', dest="src_hsl", type=commaSeparatedFloatListForArg, nargs=1, default=[[1.0, 0.5, 1.0]], metavar="H,S,L - each value between 0.0 and 1.0", help="Hue, Saturation, and Lightness adjustment on source image. Ex: --src.hsl=1.0,0.5,1.0. Default is %(default)s.", required=False)
    sourceImgOptions.add_argument('--src.srgbtolinear', dest="src_srgbtolinear", type=strValueToBool, nargs='?', default=True, const=True, metavar="yes/no", help="Assume source is sRGB and convert to linear. Default is %(default)s.")
    sourceImgOptions.add_argument('--src.wbmultipliers', dest="src_wbmultipliers", type=commaSeparatedFloatListForArg, nargs=1, required=False, metavar="RedValue, BlueValue - each value is float/decimal", help="Override white balance red/blue multipliers in template NEF.")
    sourceImgOptions.add_argument('--src.grayscale', dest="src_grayscale", type=strValueToBool, nargs='?', default=False, const=True, metavar="yes/no", help="Convert source image to grayscale. Default is %(default)s.")

    resizeOptions = parser.add_argument_group('Resize Options', "These options control how the source image is resized to fit the raw image dimensions.")
    resizeOptions.add_argument('--re.geometry', dest='re_geometry', type=str.upper, choices=ResizeGeomStrs, default="FULL", required=False, help="""Resizing: Geometry to use. \"FULL\" means source image is
        first resized so both axis reach the raw output dimensions, which means one axis will likely be oversized and need to be cropped back down for most aspect ratios. For example, a 1000x1000 1:1 source image for a 6000x4000 3:2 raw
        will be resized to 6000x6000, then cropped to 6000x4000 to meet the raw's 3:2 aspect ratio. \"MINIMUM\" means source image is resized only to its nearest axis (in size) to meet a raw axis, with the other raw output axis potentially padded with a border.
        For example, a 1000x1000 1:1 source image for a 6000x4000 3:2 raw will be resized to 4000x4000 (raw's \"row\" axis is closest in size to source image), with 1000 pixels of border on both horizontal sides of the raw image to fill
        out the raw's 6000 horizontal pixels. Default is %(default)s.""")
    resizeOptions.add_argument('--re.maintainaspectratio', dest='re_maintainaspectratio', type=strValueToBool, nargs='?', default=True, const=True, metavar="yes/no", help="""Resizing: Maintain aspect ratio of source. When false,
        the --re.geometry value isn't applicable since the aspect ratio constraints it addresses don't exist when the source image aspect ratio doesn't need to be maintained. For example, a 1000x1000 1:1 source image can be resized
        directly to a 6000x4000 3:2 raw output without needing to oversize it to 6000x6000 first. Default is %(default)s.""")
    resizeOptions.add_argument('--re.horzalign', dest='re_horzalign', type=str.upper, choices=AlignmentStrs, default="CENTER", required=False, help="""Resizing: Horizontal alignment of source image position or crop. For example, if
        resizing is disabled via --re.geometry=NONE and source image is 2000x2000, a 6000x4000 raw will have 1500 padding pixels on both horizontal sides, with source image centered in frame. Default is %(default)s.""")
    resizeOptions.add_argument('--re.vertalign', dest='re_vertalign', type=str.upper, choices=AlignmentStrs, default="CENTER", required=False, help="Resizing: Vertical alignment of source image position or crop. Default is %(default)s.")
    resizeOptions.add_argument('--re.resizealgo', dest='re_algorithm', type=str.upper, choices=ResizeAlgoNames, default='LANCZOS4', required=False, help="Resizing: Algorithm to use to resize source pixels. Default is %(default)s.")
    resizeOptions.add_argument('--re.borderfillcolor', dest='re_borderfillcolor', type=strToHex, default='#000000', required=False, metavar="#RRGGBB (hex)", help="Resizing: Border color when source image doesn't fill out raw frame for resize parameters used.  Default is %(default)s.")

    troubleshootingOptions = parser.add_argument_group("Troubleshooting Options", "These options help in troubleshooting issues")
    troubleshootingOptions.add_argument('--showperfstats', metavar="yes/no", type=strValueToBool, nargs='?', default=False, const=True, help="Show performance statistics. Implicitly enabled when --verbosity is >= VERBOSE")
    troubleshootingOptions.add_argument('--verbosity', type=str.upper, choices=VerbosityStrs, default="INFO", required=False, help="Verbosity of output during execution. Default is %(default)s.")

    if len(sys.argv) == 1:
        # print help if no parameters passed
        parser.print_help()
        return None

	#
	# if there is a default arguments file present, add it to the argument list so that parse_args() will process it
	#
    defaultOptionsFilename = os.path.join(getScriptDir(), f".{AppName}-defaultoptions")
    if os.path.isfile(defaultOptionsFilename):
        sys.argv.insert(1, "!" + defaultOptionsFilename) # insert as first arg (past script name), so that the options in the file can still be overriden by user-entered cmd line options

    # perform the argparse
    try:
        args = parser.parse_args()
    except ArgumentParserError as e:
        print("Command line error: " + str(e))
        return None

    # do post-processing/conversion of args
    args.outputfilenamemethod = OutputFilenameMethod[args.outputfilenamemethod] # convert from str to enumerated value
    args.re_geometry = ResizeGeom[args.re_geometry]   # convert from str to enumerated value
    args.re_horzalign = Alignment[args.re_horzalign]  # convert from str to enumerated value
    args.re_vertalign = Alignment[args.re_vertalign]  # convert from str to enumerated value
    args.ifexists = IfFileExists[args.ifexists]       # convert from str to enumerated value
    args.verbosity = Verbosity[args.verbosity]        # convert from str to enumerated value

    # flatten lists created by argparse. ex: args.src_hsl=[[1.0, 0.5, 1.0]] -> [1.0, 0.5, 1.0]
    if args.src_hsl:
        args.src_hsl = flattenList(args.src_hsl)

    if args.src_wbmultipliers:                          # convert from list to WhiteBalanceMultipliers
        args.src_wbmultipliers = WhiteBalanceMultipliers(red=args.src_wbmultipliers[0][0], blue=args.src_wbmultipliers[0][1])

    args.re_algorithm = getattr(cv2, "INTER_" + args.re_algorithm) # convert algorithm as string into enumerated cv2 value

    return args


def calcSrcGeomAdjustments(srcDimensions: Dimensions, tgtDimensions: Dimensions, resizeGeom: ResizeGeom, fMaintainAspectRatio: bool, horzAlignment: Alignment, vertAlignment: Alignment) -> SrcGeomAdjustments:

    """
    Calculates the geometry adjustments (resize, crop, positioning) required to get a source image into
    the raw image's size, based on a specified set of configurable parameters

    :param srcDimensions: Source image dimensions
    :param tgtDimensions: Target image dimensions (ie, the raw dimensions)
    :param resizeGeom: Resize geometry to use
    :param fMaintainAspectRatio: Whether or not aspect ratio of source image should be maintained
    :param horzAlignment: Horizontal alignment
    :param vertAlignment: Vertical alignment
    :return: SrcGeomAdjustments, which specifies the adjustments that need to be made on the source image
    """

    def calcAxisCrop(srcAmount: int, tgtAmount: int, alignment: Alignment):
        if srcAmount <= tgtAmount:
            # not larger on column axis, no cropping on this axis is necessary
            start = 0; end = srcAmount
        else:
            amountToCrop = srcAmount - tgtAmount
            match alignment:
                case Alignment.LEFT | Alignment.TOP:
                    start = 0
                    end = tgtAmount
                case Alignment.CENTER:
                    start = int(round(amountToCrop / 2))
                    end = int(round(srcAmount - (amountToCrop / 2) - (amountToCrop % 2))) # % 2 to handle odd crop amounts
                case Alignment.RIGHT | Alignment.BOTTOM:
                    start = amountToCrop
                    end = tgtAmount
                case _:
                    assert False, f"Uknown {alignment=}"
        return (start, end)

    def calcAxisPos(srcAmount: int, tgtAmount: int, alignment: Alignment):
        if srcAmount >= tgtAmount:
            # src is equal or larger than target, position at 0 in target
            pos = 0
        else:
            amountShort = tgtAmount - srcAmount
            match alignment:
                case Alignment.LEFT | Alignment.TOP:
                    pos = 0
                case Alignment.CENTER:
                    pos = int((tgtAmount/2) - (srcAmount/2))
                case Alignment.RIGHT | Alignment.BOTTOM:
                    pos = tgtAmount-srcAmount
                case _:
                    assert False, f"Uknown {alignment=}"
        return pos


    if srcDimensions == tgtDimensions:
        # already at target dimensions, nothing to do
        return None

    #
    # calculate resize enlargement
    #
    if (srcDimensions.columns >= tgtDimensions.columns) and (srcDimensions.rows >= tgtDimensions.rows):
        # src is equal/larger vs tgt on both axis - no enlargement necessary (although a crop may be necessary)
        resizeDimensions = None
    else:
        # src is smaller vs tgt on at least one axis
        if resizeGeom == ResizeGeom.MINIMUM:
            if not fMaintainAspectRatio:
                # we already know just one axis needs enlargment, so enlarge that size and use original src side for other axis
                if srcDimensions.columns < tgtDimensions.columns:
                    # src columns needs to be enlarged, leve src rows the same
                    resizeDimensions = Dimensions(columns=tgtDimensions.columns, rows=srcDimensions.rows)
                else:
                    # src rows needs to be enlarged, leve src columns the same
                    resizeDimensions = Dimensions(columns=srcDimensions.columns, rows=tgtDimensions.rows)
            else:
                # need to maintain aspect ratio. determine which axis to enlarge
                columnMultiplier = tgtDimensions.columns / srcDimensions.columns
                rowMultiplier = tgtDimensions.rows / srcDimensions.rows
                if columnMultiplier < rowMultiplier:
                    # long edge is column side, so enlarge columns to tgt dimensions and rows to whatever size the aspect ratio allows
                    resizeDimensions = Dimensions(columns=tgtDimensions.columns, rows=int(round(srcDimensions.rows * columnMultiplier)))
                else:
                    # long edge is row side, so enlarge rows to tgt dimensions and cols to whatever size the aspect ratio allows
                    resizeDimensions = Dimensions(columns=int(round(srcDimensions.columns * rowMultiplier)), rows=tgtDimensions.rows)
        elif resizeGeom == ResizeGeom.FULL:
            if srcDimensions.columns < tgtDimensions.columns:
                columnMultiplier = tgtDimensions.columns / srcDimensions.columns
            else:
                columnMultiplier = 1
            if srcDimensions.rows*columnMultiplier < tgtDimensions.rows:
                rowMultiplier = tgtDimensions.rows / (srcDimensions.rows * columnMultiplier)
            else:
                rowMultiplier = 1
            totalMultiplier = columnMultiplier * rowMultiplier
            resizeDimensions = Dimensions(int(round(srcDimensions.columns * totalMultiplier)), int(round(srcDimensions.rows * totalMultiplier)))
        elif resizeGeom == ResizeGeom.NONE:
            # resizing not enabled - src will be smaller than tgt on one axis
            resizeDimensions = None
        else:
            assert False, f"Unknown {resizeGeom=}"

    newDimensions = resizeDimensions if resizeDimensions else srcDimensions

    #
    # calculate positioning (if an one or more axis is shorter than tgt)
    #
    pos = Coordinate(x=calcAxisPos(newDimensions.columns, tgtDimensions.columns, horzAlignment),
        y=calcAxisPos(newDimensions.rows, tgtDimensions.rows, vertAlignment))

    #
    # calcualte crop
    #
    if (newDimensions.columns <= tgtDimensions.columns) and (newDimensions.rows <= tgtDimensions.rows):
        # new dimenions aren't larger than tgt dimensions on any axis, no cropping necessary
        cropRect = None
    else:
        startx, endx = calcAxisCrop(newDimensions.columns, tgtDimensions.columns, horzAlignment)
        starty, endy = calcAxisCrop(newDimensions.rows, tgtDimensions.rows, vertAlignment)
        cropRect = Rect(startx=startx, endx=endx, starty=starty, endy=endy)

    srcGeomAdjustments = SrcGeomAdjustments(resizeDimensions=resizeDimensions, posInTgt=pos, cropRect=cropRect)
    return srcGeomAdjustments


def execExternalProgram(executableFileName: str, cmdLineArgsList: List[str]) -> subprocess.CompletedProcess:

    """
    Executes an external app, waits for completion

    :param executableFileName: Full path to executable
    :param cmdLineArgsList: List structure with command-line arguments
    :return: subprocess.run() return value, or None if error
    """

    fullCmdLine = [executableFileName] + cmdLineArgsList
    try:
        result = subprocess.run(fullCmdLine, check=False, capture_output=True, text=True)
        return result
    except FileNotFoundError as e:
        printE(f"execExternalProgram() failed, \"{executableFileName}\" not found")
        return None
    except Exception as e:
        printE(f"execExternalProgram(\"{executableFileName}\") failed: {e}")
        return None


def extractExifFromNEF(nefFilename: str) -> types.SimpleNamespace:

    """
     Extracts useful EXIF info we need from the template NEF

    :param nefFilename: Full path to NEF filename
    :return: Namespace with EXIF fields, or None if error
    """

    def reportExifFieldNotFound(fieldName: str) -> None:
        printE(f"EXIF: Could not find field '{fieldName}' in NEF EXIF for \"{nefFilename}\"")
        return None

    def extractEmbeddedJpgExifInfo(exifName: str, lenDescSuffix: str) -> EmbeddedJpgExifInfo:

        """
        Extracts EXIF info about the specified embedded jpg

        :param exifName: EXIF name of jpg, as named by exiftool
        :param lenDescSuffix: Suffix applied to exifName for length field
        :return: EmbeddedJpgExifInfo for embedded jpg, or None if the EXIF field doesn't exist
        or error extracting its info
        """

        jpgStartDescInExif  = f"{exifName}{lenDescSuffix}"    # ex: exifName="JpgFromRaw" -> "JpgFromRawStart"
        jpgLengthDescInExif = f"{exifName}Length"             # ex: exifName="JpgFromRaw" -> "JpgFromRawLength"

        # extract starting offset to jpg
        m = re.search(rf'{jpgStartDescInExif} = (\d+)', ifd0Str)
        if m is None: return None
        if exifName != "PreviewImage":
            jpgStart = int(m.group(1))
        else:
            # ignore -v3 value and use separate tag value (exiftool bug) for "PreviewImage"
            jpgStart = exif.PreviewImageStart

        '''
        Sample output that we're parsing to get the strip byte count and file offset to strip byte count
          | | 6)  JpgFromRawLength = 503293
          | |     - Tag 0x0202 (4 bytes, int32u[1]):
          | |        22d68: fd ad 07 00                                     [....]
        '''
        m = re.search(rf'{jpgLengthDescInExif} = (\d+).*\n.*Tag.*\n.*?([0-9a-f]+):', ifd0Str)
        if (m is None): return reportExifFieldNotFound(f"{jpgLengthDescInExif}")
        jpgLength = int(m.group(1))
        offsetToJpgLengthField = int(m.group(2), 16)
        return EmbeddedJpgExifInfo(exifName=exifName, start=jpgStart, length=jpgLength, offsetToLengthField=offsetToJpgLengthField)

    exif = types.SimpleNamespace()

    # run exiftool in verbose v3 mode
    # note we request the PreviewImageStart tag seperately because the value reported by -v3 isn't corect (https://exiftool.org/forum/index.php?topic=17665.0)
    cmdLineArgList = ['-v3', '-PreviewImageStart', nefFilename];
    result = execExternalProgram("exiftool", cmdLineArgList)

    if result is None:
        printE(f"Failed to execute exiftool on \"{nefFilename}\"")
        return None
    if result.stderr:
        printE(f"exiftool reported:\n{result.stderr}")
        return None

    fullExifStr = result.stdout

    # make sure the file specified is interprted as a valid NEF by exiftool (FileType = NEF)
    m = re.search(r'FileType = (.+)', fullExifStr)
    if (m.group(1) != "NEF"):
        printE(f"\"{nefFilename}\" is not a valid Nikon NEF file")
        return None

    #
    # parse the exiftool output to extract the fields we need
    #

    # extract byte order (ie, endian) of EXIF data
    m = re.search(r'ExifByteOrder = (.+)', fullExifStr)
    if m is None: return reportExifFieldNotFound("ExifByteOrder")
    match m.group(1):
        case "II": # "Intel"
            exif.endian = Endian.LITTLE
        case "MM": # "Motorola"
            exif.endian = Endian.BIG
        case _:
            printE(f"EXIF: Unkown byte order value of \"{m.group(1)}\" for \"{nefFilename}\"")
            return None

    '''
    Get to IFD0. Sample output that we're parsing:
      + [IFD0 directory with 22 entries]
    '''
    m = re.search(r'.*\+ \[IFD0 directory', fullExifStr)
    if m is None: return reportExifFieldNotFound("IFD0")
    ifd0Str = fullExifStr[m.start():]

    # extract model of camera
    m = re.search(r'Model = (.+)', ifd0Str)
    if m is None: return reportExifFieldNotFound("Model")
    exif.cameraModel = m.group(1)

    # obtain PreviewImageStart via the separate tag report because the value reported
    # by -v3 isn't corect (https://exiftool.org/forum/index.php?topic=17665.0)
    m = re.search(r'Preview Image Start\s+: (.+)', fullExifStr) # sample: "Preview Image Start             : 104744"
    if m is None: return reportExifFieldNotFound("PreviewImageStart")
    exif.PreviewImageStart = int(m.group(1))

    # embedded jpgs
    exif.embeddedJpgs = list()
    for embeddedJpgExifName in EmbeddedJpgExifNames:
        e = extractEmbeddedJpgExifInfo(embeddedJpgExifName, "Offset" if embeddedJpgExifName == "Thumbnail" else "Start")
        if e is not None:
            exif.embeddedJpgs.append(e)

    # find the SubIFD with a subfiletype of 0, which is the NEF raw area
    m = re.search(r'SubfileType = 0', ifd0Str)
    if m is None: return reportExifFieldNotFound("SubfileType of 0")
    subIFDStr = ifd0Str[m.start():]

    # extract ImageWidth and ImageHeight
    m1 = re.search(r'ImageWidth = (\d+)', subIFDStr)
    m2 = re.search(r'ImageHeight = (\d+)', subIFDStr)
    if (m1 is None) or (m2 is None): return reportExifFieldNotFound("ImageWidth/ImageHeight")
    exif.rawDimensions = Dimensions(columns=int(m1.group(1)), rows=int(m2.group(1)))

    # extract BitsPerSample
    m = re.search(r'BitsPerSample = (\d+)', subIFDStr)
    if m is None: return reportExifFieldNotFound("BitsPerSample")
    exif.bitsPerSample = int(m.group(1))
    if exif.bitsPerSample != 14:
        printE(f'Template NEF "{nefFilename}" is a {exif.bitsPerSample}-bit raw; only 14-bit raws are supported')
        return None


    # extract StripOffset
    m = re.search(r'StripOffsets = (\d+)', subIFDStr)
    if m is None: return reportExifFieldNotFound("StripOffsets")
    exif.stripOffset = int(m.group(1))

    '''
    Sample output that we're parsing to get the strip byte count and file offset to strip byte count
      | | 9)  StripByteCounts = 23706986
      | |     - Tag 0x0117 (4 bytes, int32u[1]):
      | |        22e02: 6a bd 69 01                                     [j.i.]
    '''
    m = re.search(r'StripByteCounts = (\d+).*\n.*Tag.*\n.*?([0-9a-f]+):', subIFDStr)
    if (m is None): return reportExifFieldNotFound("StripByteCounts")
    exif.stripByteCount = int(m.group(1))
    exif.fileOffsetToStripByteCount = int(m.group(2), 16)

    #
    # move on to Maker Notes
    #
    m = re.search(r'ExifIFD directory.*MakerNotes directory', ifd0Str, re.DOTALL)
    if (m is None): return reportExifFieldNotFound("MakerNotes")
    makerNotesStr = ifd0Str[m.start():]

    '''
    Sample output that we're parsing to get the Red and Black White Balance multipliers
      | | | 6)  WB_RBLevels = 1.916015625 1.2578125 1 1 (981/512 644/512 512/512 512/512)
    '''
    m = re.search(r'.*WB_RBLevels = ([\d\.]+) ([\d\.]+)', makerNotesStr)
    if (m is None): return reportExifFieldNotFound("WB_RBLevels")
    exif.wbMultipliers = WhiteBalanceMultipliers(float(m.group(1)), float(m.group(2)))

    m = re.search(r'.*NEFCompression = (\d+)', makerNotesStr)
    if (m is None): return reportExifFieldNotFound("NEFCompression")
    exif.nefCompressionType = int(m.group(1))
    if exif.nefCompressionType != 3:
        printE(f'Template NEF "{nefFilename}" is not using lossless compression')
        return None

    m = re.search(r'.*BlackLevel = (\d+)', makerNotesStr)
    if m:
        exif.blackLevel = int(m.group(1))
    else:
        # no blacklevel field. Assume it's an older model that subtracted blacks in-camera
        printV("EXIF: No BlackLevel field found; assuming a black level of zero")
        exif.blackLevel = 0

    '''
    Sample output for extracting the initial "pred" value for NEF lossless compression.
    We want the little-endian 16-bit value starting at offset 2 into the NEFLinearizationTable (usually 0x800)
      | | | 64) NEFLinearizationTable = F0....".*...r^.....e.... ../......Z!X...6
      | | |     - Tag 0x0096 (46 bytes, undef[46]):
      | | |        19584: 46 30 00 08 00 08 00 08 00 08 22 00 b7 2a aa 9d [F0........"..*..]
      | | |        19594: e0 72 5e 91 18 f5 1c 99 65 82 f0 af bf 20 d2 d2 [.r^.....e.... ..]
      | | |        195a4: 2f c6 c1 02 a7 86 c5 5a 21 58 d8 a6 ca 36       [/......Z!X...6]
    '''
    m = re.search(r'.*NEFLinearizationTable .*\n.*Tag.*\n.*?[0-9a-f]+: [0-9a-f][0-9a-f] [0-9a-f][0-9a-f] ([0-9a-f][0-9a-f]) ([0-9a-f][0-9a-f])', makerNotesStr)
    if (m is None): return reportExifFieldNotFound("NEFLinearizationTable")
    if exif.endian == Endian.LITTLE:
        predValueStr = m.group(2)+m.group(1)
    else:
        predValueStr = m.group(1)+m.group(2)
    exif.predValueNefCompression = int(predValueStr, 16)

    '''
     Sample output for extracting the initial "CropArea" values
       | | | 35) CropArea = 8 4 6048 4032
    '''
    m = re.search(r'.*CropArea = (\d+) (\d+) (\d+) (\d+)', makerNotesStr)
    if m:
        exif.cropAreaDimensions = NikonCropArea(left=int(m.group(1)), top=int(m.group(2)), columns=int(m.group(3)), rows=int(m.group(4)))
    else:
        # older models don't have a CropArea tag
        exif.cropAreaDimensions = None

    return exif


def src_EncodeToNikonLossless(bayerImage: np.ndarray[tuple[int, int], np.dtype[np.uint16]]) -> bytearray:

    """
    Encodes a bayered RGGB image using Nikon's lossless NEF compression, using my optimized 'C' logic

    :param bayerImage: Bayered image to encode
    :return: Encoded data (bytearray)
    """

    #
    # load the compiled 'C' shared library. first we check the base directory of our script,
    # in case the user compiled a version for a non-standard platform. if that doesn't exist
    # then we'll load the pre-compiled version based on the standard platform we're running under
    #
    def loadSharedLibrary(path: str):
        try:
            lib = ctypes.CDLL(path)
            return (lib, None)
        except Exception as e:
            return (None, f"Unable to open/read shared library {path}, error: {e}")

    libNefencode, errorMsg = loadSharedLibrary('./nefencode2.so')
    if libNefencode is None:
        libDir = platform.system()
        if libDir == "Darwin":
            libDir = "Mac"
        scriptDir = getScriptDir()
        libNefencode, errorMsg = loadSharedLibrary(f"{scriptDir}/{libDir}/nefencode.so")
        if libNefencode is None:
            printE(errorMsg)
            return None

    # define python version of the NEF_ENCODE_PARAMS structure in nefencode.c
    class NefEncodeParams(ctypes.Structure):
        _fields_ = [
            ("countColumns", ctypes.c_int),
            ("countRows", ctypes.c_int),
            ("sourceBufferSizeBytes", ctypes.c_int),
            ("outputBufferSizeBytes", ctypes.c_int),
            ("startingPredictiveValue", ctypes.c_uint16),
            ("pad1", ctypes.c_uint16),
            ("sourceData", ctypes.POINTER(ctypes.c_uint16)),
            ("outputBuffer", ctypes.POINTER(ctypes.c_uint8)),
        ]

    nefEncodeParams = NefEncodeParams()

    # configure paramters and return value to "t_NefEncodeError NefEncode(NEF_ENCODE_PARAMS *params)"
    libNefencode.NefEncode.argtypes = [ ctypes.POINTER(NefEncodeParams) ]
    libNefencode.NefEncode.restype = ctypes.c_int32

    # build NefEncodeParams

    sourceImageSizeBytes = bayerImage.nbytes
    outputBufferSizeBytes = sourceImageSizeBytes + 1048576 # +1MB is somewhat arbitrary
    outputBuffer = bytearray(outputBufferSizeBytes)
    outputBufferCtypeArray = (ctypes.c_uint8 * outputBufferSizeBytes)

    nefEncodeParams.countColumns = Config.exif.rawDimensions.columns
    nefEncodeParams.countRows = Config.exif.rawDimensions.rows
    nefEncodeParams.sourceBufferSizeBytes = sourceImageSizeBytes
    nefEncodeParams.outputBufferSizeBytes = outputBufferSizeBytes
    nefEncodeParams.startingPredictiveValue = Config.exif.predValueNefCompression
    nefEncodeParams.pad1 = 0
    nefEncodeParams.sourceData = bayerImage.ctypes.data_as(ctypes.POINTER(ctypes.c_uint16))
    nefEncodeParams.outputBuffer = outputBufferCtypeArray.from_buffer(outputBuffer)

    assert bayerImage.flags['C_CONTIGUOUS'] == True, "Image numpy array isn't contiguous!"

    # call nefencode.c::NefEncode() in shared library to encode the data
    result = libNefencode.NefEncode(ctypes.byref(nefEncodeParams))

    if result < 0:
        printE(f"Compressing image data into Nikon lossless failed - error={result}")
        return None

    return outputBuffer[:result]


def splitPathIntoParts(fullPath: str) -> tuple[str, str, str]:

    """
    Splits path into parts (directory, root filename, and extension)

    :param fullPath: Full path to split
    :return: Tuple containing (directory, root filename, extension)
    """

    dir, filename = os.path.split(fullPath)
    root, ext = os.path.splitext(filename)
    return (dir, root, ext)


def generateFilenameWithDifferentExtensionAndDir(fullPath: str, newDir: str, newExt: str) -> str:

    """
    Generates filename based on existing filename but with different extension

    :param fullPath: Full path to filename
    :param newDir: New directory, or None to use existing directory of fullPath
    :param newExt: New extension (with the leading period), or None to use existing extension
    :return: Generated full path to filename with changed extension
    """

    dir, root, ext = splitPathIntoParts(fullPath)
    if newDir is not None:
        dir = newDir
    if newExt is not None:
        if newExt[0] != '.': newExt = '.' + newExt
        ext = newExt
    return os.path.join(dir, root + ext)


def generateUniqueFilenameFromExistingIfNecessary(fullPath: str) -> str:

    """
    If a file with the specified name exists, adds a numerical suffix to the filename
    to make it a unique filename for the path the file is in

    :param fullPath: Full path to original filename
    :return: fullPath if a file with that name doesn't already exist, or a
    fullPath with a unique suffix
    """

    dir, root, ext = splitPathIntoParts(fullPath)

    seqNum = 0; seqNumStr = "" # first candidate is without a suffix
    while True:
        filenameCandidate = os.path.join(dir, root + seqNumStr + ext)
        if not os.path.exists(filenameCandidate):
            return filenameCandidate
        seqNum += 1
        seqNumStr = f"-{seqNum}"


def generateOutputFilename() -> str:

    """
    Generates the filename to hold encoded output, based on user settings

    :return: Output filename, or None if output filename couldn't be determined.
    """

    outputFilename = Config.args.outputfilename
    if outputFilename is None:

        # user didn't specify an output filename. generate one based on the template NEF and input filenames

        templateNefDir, templateNefRootName, _ = splitPathIntoParts(Config.args.templatenef)
        inputDir, inputRootName, _ = splitPathIntoParts(Config.args.inputfilename)

        match Config.args.outputfilenamemethod:
            case OutputFilenameMethod.NONE:
                printE(f"No output filename specified and --outputfilenamemethod is NONE. Either specify an output filename or a different --outputfilenamemethod")
                return None
            case OutputFilenameMethod.TEMPLATENEF_AND_INPUTFILE:
                outputFilename = f"{os.path.join(inputDir, templateNefRootName)}_{inputRootName}"
            case OutputFilenameMethod.TEMPLATENEF:
                outputFilename = f"{os.path.join(inputDir, templateNefRootName)}"
            case OutputFilenameMethod.INPUTFILE:
                outputFilename = f"{os.path.join(inputDir, inputRootName)}"

        outputFilename = generateFilenameWithDifferentExtensionAndDir(outputFilename, Config.args.outputdir, "NEF")
    else:
        outputFilename = generateFilenameWithDifferentExtensionAndDir(outputFilename, Config.args.outputdir, None)

    match Config.args.ifexists:
        case IfFileExists.ADDSUFFIX:
            outputFilename = generateUniqueFilenameFromExistingIfNecessary(outputFilename)
        case IfFileExists.OVERWRITE:
             pass
        case IfFileExists.EXIT:
            if os.path.exists(outputFilename):
                printE(f"Output file \"{outputFilename}\" already exists. Exiting per --ifexists setting")
                return None

    return outputFilename


def generateEmbeddedJpg(image: np.ndarray, embeddedJpgDimensions: Dimensions, maxSizeBytes: int, embeddedJpgExifName: str) -> np.ndarray:

    """
    Generates an in-memory jpg suitable for embedding into the output raw

    :param image: Processed source image to generate the embedded jpg from
    :param embeddedJpgDimensions: Dimensions of this embedded jpg
    :param maxSizeBytes: Maximum size of embedded jpg that will fit within the EXIF of the template NEF
    :param embeddedJpgExifName: Name of this embedded JPG in EXIF (used for debug prints only)
    :return: Generated in-memory JPG image or None if unable to generate within the specified size constraint
    """

    # resize image to match embedded jpg dimensions, if necessary
    imageDimensions = Dimensions(rows=image.shape[0], columns=image.shape[1])
    if imageDimensions != embeddedJpgDimensions:
        printV(f"Resizing image from {imageDimensions.columns}x{imageDimensions.rows} to {embeddedJpgDimensions.columns}x{embeddedJpgDimensions.rows} for \"{embeddedJpgExifName}\" embedded jpg")
        image = cv2.resize(image, (embeddedJpgDimensions.columns, embeddedJpgDimensions.rows), interpolation=Config.args.re_algorithm)

    #
    # use PIL to generate the embedded jpg from he source data. We use PIL instead of cv2
    # because cv2 doesn't support 4:2:2 encoding and Nikon cameras require 4:2:2 for their
    # in-camera playback functionality
    #
    pilImage = Image.fromarray(image)
    quality = 100
    while True:
        memoryFile = BytesIO()
        pilImage.save(memoryFile, format='JPEG', subsampling='4:2:2', quality=quality)
        jpg = memoryFile.getvalue()
        jpgSizeBytes = len(jpg)
        printD(f"Generated embedded jpg \"{embeddedJpgExifName}\" (qual={quality}): {jpgSizeBytes:,} bytes vs max fit {maxSizeBytes:,} bytes")
        if jpgSizeBytes <= maxSizeBytes:
            return jpg
        if quality <= 20: # minimum quality we attempt is 20 (arbitrary)
            break;
        quality -= 10
    printW(f"Unable to generate embedded jpg \"{embeddedJpgExifName}\" that fits within {maxSizeBytes:,} bytes - last attempt produced {jpgSizeBytes:,} bytes at a quality level of {quality}")
    return None


def generatePlaceholderEmbeddedJpg(embeddedJpgDimensions: Dimensions, maxSizeBytes: int, embeddedJpgExifName: str) -> np.ndarray:

    """
    Generates an placeholder in-memory jpg suitable for embedding into the output raw. The placeholder
    is a simple all-black image with a single line of text

    :param embeddedJpgDimensions: Dimensions of this embedded jpg
    :param maxSizeBytes: Maximum size of embedded jpg that will fit within the EXIF of the template NEF
    :param embeddedJpgExifName: Name of this embedded JPG in EXIF (used for debug prints only)
    :return: Generated in-memory JPG image or None if unable to generate within the specified size constraint
    """

    #
    # use PIL to generate an in-memory image of the specified dimensions. The image is all black except
    # for a single line of text
    #
    pilImage = Image.new('RGB', (embeddedJpgDimensions.columns, embeddedJpgDimensions.rows), color = 'black')
    draw = ImageDraw.Draw(pilImage)

    text = f"{embeddedJpgExifName}, {embeddedJpgDimensions.columns} x {embeddedJpgDimensions.rows}"

    #
    # iterate through font sizes until we find one that allows our single line of text
    # to fill out the horizontal axis entirely
    #
    centerX = embeddedJpgDimensions.columns/2
    centerY = embeddedJpgDimensions.rows/2
    fontSize = 512
    while fontSize >= 8:
        defaultFont = ImageFont.load_default(size=fontSize)
        left, top, right, bottom = draw.textbbox((centerX, centerY), text, font=defaultFont, anchor="mm")
        textWidthPixels = int(right-left)
        if textWidthPixels < embeddedJpgDimensions.columns:
            # found a good font size
            break
        multiple  = textWidthPixels // embeddedJpgDimensions.columns
        if multiple >= 2:
            fontSize //= multiple
        else:
            fontSize = int(math.floor(fontSize * .95))
    draw.text((centerX,centerY), text, color="white", font=defaultFont, anchor="mm")

    #
    # save our drawing canvas to an in-memory jpg. unlike the normal embedded jpg case,
    # it doesn't make sense to iterate different quality levels to meet the size constraint
    # because the difference in sizes for such a simple image are negligible
    #
    memoryFile = BytesIO()
    pilImage.save(memoryFile, format='JPEG', subsampling='4:2:2', quality=50)
    jpg = memoryFile.getvalue()
    jpgSizeBytes = len(jpg)
    if jpgSizeBytes > maxSizeBytes:
        printW(f"Unable to generate placeholder embedded jpg \"{embeddedJpgExifName}\" that fits within {maxSizeBytes:,} bytes - last attempt produced {jpgSizeBytes:,} bytes")
        return None
    printD(f"Generated placeholder embedded jpg \"{embeddedJpgExifName}\", {fontSize=}, {jpgSizeBytes:,} bytes")
    return jpg


def generateAndInsertEmbeddedJpgs(image: np.ndarray, newNefData: bytearray) -> bool:

    """
    Geneates and inserts (overwrites) embedded JPGs into NEF data in memory

    :param image: Fully-processed source image to use as embedded jpg, or None if not available
    :param newNefData: Bytearray containing entire template NEF, minus the raw data
    :return: False if successful, True if error
    """

    def loadImageToUseAsEmbeddedJpg(filename: str) -> np.ndarray:

        """
        Loads a separate image file to use as the embedded jpg

        :param filename: Filename of image
        :return: Image, resized to the raw dimensions, with no specific dtype, or None if unable to load image
        """

        image = loadImage(filename)
        if image is None:
            return None
        fImageResized, image = resizeImgToRawDimensions(image, f'"{filename}"')
        return image


    def getEmbeddedJpgDimensions(exifFieldName: str, origJpgStart: int, origJpgSize: int):

        """
        Determines dimensions of existing embedded JPG by telling CV2 to decode our in-memory copy of the
        jpg. We have to do this because Nikon doesn't provide the dimensions of the embedded jpgs in a
        separate EXIF field.

        :param exifFieldName: EXIF field name for embedded jpg
        :param origJpgStart: Offset to embedded jpg in template NEF
        :param origJpgSize: Size embedded jpg in template NEF
        :return: Dimensions of embedded jpg
        """

        jpgData = np.frombuffer(newNefData[origJpgStart : origJpgStart + origJpgSize], dtype=np.uint8)
        jpgFromData = cv2.imdecode(jpgData, cv2.IMREAD_UNCHANGED)
        if jpgFromData is None:
            printE(f"Unable to decode embedded jpg \"{exifFieldName}\"")
            return None
        return Dimensions(rows=jpgFromData.shape[0], columns=jpgFromData.shape[1])


    #
    # if user specified their own image to use as the embedded image then load
    # it now, otherwise use the image generated from the input source image (if it's available)
    #
    if Config.args.embeddedimg:
        image = loadImageToUseAsEmbeddedJpg(Config.args.embeddedimg)
    if image is not None:
        #
        # convert the image to 8-bit RGB, then crop using Nikon's crop field in EXIF. This
        # image will serve as the source for all the embedded JPGs.
        #
        _, image8 = convertImageNumpyTypeIfNecessary(image, "uint8")
        image8 = cv2.cvtColor(image8, cv2.COLOR_BGR2RGB)
        if Config.exif.cropAreaDimensions:
            cropRect = Rect(startx = Config.exif.cropAreaDimensions.left,
                endx = Config.exif.cropAreaDimensions.left + Config.exif.cropAreaDimensions.columns,
                starty = Config.exif.cropAreaDimensions.top,
                endy = Config.exif.cropAreaDimensions.top +  Config.exif.cropAreaDimensions.rows)
            image8 = image8[cropRect.starty : cropRect.endy, cropRect.startx : cropRect.endx]
    else:
        # no image available, either from the input source imnage or a separate image file specified
        printW("No image available for embedded jpgs - will generate a placeholder image")
        image8 = None

    #
    # generate and insert each of the embedded JPGs
    #
    for embeddedJpgExif in Config.exif.embeddedJpgs:

        # get parameters of the embedded jpg
        jpgExifName = embeddedJpgExif.exifName
        origJpgStart = embeddedJpgExif.start
        origJpgSize = embeddedJpgExif.length
        offsetToOrigJpgSizeInTemplateNef = embeddedJpgExif.offsetToLengthField

        dimensions = getEmbeddedJpgDimensions(jpgExifName, origJpgStart, origJpgSize)
        if dimensions is None:
            return True

        #
        # generate a new embedded jpg of the same dimensions, restricting its size to the
        # existing embedded jpg since we're overwriting it memory and don't support rearranging
        # exif fields to make room for larger jpgs
        #
        if image8 is not None:
            embeddedJpg = generateEmbeddedJpg(image8, dimensions, origJpgSize, jpgExifName)
        else:
            embeddedJpg = None
        if embeddedJpg is None:
            # failed to fit an embedded image or none was available - try a placeholder image
            embeddedJpg = generatePlaceholderEmbeddedJpg(dimensions, origJpgSize, jpgExifName)

        #
        # insert (overwrite) new jpg in memory. if we couldn't generate the jpg due to size
        # constraint then skip this embedded jpg while still allowing the new NEF to be generated
        #
        if embeddedJpg is not None:
            # overwrite original embedded jpg with the one we generated
            newJpgSizeBytes = len(embeddedJpg)
            printV(f"Overwriting \"{jpgExifName}\" at offset 0x{origJpgStart:x}, len={newJpgSizeBytes:,} [old size = {origJpgSize:,}]")
            newNefData[origJpgStart : origJpgStart + newJpgSizeBytes] = embeddedJpg
            # if new jpg is smaller than existing, fill unused portion with zeros (not necessary but for debug clarity)
            if (countUnusedBytes := origJpgSize-newJpgSizeBytes) > 0:
                newNefData[origJpgStart+newJpgSizeBytes : origJpgStart+origJpgSize] = bytes([0x0] * countUnusedBytes)
            # update EXIF size field
            newNefData[offsetToOrigJpgSizeInTemplateNef : offsetToOrigJpgSizeInTemplateNef+4] = struct.pack('<I', newJpgSizeBytes)

    return False


def writeOutputNEF(image: np.ndarray, encodedImageData: bytearray) -> bool:

    """
    Writes losslessly-encoded image data into a Nikon NEF raw file

    :param image: Fully-processed source image (or None if not available)
    :param encodedImageData: Encoded image data (bytearray)
    :return: False if successful, TRUE if error
    """

    #
    # read entire template NEF up to where the raw data starts but not the raw data itself,
    # since we'l be replacing that with the new raw data we've generated
    #
    encodedImageDataSize = len(encodedImageData)
    templateNefSizeExcludingRawData = Config.exif.stripOffset
    try:
        with open(Config.args.templatenef, 'rb') as f:
            templateNefData = f.read(templateNefSizeExcludingRawData)
    except Exception as e:
        printE(f"Unable to open/read template NEF \"{Config.args.templatenef}\", error: {e}")
        return True

    # create mutable buffer we'll use to hold template NEF data and the data we're merging into it
    newNefData = bytearray(templateNefSizeExcludingRawData + encodedImageDataSize)

    # copy data from template NEF up to where the raw data starts
    newNefData[0:templateNefSizeExcludingRawData] = templateNefData

    #
    # copy the raw data we encoded (compressed), which inludates updating the 32-bit strip count
    # field that reflects the size of our encoded data
    #
    newNefData[templateNefSizeExcludingRawData:] = encodedImageData
    newNefData[Config.exif.fileOffsetToStripByteCount:Config.exif.fileOffsetToStripByteCount+4] = struct.pack('<I', encodedImageDataSize)

    #
    # generate+insert embedded JPGs. We ignore errors for this because the embedded jpgs aren't essential
    #
    generateAndInsertEmbeddedJpgs(image, newNefData)

    #
    # determine the output filename
    #
    outputFilename = generateOutputFilename()
    if not outputFilename:
        return True

    #
    # write out the NEF
    #
    try:
        with open(outputFilename, 'wb') as f:
            f.write(newNefData)
    except Exception as e:
        printE(f"Unable to create/write output NEF \"{outputFilename}\", error: {e}")
        return True

    printI(f"Successfully generated \"{os.path.realpath(outputFilename)}\"")
    if Config.args.openinviewer:
        openFileInOS(outputFilename) # we ignore any viewer errors since it's not an essential operation

    return False


def src_Convert_8BitTo16Bit(image: np.ndarray) -> np.ndarray:

    """
    Converts image from 8-bit to 16-bit integer, if it's not already 16-bits

    :param image: Image to convert
    :return: (bool, image) True with new if image was converted, False with original image otherwise
    """

    assert (image.dtype == np.uint8) or (image.dtype == np.uint16), f"src_Convert_8BitTo16Bit: Expected image to be either 8-bit or 16-bits but it is \"{image.dtype}\""
    origType, image = convertImageNumpyTypeIfNecessary(image, "uint16")
    return (origType != image.dtype, image)


def src_Convert16BitToNormalizedFloat(image: np.ndarray) -> np.ndarray:

    """
    Converts image from 16-bit uint to normalized float (ie, values from 0.0 to 1.0)

    :param image: Image to convert
    :return: (bool, image) True with new if image was converted, False with original image otherwise
    """

    origType, image = convertImageNumpyTypeIfNecessary(image, ImgFloatType)
    return (origType != image.dtype, image)


def src_ConvertNormalizedFloatTo16Bit(image: np.ndarray) -> np.ndarray:

    """
    Converts image from normalized float (ie, values from 0.0 to 1.0) to 16-bit uint

    :param image: Image to convert
    :return: (bool, image) True with new if image was converted, False with original image otherwise
    """

    origType, image = convertImageNumpyTypeIfNecessary(image, "uint16")
    return (origType != image.dtype, image)


def resizeImgToRawDimensions(image: np.ndarray, desc: str) -> np.ndarray:

    """
    Resizes image based on user's configuration

    :param image: Image to resize
    :param desc: Description of image, to be used in debug prints
    :return: (bool, image) True with new if image was generated, False with original image otherwise
    """

    origSrcDimensions = Dimensions(rows=image.shape[0], columns=image.shape[1])
    outputDimensions = Config.exif.rawDimensions;

    printI(f"{desc} image dimensions: {origSrcDimensions.columns}x{origSrcDimensions.rows}, Raw Dimensions: {outputDimensions.columns}x{outputDimensions.rows}",)
    srcGeomAdjustments = calcSrcGeomAdjustments(origSrcDimensions, outputDimensions,
        Config.args.re_geometry, Config.args.re_maintainaspectratio, Config.args.re_horzalign, Config.args.re_vertalign)
    printD(f"Resize: {desc} Calculated adjustments: {srcGeomAdjustments}")
    if not srcGeomAdjustments:
        # nothing to do
        return (False, image)
    if srcGeomAdjustments.resizeDimensions:
        image = image = cv2.resize(image, (srcGeomAdjustments.resizeDimensions.columns, srcGeomAdjustments.resizeDimensions.rows), interpolation=Config.args.re_algorithm)
    if srcGeomAdjustments.cropRect:
        image = image[srcGeomAdjustments.cropRect.starty:srcGeomAdjustments.cropRect.endy, srcGeomAdjustments.cropRect.startx:srcGeomAdjustments.cropRect.endx]

    newSrcDimensions = Dimensions(rows=image.shape[0], columns=image.shape[1])

    if (srcGeomAdjustments.posInTgt.x > 0) or (srcGeomAdjustments.posInTgt.y > 0) or (newSrcDimensions != outputDimensions):
        countBorderRowsAbove = srcGeomAdjustments.posInTgt.y
        countBorderRowsBelow = outputDimensions.rows - (newSrcDimensions.rows + srcGeomAdjustments.posInTgt.y)
        countBorderRowsLeft = srcGeomAdjustments.posInTgt.x
        countBorderRowsRight =  outputDimensions.columns - (newSrcDimensions.columns + srcGeomAdjustments.posInTgt.x)
        # RGB values below are multiplied by 256 to scale them from 8-bit to 16-bit
        image = cv2.copyMakeBorder(image, countBorderRowsAbove, countBorderRowsBelow, countBorderRowsLeft, countBorderRowsRight,
            cv2.BORDER_CONSTANT, value=((  ((Config.args.re_borderfillcolor & 0xff)*256), ((Config.args.re_borderfillcolor>>8 & 0xff)*256), ((Config.args.re_borderfillcolor>>16 & 0xff)*256))))

    finalSrcDimensions = Dimensions(rows=image.shape[0], columns=image.shape[1])
    assert finalSrcDimensions == outputDimensions, f"src_Resize: Internal error, {desc} resized from {origSrcDimensions} to {finalSrcDimensions} but raw is {outputDimensions}"

    return (True, image)


def src_Resize(image: np.ndarray) -> np.ndarray:

    """
    Resizes image based on user's configuration

    :param image: Image to resize
    :return: (bool, image) True with new if image was generated, False with original image otherwise
    """

    return resizeImgToRawDimensions(image, "source")



def src_ConvertToBayer(image: np.ndarray) -> np.ndarray:

    """
    Converts RGB image to either bayer RGGB image or grayscale, depending on source image and user configuration

    :param image: Image to convert
    :return: (bool, image) True with new if image was generated, False with original image otherwise
    """

    def colorToBayer(image: np.ndarray[tuple[int, int], np.dtype[np.uint16]]) -> np.ndarray[tuple[int, int], np.dtype[np.uint16]]:

        """
        Converts an RGB image (rows x columns x 3) into an RGGB bayered image (rows x columns)

        :param image: Image to convert
        :return: bAYER IMAGE
        """
        dimensions = Dimensions(rows=image.shape[0], columns=image.shape[1])
        bayer = np.empty((dimensions.rows, dimensions.columns), dtype=image.dtype)
        bayer[0::2,0::2] = image[0::2,0::2,2] # RGGB Red  = BGR Red
        bayer[0::2,1::2] = image[0::2,1::2,1] # RGGB G1   = BGR Green
        bayer[1::2,0::2] = image[1::2,0::2,1] # RGGB G2   = BGR Green
        bayer[1::2,1::2] = image[1::2,1::2,0] # RGGB Blue = BGR Blue
        return bayer

    fInputIsGrayscale = (image.ndim == 2)

    if fInputIsGrayscale:
        # image is already grayscale
        return (False, image)

    if Config.args.src_grayscale:
        image = cv2.cvtColor(image, cv2.COLOR_3GRAY)
    else:
        image = colorToBayer(image)

    return (True, image)


def convertImageNumpyTypeIfNecessary(image: np.ndarray, typeWanted: Type[type]) -> np.ndarray:

    """
    Converts numpy image array to specified type, if not already of the desired type

    :param image: image to change type
    :param typeWanted: numpy type wanted. Ex: np.uint16
    :return: (origType, image) The original numpy type of the image (used later to call this
    function again to convert back to original type), converted image (or original image if
    conversion wasn't necessary)
    """

    if type(typeWanted) is str:
        # convert type name in str to numpy dtype
        typeWanted = np.dtype(typeWanted)

    if (origType := image.dtype) == typeWanted:
        # already has desired type
        return (origType, image)

    if np.issubdtype(origType, np.integer) and np.issubdtype(typeWanted, np.floating):
        # going from integer -> normalized float. scale 2^bits integer value to 0.0..1.0
        image = image.astype(typeWanted)
        image /= (1 << origType.itemsize*8)-1
    elif np.issubdtype(origType, np.floating) and np.issubdtype(typeWanted, np.integer):
        # going from normalized float to integer. scale float value to 2^bits integer value
        image *= (1 << typeWanted.itemsize*8)-1
        image = image.astype(typeWanted)
    elif np.issubdtype(origType, np.integer) and np.issubdtype(typeWanted, np.integer):
        # going from one integer type to another integer type
        if origType.itemsize <= typeWanted.itemsize:
            # increasing bit-depth - scale values up
            image = image.astype(typeWanted)
            image <<= ((typeWanted.itemsize - origType.itemsize) * 8)
        else:
            # decreasing bit-depth - scale values down
            image >>= ((origType.itemsize - typeWanted.itemsize) * 8)
            image = image.astype(typeWanted)
    else:
        # float to another float type - no scaling necessary
        image = image.astype(typeWanted)

    return (origType, image)


def src_ModifyHSL(image: np.ndarray) -> np.ndarray:

    """
    Changes hue, saturation, and lightness of pixels

    :param image: image to change
    :return: (bool, image) True with modified image if HSL was modified, False with same image if not
    """
    if Config.args.src_hsl is None:
        return (False, image)
    assert np.issubdtype(image.dtype, np.floating), f"src_ModifyHSL: expecting image data type to be floating-point but encountered \"{image.dtype}\""
    image = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    image *= Config.args.src_hsl
    image = cv2.cvtColor(image, cv2.COLOR_HSV2BGR)

    return (True, image)


def src_ConvertSRGBToLinear(image: np.ndarray) -> np.ndarray:

    """
    Converts image from sRGB to Linear RGB

    :param image: sRGB bayeredimage to convert (float, normalized to 0.0 to 1.0)
    :return: (bool, image) True with new if image was generated, False with original image otherwise
    """

    if not Config.args.src_srgbtolinear:
        return (False, image)
    assert np.issubdtype(image.dtype, np.floating), f"src_ConvertSRGBToLinear: expecting image data type to be floating-point but encountered \"{image.dtype}\""
    image = np.where(image <= 0.04045,
        image / 12.92,
        ((image + 0.055) / 1.055)**2.4)
    return (True, image)


def src_ApplyInverseWbMultipliers(bayerImageFloat: np.ndarray) -> np.ndarray:

    """
     Applies inverse of WB multipliers, which is done to simulate the uneven color response of the image
     sensor since we're going from a normal image -> raw

    :param bayerImageFloat: sRGB bayeredimage to apply inverse WB multipliers to
    :return: (True, image) True with inverse WB multipliers applied
    """

    if Config.args.src_wbmultipliers is not None:
        # use overrode WB multipliers in template NEF EXIF. use the mulitipliers they specified
        wbMultipliers = Config.args.src_wbmultipliers
    else:
        wbMultipliers = Config.exif.wbMultipliers

    assert np.issubdtype(bayerImageFloat.dtype, np.floating), f"src_ApplyInverseWbMultipliers() expecting image data type to be floating-point but encountered \"{bayerImageFloat.dtype}\""
    assert bayerImageFloat.ndim==2, f"src_ApplyInverseWbMultipliers() expecting 2D bayer array but encountered {bayerImageFloat.shape}"
    bayerImageFloat[0::2, 0::2] = bayerImageFloat[0::2, 0::2] * (1/wbMultipliers.red)
    bayerImageFloat[1::2, 1::2] = bayerImageFloat[1::2, 1::2] * (1/wbMultipliers.blue)
    return (True, bayerImageFloat)


def src_ScaleNormalizedFloatTo14Bit(image: np.ndarray) -> np.ndarray:

    """
    Converts normalized float values to 14-bit uint16 values

    :param image: sRGB bayeredimage to scale values to 14-bits
    :return: (bool, image) True with image values scaled to 14-bits
    """

    assert np.issubdtype(image.dtype, np.floating), f"src_ScaleNormalizedFloatTo14Bit: expecting image data type to be floating-point but encountered \"{image.dtype}\""
    image *= (16383 - Config.exif.blackLevel);
    image = image.astype(np.uint16)
    return (True, image)


def src_AddBlackLevelBias(image: np.ndarray) -> np.ndarray:

    """
    Applies blacklevel bias to image data, as necessary to simulate raw data coming from the camera

    :param image: sRGB bayeredimage to apply black level bias
    :return: (bool, image) True with image with black level bias added
    """

    image += Config.exif.blackLevel
    return (True, image)


def printExecutionTime(desc: str, timeElapsed: float) -> None:

    """
    Prints the execution time of an operation

    :param desc: Text description of operation
    :param timeElapsed: Execution time of operation (from time.perf_counter)
    :return: None
    """

    if Config.args.showperfstats or isVerbose():
        printA(f"Perf: Completed {desc} in {timeElapsed / (1/1000):.2f} ms")


def execMethodPartialAndPrintExecutionTime(partialInst: partial) -> Any:

    """
    Executes a method, timing and printing its execution time.

    :param partialInst: Method and its argument, bound via functools.partial()
    :return: The return value from the method called
    """

    timeStart = time.perf_counter()
    result = partialInst()
    timeElapsed = time.perf_counter() - timeStart
    printExecutionTime(partialInst.func.__name__, timeElapsed)
    return result


def performSrcImageOpList(opsList: List[Callable[[np.ndarray], np.ndarray]], image):

    """
    Performs list of source image operations

    :param opsList: List containing references to methods to invoke; each is called, with the image data as
    a paramter and each returns the potentially-modified image data
    :param image: Image data to pass through operation methods
    :return: Image data modified by all operations in list
    """

    allOpsTimeStart = time.perf_counter()
    for op in opsList:
        timeStart = time.perf_counter()
        (fPerformedOp, image) = op(image)
        timeElapsed = time.perf_counter() - timeStart
        if fPerformedOp:
            printExecutionTime(op.__name__, timeElapsed)

    timeElapsed = time.perf_counter() - allOpsTimeStart
    return (timeElapsed, image)


def loadImage(filename:str) -> np.ndarray:

    """
    Uses opencv to load an image file

    :param filename: Filename of image to load
    :return: Numpy array with image or None if error. Prints error message on failure
    """

    #
    # load image into numpy array using opencv
    #
    image = cv2.imread(filename, cv2.IMREAD_UNCHANGED)
    if image is not None:
        return image

    #
    # image load failed. imread() doesn't throw exceptions or return error
    # codes so attempt to present useful info about why the image didn't load
    #
    if not os.path.isfile(filename):
        printE(f"Source image file \"{filename}\" doesn't exist")
        return None

    #
    # file exists. either not a valid image file or format not supported
    #
    printE(f"Error loading image \"{filename}\". Image format not supported?")
    return None


def processSourceImageData(image: np.ndarray) -> tuple[ np.ndarray[tuple[int, int], np.dtype[np.uint16]], np.ndarray[tuple[int, int], np.dtype[np.uint16]] ]:

    """
    Performs all the operations necessary on the source image to produce a final source image and bayered output suitable for raw encoding

    :param image: Source image
    :return: (image, bayeredImage) Source image fully processed, both in RGB and bayered form.
    """

    #
    # operations on the source image are split into two phases - first is all the
    # non-bayer specific transforms, such as resizing to output (raw) resolution, color
    # transforms, etc. Some of these operations are done against 16-bit image data, while
    # others use normalized float data. When done we have a source image that's usable for
    # encoding as the embedded jpg in the raw and for data that can be passed to the second
    # phase, which involves bayering it and applying raw-specific transforms like inverse
    # WB multipliers (to simulate RGB sensor response in reverse), black level bias addition,
    # etc - this second phase is also done in both integer and float parts
    #

    #
    # note: src_ConvertSRGBToLinear() is slow due to raised-power logic, so
    # try to run it after bayer conversion to execute faster (less data to convert vs RGB array)
    #

    sourceOps = [

        # first do integer-based operations
        src_Convert_8BitTo16Bit,
        src_Resize,

        # now do operations that require float
        src_Convert16BitToNormalizedFloat,
        src_ModifyHSL,

        # all source operations are done. convet back to 16-bit integer
        src_ConvertNormalizedFloatTo16Bit,
    ]

    bayerOps = [

        # we enter this phase with 16-bit data

        # bayer the image
        src_ConvertToBayer,

        # now do operations on float bayered data
        src_Convert16BitToNormalizedFloat,
        src_ConvertSRGBToLinear,
        src_ApplyInverseWbMultipliers,

        # convert float bayered back to 16-bit but scaled to 14-bit values (in prepration for 14-bit raw encoding)
        src_ScaleNormalizedFloatTo14Bit,
        src_AddBlackLevelBias
    ]

    (totalTimeElapsed, image) = performSrcImageOpList(sourceOps, image)
    printExecutionTime("*** all source ops ***", totalTimeElapsed)

    (totalTimeElapsed, bayeredImage) = performSrcImageOpList(bayerOps, image)
    printExecutionTime("*** all bayer ops ***", totalTimeElapsed)

    return (image, bayeredImage)


def processSourceImageFile(filename: str) -> tuple[ np.ndarray[tuple[int, int], np.dtype[np.uint16]], np.ndarray[tuple[int, int], np.dtype[np.uint16]] ]:

    """
    Performs all the operations necessary on the source image to get it ready for encoding to raw

    :return: (image, bayeredImage) Source image fully processed, both in RGB and bayered form
    """

    image = loadImage(filename)
    if image is None:
        return (None, None)

    return processSourceImageData(image)


def processSourceNumpy(filename) -> tuple[ np.ndarray[tuple[int, int], np.dtype[np.uint16]], np.ndarray[tuple[int, int], np.dtype[np.uint16]] ]:

    """
    Performs all the operations necessary on the source image contained in a numpy file

    :param filename: Numpy filename containing image data.
    :return: (image, bayeredImage) Source image fully processed, both in RGB and bayered form. image will be
    None if there was no non-bayered source available
    """

    def validateBayeredNpyData(data: np.ndarray) -> bool:

        """
        Validates numpy data loaded, to make sure it contains valid image data that's encodable

        :param data: Numpy array to validate
        :return: (image, bayeredImage) Source image fully processed, both in RGB and bayered form. image will be
        None if there was no non-bayered source available
        """

        if data.max() >= 2**14:
            printE(f"\"{filename}\" has pixels >= 2^14 - cannot encode")
            return True
        if Config.exif.blackLevel > 0:
            if data.min() < Config.exif.blackLevel:
                printW(f"\"{filename}\" has pixels < blackLevel of {Config.exif.blackLevel}")
        return False

    rawDimensions = Config.exif.rawDimensions;

    try:
        input = np.load(filename)
    except Exception as e:
        printE(f"Error loading numpy file \"{filename}\": {e}")
        return (None, None)

    if input.dtype != np.uint16:
        printE(f"Numpy array must be uint16 - \"{filename}\" is {input.dtype}")
        return (None, None)

    numDimensions = input.ndim
    if numDimensions >= 2:

        inputDimensions = Dimensions(rows=input.shape[0], columns=input.shape[1])

        if numDimensions == 2:
            # appears to be in the format: rows x columns, so assume it's a bayered image (though it might also be a grayscale image)

            if validateBayeredNpyData(input):
                return (None, None)

            #
            # calculate crop and/or padding needed to fit input image onto raw dimensions.
            #
            srcGeomAdjustments = calcSrcGeomAdjustments(inputDimensions, rawDimensions,
                ResizeGeom.NONE, fMaintainAspectRatio=False, horzAlignment=Config.args.re_horzalign, vertAlignment=Config.args.re_vertalign)
            posInTgt = Coordinate(x=0, y=0) # assume no padding
            cropRect = Rect(startx=0, starty=0, endx=inputDimensions.columns, endy=inputDimensions.rows) # assume no cropping
            if srcGeomAdjustments:
                posInTgt = srcGeomAdjustments.posInTgt
                if srcGeomAdjustments.cropRect:
                    cropRect = srcGeomAdjustments.cropRect

            bayeredImage = np.full((rawDimensions.rows, rawDimensions.columns), Config.exif.blackLevel, dtype=np.uint16)

            origShape = input.shape
            bayeredImage[posInTgt.y : posInTgt.y+cropRect.endy :, posInTgt.x : posInTgt.x+cropRect.endx :] =\
                input[cropRect.starty : cropRect.endy :, cropRect.startx : cropRect.endx :]

            newShape = bayeredImage.shape
            if origShape != newShape:
                printV(f"Resized \"{filename}\" input from {origShape} to {newShape}")

            return (None, bayeredImage)


        if numDimensions == 3:

            numColorChannels = input.shape[2]

            if numColorChannels == 3:
                # appears to be in the format: rows x columns x RGB color channels, so assume it's an RGB image
                return processSourceImageData(input)

            if numColorChannels == 4:
                # appears to be in the format: rows x columns x bayer color channel, for example from https://github.com/SonyResearch/

                if validateBayeredNpyData(input):
                    return (None, None)

                #
                # calculate crop and/or padding needed to fit input bayer image onto raw dimensions. In reviewing these calculations,
                # keep in mind that each color bayer layer in the input array has 1/2 the number of columns and rows
                #

                colorChannelDimensionsAsBayer = Dimensions(rows=inputDimensions.rows*2, columns=inputDimensions.columns*2) # x2 to normalize color channel resolution to full bayer for calcSrcGeomAdjustments()
                srcGeomAdjustments = calcSrcGeomAdjustments(colorChannelDimensionsAsBayer, rawDimensions,
                    ResizeGeom.NONE, fMaintainAspectRatio=False, horzAlignment=Config.args.re_horzalign, vertAlignment=Config.args.re_vertalign)
                posInTgt = Coordinate(x=0, y=0) # assume no padding
                cropRect = Rect(startx=0, starty=0, endx=colorChannelDimensionsAsBayer.columns, endy=colorChannelDimensionsAsBayer.rows) # assume no cropping
                if srcGeomAdjustments:
                    posInTgt = srcGeomAdjustments.posInTgt
                    if srcGeomAdjustments.cropRect:
                        cropRect = srcGeomAdjustments.cropRect

                bayeredImage = np.full((rawDimensions.rows, rawDimensions.columns), Config.exif.blackLevel, dtype=np.uint16)

                origShape = (input.shape[0]*2, input.shape[1]*2)
                bayeredImage[0+posInTgt.y : posInTgt.y+cropRect.endy : 2, 0+posInTgt.x : posInTgt.x+cropRect.endx : 2] =\
                    input[cropRect.starty//2  : cropRect.endy//2 :, cropRect.startx//2 : cropRect.endx//2 :,0]
                bayeredImage[0+posInTgt.y : posInTgt.y+cropRect.endy : 2, 1+posInTgt.x : posInTgt.x+cropRect.endx : 2] =\
                    input[cropRect.starty//2  : cropRect.endy//2 :, cropRect.startx//2 : cropRect.endx//2 :,1]
                bayeredImage[1+posInTgt.y : posInTgt.y+cropRect.endy : 2, 0+posInTgt.x : posInTgt.x+cropRect.endx : 2] =\
                    input[cropRect.starty//2  : cropRect.endy//2 :, cropRect.startx//2 : cropRect.endx//2 :,2]
                bayeredImage[1+posInTgt.y : posInTgt.y+cropRect.endy : 2, 1+posInTgt.x : posInTgt.x+cropRect.endx : 2] =\
                    input[cropRect.starty//2  : cropRect.endy//2 :, cropRect.startx//2 : cropRect.endx//2 :,3]

                newShape = bayeredImage.shape
                if origShape[0]*2 != newShape[0] or origShape[1]*2 != newShape[1]:
                    printV(f"Resized \"{filename}\" input from {origShape} to {newShape}")

                return (None, bayeredImage)

            printE(f"Numpy array from \"{filename}\" is 3D {input.shape}: 1st dimension must be either x3 deep (RGB image with 3 color channels) or x4 deep (bayer image with 4 channels, ie RGGB)")
            return (None, None)

    printE(f"Can't identify image data type from \"{filename}\" from its shape {input.shape}")
    return (None, None)


def processSourceFile() -> tuple[ np.ndarray[tuple[int, int], np.dtype[np.uint16]], np.ndarray[tuple[int, int], np.dtype[np.uint16]] ]:

    """
    Performs all the operations necessary on the source image to get it ready for encoding to raw

    :return: (image, bayeredImage) Source image fully processed, both in RGB and bayered form. image will be
    None if there was no non-bayered source available
    """

    filename = Config.args.inputfilename

    _, ext = os.path.splitext(filename)
    if ext:
        ext = ext.lstrip('.').upper()   # convert to uppercase, stirp off leading period
        match ext:
            case "NPY":
                return processSourceNumpy(filename)

    # asssume the file is an image that opencv can handle
    return processSourceImageFile(filename)


def resolveTemplateNefSource():

    """
    Determines the source of our template NEF filename. This app has a feature where the user can specify
    a shorthand name of just the camera model for the template nef instead of a filename - we'll check that
    shorthand name against a file in our script's "templatenef" directory and use it if available

    :return: False if successful, True if error
    """

    if os.path.isfile(Config.args.templatenef):
        # a file exits with the specified name, so presume it's not a shorthand name
        return False

    # check if an NEF exist by the shorthand name in our script's "templatenef" directory. for
    # example, if the user specified "Z6III" as the template NEF, we'll check our
    # script directory for a file named .\templatenef\Z6III.NEF
    dir, root, ext = splitPathIntoParts(Config.args.templatenef)

    templateNefDir = os.path.join(getScriptDir(), "templatenef")
    potentialTemplateNefFilename = os.path.join(templateNefDir, root + ".NEF")
    if os.path.isfile(potentialTemplateNefFilename):
        # found a matching file for the shortname name. change the config to reflect this file
        Config.args.templatenef = potentialTemplateNefFilename
        return False

    printE(f"The template NEF specified \"{Config.args.templatenef}\" doesn't exist, either as a file or in the template directory \"{templateNefDir}\"")
    return True


def run() -> bool:

    """
    main module routine

    :return: False if successful, True if error
    """

    # process the cmd line
    Config.args = processCmdLine()
    if Config.args is None:
        return True

    printI(f"{AppName} v{AppVersion}")
    printD(f"Args: {Config.args}")

    # determine the template NEF we'll be using
    if resolveTemplateNefSource():
        return True

    # process the template NEF and make sure it's the type we're expecting
    Config.exif  = extractExifFromNEF(Config.args.templatenef)
    if Config.exif is None:
        return True
    printD(f"Template EXIF: {Config.exif}")

    # process the source image, which results in both bayer output and the fully-processed source image (to generated embedded jpgs from)
    (image, bayeredImage) = processSourceFile()
    if bayeredImage is None:
        return True

    # encode the source image using Nikon's lossless compression
    encodedImageData = execMethodPartialAndPrintExecutionTime(partial(src_EncodeToNikonLossless, bayeredImage))
    if encodedImageData is None:
        return True
    bytesCompressed = len(encodedImageData)
    bytesUncompressed = int(Config.exif.rawDimensions.columns * Config.exif.rawDimensions.rows * 14 / 8);
    printI(f"NEF: {bytesCompressed:,} compressed bytes, which is {float(bytesCompressed) / bytesUncompressed * 100:.2f}% of 14-bit image size ({bytesUncompressed:,} bytes)")

    # write encoded raw data into NEF, including generating the embedded jpgs
    fWriteFailed = writeOutputNEF(image, encodedImageData)
    if fWriteFailed:
        printE("Error generating/writing output NEF")
        return True

    # if running in Python debugger, break now to examine vars
    if "pdb" in sys.modules:
        breakpoint()

    return False


if __name__ == "__main__":
    fError = run()
    sys.exit(fError)
