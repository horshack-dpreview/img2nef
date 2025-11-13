#!/usr/bin/env python3
"""
createoverlay.py
This app generates a camera viewfinder/LCD overlay image that contains customing framing guides (lines) and shooting grids.
The overlay image can be then passed into img2nef to genereat raw images to use as custom viewfinder overlays on Nikon cameras
via the multiple-exposure overlay feature.

To draw a framelines/gridlines this app needs two sets of dimensions - raw and jpg. Both are automatically
generated if the user passes in a camera model listed in cameras.py. If a model is not specified or
supported then the dimensions must be provided manually via the --dimensions option.

The raw dimensions determine the size of the generated image and should match the camera's EXIF raw
dimensions, which can be obtained via the ImageWidth and ImageHeight fields. The jpg dimensions
determine which part of the raw image we draw on to. Most cameras have a slight crop from
raw -> jpg, with the crop implemented as borders on all sides of the full raw dimensions
"""

#
# verify python version early, before executing any logic that relies on features not available in all versions
#
import sys
if (sys.version_info.major < 3) or (sys.version_info.minor < 10):
    print("Requires Python v3.10 or later but you're running v{}.{}.{}".format(sys.version_info.major, sys.version_info.minor, sys.version_info.micro))
    sys.exit(1)

#
# imports
#
import argparse
import cameras
from   enum import Enum
import importlib
import math
import os
import platform
import re
import subprocess
import sys
import types
from   typing import Any, Callable, List, NamedTuple, Tuple, Type

#
# types
#
class IfFileExists(Enum): ADDSUFFIX=0; OVERWRITE=1; EXIT=2
class Verbosity(Enum): SILENT=0; WARNING=1; INFO=2; VERBOSE=3; DEBUG=4
class LineWidthExpansion(Enum): EXPAND_CENTERED=0; EXPAND_RIGHT_DOWN=1; EXPAND_LEFT_UP=2;
class VertPos(Enum): TOP=0; CENTER=1; BOTTOM=2
class HorzPos(Enum): LEFT=0; CENTER=1; RIGHT=2
Dimensions = NamedTuple('Dimensions', [('columns', int), ('rows', int)])
RGB = NamedTuple('RGB', [('red', int), ('green', int), ('blue', int)])
DashedLine = NamedTuple('DashedLine', [('dashLength', int), ('dashGap', int)])
LabelPos = NamedTuple('LabelPos', [('vertPos', VertPos), ('horzPos', HorzPos)])
Frameline = NamedTuple('Frameline', [('aspectRatio', Dimensions), ('lineWidth', int), ('dashedLine', DashedLine), ('lineColor', RGB), ('fillColor', RGB), ('labelPos', LabelPos)])
Gridline = NamedTuple('Gridline', [('gridDimensions', Dimensions), ('aspectRatio', Dimensions), ('lineWidth', int), ('dashedLine', DashedLine), ('lineColor', RGB)])

#
# module data
#
AppName = "createoverlay"
AppVersion = "1.00"
Config = types.SimpleNamespace()
IfFileExistsStrs = [x.name for x in IfFileExists]
VerbosityStrs = [x.name for x in Verbosity]
VertPosStrs = [x.name for x in VertPos]
HorzPosStrs = [x.name for x in HorzPos]


#
# verify all optional modules we need are installed before we attempt to import them.
# this allows us to display a user-friendly message for the missing modules instead of the
# python-generated error message for missing imports
#
if __name__ == "__main__":
    RequiredModule = NamedTuple('RequiredModule', [('importName', str), ('pipInstallName', str)])
    def verifyRequiredModulesInstalled():
        requiredModules = [
            RequiredModule(importName="PIL", pipInstallName="pillow"),
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
            sys.exit(1)

    verifyRequiredModulesInstalled()


#
# import optional modules now we've established they're available
#
from   PIL import Image, ImageDraw, ImageFont


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

    def strDimensionsToDimensions(string: str) -> Dimensions:
        dimensionStrs = string.split('x')
        if len(dimensionStrs) != 2:
            printE(f"Dimension ust be specified as a pair, ex: 6000x4000, but \"{string}\" was specified instead.")
            return None
        columnStr, rowStr = dimensionStrs
        if (not columnStr.isdigit()) or (not rowStr.isdigit()):
            printE(f"Dimensions must be in the format of \"columns x rows\" (ex: \"6000x4000\") but {string} was specified instead.")
            return None
        return Dimensions(columns=int(columnStr), rows=int(rowStr))

    def parseDelimitedString(string: str, delimiter: str, numValues: int, descForError: str):
        if (not string) or (string == 'none'):
            return False, None
        string = string.replace(" ", "") # remove all spaces before parsing
        strList = string.split(delimiter)
        if len(strList) != numValues:
            printE(f"{descForError} but \"{string}\" was specified instead.")
            return True, None
        return False, strList

    def convertDelimitedIntValueString(string: str, delimiter: str, numValues: int, descForError: str) -> tuple[bool, List]:
        fConversionError, strList = parseDelimitedString(string, delimiter, numValues, descForError)
        if fConversionError or (not strList):
            return fConversionError, strList
        if not all(s.isdigit() for s in strList):
            printE(f"{descForError} and values must be valid integer digits [0-9] but \"{string}\" was specified instead.")
            return True, None
        valueList = [int(s) for s in strList]
        return False, valueList

    def convertRgbStr(rgbHexStr: str) -> tuple[bool, RGB]:
        if (not rgbHexStr) or (rgbHexStr == 'none'):
            return False, None
        m = re.search(r"#([0-9a-f][0-9a-f])([0-9a-f][0-9a-f])([0-9a-f][0-9a-f])", rgbHexStr)
        if not m:
            printE(f"RGB must be in the form of #RRGGBB, where RGB are hex digits. \"{rgbHexStr}\" was specified instead.")
            return True, None
        return False, RGB(int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16))

    def convertRatioStr(string: str, ratioDesc: str) -> tuple[bool, Dimensions]:
        fConversionError, valueList = convertDelimitedIntValueString(string=string, delimiter=":", numValues=2, descForError=f"{ratioDesc} must be in the form of width:height")
        if fConversionError or not valueList:
            return fConversionError, valueList
        return False, Dimensions(columns=valueList[0], rows=valueList[1])

    def convertDimensionsStr(string: str, dimensionsDesc: str) -> tuple[bool, Dimensions]:
        fConversionError, valueList = convertDelimitedIntValueString(string=string, delimiter="x", numValues=2, descForError=f"{dimensionsDesc} must be in the form of columns x rows")
        if fConversionError or not valueList:
            return fConversionError, valueList
        return False, Dimensions(columns=valueList[0], rows=valueList[1])

    def convertLineWidthStr(string: str) -> tuple[bool, int]:
        if (not string) or (string == 'none'):
            return False, None
        try:
            value = int(string)
        except:
            printE(f"Line width must be valid integer digits [0-9] but \"{string}\" was specified instead.")
            return True, None
        return False, value

    def convertDashedLineStr(string: str) -> tuple[bool, DashedLine]:
        fConversionError, dashedLineValues = convertDelimitedIntValueString(string, delimiter="-", numValues=2, descForError="Dashed line must be in the form of line_length-gap_length")
        if fConversionError or not dashedLineValues:
            return fConversionError, dashedLineValues
        dashLength = dashedLineValues[0]
        dashGap = dashedLineValues[1]
        if dashLength <= 0:
            printE(f"Dot length value must be >= 0 but \"{string}\" was specified instead.")
            return True, None
        return False, DashedLine(dashLength=dashLength, dashGap=dashGap)

    def convertColorStr(string: str) -> tuple[bool, RGB]:
        return convertRgbStr(string)

    def convertLabelPosStr(string: str) -> tuple[bool, LabelPos]:
        fConversionError, strList = parseDelimitedString(string.upper(), '-', 2, "Label position must be in the form of vertdesc:horzdesc")
        if fConversionError or (not strList):
            return fConversionError, strList
        vertPosStr, horzPosStr = strList
        if vertPosStr not in VertPosStrs:
            printE(f"Invalid vertical position: Valid values are: {VertPosStrs}")
            return True, None
        if horzPosStr not in HorzPosStrs:
            printE(f"Invalid horizontal position: Valid values are: {HorzPosStrs}")
            return True, None
        labelPos = LabelPos(vertPos=VertPos[vertPosStr], horzPos=HorzPos[horzPosStr])
        return False, labelPos

    def parseAttributeValuePairs(attributeValueStr: str, attributeOrderForUnamedFields: List, optionDescStr: str):

        # initialize dict with None for all values, to handle the case of values not specified in 'attributeValueStr'
        attributeValueDict = dict()
        for attributeStr in attributeOrderForUnamedFields:
            attributeValueDict[attributeStr] = None

        attributeValueListStr = attributeValueStr.split(',')
        indexForUnamedField = 0
        for index, attributeAndValueStr in enumerate(attributeValueListStr):
            if indexForUnamedField >= len(attributeOrderForUnamedFields):
                printE(f"Too many values specified for \"{optionDescStr}\" \"{attributeValueStr}\"")
                return None
            if '=' in attributeAndValueStr:
                attributeStr, valueStr = attributeAndValueStr.split('=')
            else:
                attributeStr = attributeOrderForUnamedFields[indexForUnamedField]
                valueStr = attributeAndValueStr
            attributeStr = attributeStr.lower()
            if attributeStr not in attributeOrderForUnamedFields:
                printE(f"Uknown or unexpected attribute \"{attributeStr}\" for \"{optionDescStr}\" \"{attributeValueStr}\"")
                return None
            match attributeStr:
                case "aspectratio":
                    fConversionError, value = convertRatioStr(valueStr, "Aspect ratio")
                case "griddimensions":
                    fConversionError, value = convertDimensionsStr(valueStr, "Grid dimensions")
                case "linewidth":
                    fConversionError, value = convertLineWidthStr(valueStr)
                case "dashedline":
                    fConversionError, value = convertDashedLineStr(valueStr)
                case "linecolor":
                    fConversionError, value = convertColorStr(valueStr)
                case "fillcolor":
                    fConversionError, value = convertColorStr(valueStr)
                case "labelpos":
                    fConversionError, value = convertLabelPosStr(valueStr)
            if fConversionError:
                return None
            attributeValueDict[attributeStr] = value
            # if user specified attribute by name, then next (possibly unamed) attribute we expect after is the one after the attribute user specified (orderi in attributeOrderForUnamedFields)
            indexForUnamedField = attributeOrderForUnamedFields.index(attributeStr)+1
        return attributeValueDict

    # arg parser that throws exceptions on errors
    parser = ArgumentParserWithException(fromfile_prefix_chars='!',\
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""Generates custom camera frame and gridline display images, which can be passed into img2nef to generate an NEF to use with Nikon's multiple-exposure overlay feature for custom in-camera viewfinder overlays. (Written by Horshack)""",
        epilog="Options can also be specified from a file. Use !<filename>. Each word in the file must be on its own line.\n\nYou "\
            "can abbreviate any argument name provided you use enough characters to uniquely distinguish it from other argument names.\n")

    parser.add_argument('camera', metavar="model", nargs='?', type=str.upper, default=None, help="""Build for a predefined camera model. Use --list-cameras to see models supported. If your model isn't
        supported then you'll need to manually specify the raw and jpg dimensions via --dimensions""")
    parser.add_argument('--dimensions', metavar="raw columns x rows, jpg columns x rows", type=str.lower, required=False, action='append', help="Manually specify dimensions (typically when camera model isn't specified). Ex: --dimensions 6048x4032,6000x4000")
    parser.add_argument('--backgroundcolor', dest='backgroundColor', metavar="#RRGGBB", type=str, default='#000000', help="Backround color for entire overlay in #RRGGBB. Ex: --backgroundcolor #ff0000. Default is %(default)s.")
    parser.add_argument('--frameline', metavar="aspectratio=columns:rows,[linewidth=#pixels],[dashedline=dashlen-gaplen,[linecolor=#RRGGBB],[fillcolor=#RRGGBB],[labelpos=vert-horz]", type=str.lower, required=False, action='append',
        help="""Multiple framelines can be specified. Ex: --frameline 16:9,32,50-100,#ff0000,#000000,bottom-left. Creates 16:9 frameline, line width 32, dashed line segments of 50 pixels with 100 pixel gaps,
        line color of red, fill color of black.
        You can empty fields to skip values - default values are used for skipped fields. Ex: --frameline 16:9,,,#ff0000. Creates 16:9 frameline with default line width and dashed spec, line color of red, default fill color.""")
    parser.add_argument('--gridline',  metavar="griddimensions=columns x rows,[aspectratio=columns:rows],[linewidth=pixels],[dashedline=dashlen-gaplen],[linecolor=#RRGGBB]", type=str.lower, required=False, action='append',
        help="""Multiple gridlines can be specified. Ex: --gridline 4x4,16:9,32,none,#ff0000 - Draws a grid of 4 columns and rows inside a 16:9 aspect ratio area, line width of 32, no dashed lines, line color of red.
        Use empty fields to skip value and use default for the value instead.""")
    parser.add_argument('--labelpos', dest='labelPos', metavar="vertpos-horzpos", type=str.upper, default="BOTTOM-LEFT", help="""The position of the aspect-ratio label.
        'vertpos' values are TOP, CENTER, BOTTOM. 'horzpos' values are LEFT, CENTER, RIGHT. Specify "none" for no label. Ex: --labelpos TOP-RIGHT. Default is %(default)s.""")
    parser.add_argument('--fontsizepct', dest='fontSizePct', metavar="Font size as %", type=str.lower, default="5", help="Font size as percentage of raw height. Default is %(default)s%%.")
    parser.add_argument('--outputfilename', metavar="<filename>", help="""Optional - If not specified then the output filename will be generated based on the frame and gridlines specified.
        If specified and includes a path and --outputdir is also specified then path is replaced by --outputdir.""")
    parser.add_argument('--outputdir', type=str, metavar="path", help="Directory to store generated output.  Default is current directory. If path contains any spaces enclose it in double quotes. Example: --outputdir \"c:\\My Documents\"", default=None, required=False)
    parser.add_argument('--imagetype', dest='imageTypeExtension', type=str, metavar="extension", default="PNG", required=False, help="Image type, specified via extension. Default is \"%(default)s\".")
    parser.add_argument('--openinviewer', dest='openInViewer', type=strValueToBool, nargs='?', default=True, const=True, metavar="yes/no", help="Open in default image viewer/editor after creating. Default is %(default)s.")
    parser.add_argument('--ifexists', type=str.upper, choices=IfFileExistsStrs, default='ADDSUFFIX', required=False, help="""Action to take if an output file already exists. Default is \"%(default)s\",
        which means a suffix is added to the output filename to create a unique filename.""")

    defaultDrawOptions = parser.add_argument_group("Default Draw Options", "Default drawing options when not specified in --frameline and --gridline.")
    defaultDrawOptions.add_argument('--linewidth', dest='lineWidth', metavar="pixels", type=str.lower, default="32", help="Line width. Default is %(default)s.")
    defaultDrawOptions.add_argument('--dashedline', dest='dashedLine', metavar="dashlen-gaplen", type=str.lower, default=None, help="""Line dashing . Each segment drawn
        for 'dashlen' pixels and 'gaplen' empty pixels between each segment. Specify \"NONE\" for solid lines. Default is %(default)s.
        Ex: --dashedline=10-50. Creates a dashed line with solid segments of 10 pixels and gaps of 50 pixels.""")
    defaultDrawOptions.add_argument('--linecolor', dest='lineColor', metavar="#RRGGBB", type=str.lower, default='#FFFFFF', help="Line color. Default is %(default)s.")
    defaultDrawOptions.add_argument('--fillcolor', dest='fillColor', metavar="#RRGGBB", type=str.lower, default=None, help="Fill color. Default is %(default)s.")

    parser.add_argument('--generatenef', dest='generatenef', type=strValueToBool, nargs='?', default=True, const=True, metavar="yes/no", help="Generate NEF with img2nef after creating overlay. Default is %(default)s.")

    parser.add_argument('--verbosity', type=str.upper, choices=VerbosityStrs, default="INFO", required=False, help="How much information to print during execution.. Default is %(default)s.")
    parser.add_argument('--list-cameras', dest='fListCameras', action='store_true', help="Show list of predefined camera models supported")

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

    if args.fListCameras:
        printA(f"Camera models supported:")
        cameras.listCameras()
        sys.exit(0)

    # do post-processing/conversion of args

    if args.camera and args.dimensions:
        printW(f"Both a camera model and manual dimensions were provided. The values for --dimensions will be used.")

    if args.generatenef and not args.camera:
        printE(f"A camera model must be specified when --generatenef is used")
        return None

    if args.dimensions:
        # ex: "6048x4032,6000x4000"
        dimensionStrs = args.dimensions[0].split(',')
        if len(dimensionStrs) != 2:
            printE("--dimensions must be specified as a pair, the 1st for raw and 2nd for jpg. ex: --dimensions 6048x4032,6000x4000")
            return None
        args.rawDimensions = strDimensionsToDimensions(dimensionStrs[0])
        if not args.rawDimensions:
            return None
        args.jpgDimensions = strDimensionsToDimensions(dimensionStrs[1])
        if not args.jpgDimensions:
            return None
    else:
        if not args.camera:
            printE("Dimensions of image must be specified, either implicitly by a camera model or --dimensions")
            return None

    fConversionError, args.lineWidth = convertLineWidthStr(args.lineWidth)
    if fConversionError:
        return None

    fConversionError, args.dashedLine = convertDashedLineStr(args.dashedLine)
    if fConversionError:
        return None

    fConversionError, args.lineColor = convertRgbStr(args.lineColor)
    if fConversionError:
        return None

    fConversionError, args.fillColor = convertRgbStr(args.fillColor)
    if fConversionError:
        return None

    fConversionError, args.backgroundColor = convertRgbStr(args.backgroundColor)
    if fConversionError:
        return None

    fConversionError, args.labelPos = convertLabelPosStr(args.labelPos)
    if fConversionError:
        return None

    #
    # convert --frameline entries into a Frameline list. Note we do this after processing/conversion
    # of all the default values, since we'll potentially reference those
    #
    args.framelines = list()
    if args.frameline:
        for framelineArgStr in args.frameline:
            attributeValueDict = parseAttributeValuePairs(framelineArgStr, ["aspectratio", "linewidth", "dashedline", "linecolor", "fillcolor", "labelpos"], "--frameline")
            if not attributeValueDict:
                return None
            if not attributeValueDict['aspectratio']:
                printE(f"Aspect ratio must be specified for --frameline")
                return None
            lineWidth = attributeValueDict['linewidth'] if (attributeValueDict['linewidth'] is not None) else args.lineWidth
            dashedLine = attributeValueDict['dashedline'] if (attributeValueDict['dashedline'] is not None) else args.dashedLine
            lineColor = attributeValueDict['linecolor'] if (attributeValueDict['linecolor'] is not None) else args.lineColor
            fillColor = attributeValueDict['fillcolor'] if (attributeValueDict['fillcolor'] is not None) else args.fillColor
            labelPos = attributeValueDict['labelpos'] if (attributeValueDict['labelpos'] is not None) else args.labelPos
            args.framelines.append(Frameline(aspectRatio=attributeValueDict['aspectratio'], lineWidth=lineWidth, dashedLine=dashedLine, lineColor=lineColor, fillColor=fillColor, labelPos=labelPos))

    #
    # convert --gridline entries into a Gridline list. Note we do this after processing/conversion
    # of all the default values, since we'll potentially reference those
    #
    args.gridlines = list()
    if args.gridline:
        for gridlineArgStr in args.gridline:
            attributeValueDict = parseAttributeValuePairs(gridlineArgStr, ["griddimensions", "aspectratio", "linewidth", "dashedline", "linecolor"], "--gridline")
            if not attributeValueDict:
                return None
            if not attributeValueDict['griddimensions']:
                printE(f"Grid dimensions must be specified for --gridline")
                return None
            lineWidth = attributeValueDict['linewidth'] if (attributeValueDict['linewidth'] is not None) else args.lineWidth
            dashedLine = attributeValueDict['dashedline'] if (attributeValueDict['dashedline'] is not None) else args.dashedLine
            lineColor = attributeValueDict['linecolor'] if (attributeValueDict['linecolor'] is not None) else args.lineColor

            args.gridlines.append(Gridline(gridDimensions=attributeValueDict['griddimensions'], aspectRatio= attributeValueDict['aspectratio'],
                lineWidth=lineWidth, dashedLine=dashedLine, lineColor=lineColor))

    if len(args.framelines) == 0 and len(args.gridlines) == 0:
        printE("At least one --frameline or --gridline must be specified.")
        sys.exit(1)

    # process font size
    fontSizePctStr = args.fontSizePct.rstrip("%")
    try:
        fontSizePct = float(fontSizePctStr)
        if fontSizePct < 0 or fontSizePct > 100:
            raise ValueError("")
    except:
        printE(f"--fontsizepct value specified \"{fontSizePctStr}\" is invalid. It must be a number from 0 to 100. Decimal values are allowed.")
        return None
    args.fontSizePct = fontSizePct/100

    # convert from strs to enumerated values
    args.ifexists = IfFileExists[args.ifexists]
    args.verbosity = Verbosity[args.verbosity]

    return args


def runImg2nef(overlayFilename: str):

    """
    Executes img2nef to generate an NEF with the overlay we just created

    :param overlayFilename: Path to overlay file
    :return: False if successful, True if error
    """

    outputFilename = generateFilenameWithDifferentExtensionAndDir(overlayFilename, Config.args.outputdir, "NEF")
    try:
        import img2nef
    except Exception as e:
        printE(f"Unable to import the img2nef.py module needed to generate an NEF: {e}")
        return True
    argvSaved = sys.argv
    sys.argv = ['img2nef.py', Config.args.camera, overlayFilename, f'{outputFilename}', '--src.hsl=1.0,1.0,1.0', f'--verbosity={Config.args.verbosity.name}']
    if Config.args.outputdir:
        # even though 'outputFilename' includes a possible outputdir, specify again in case there's a different default included in a .options file for img2nef
        sys.argv.append(f'--outputdir={Config.args.outputdir}')
    printV(f"Calling img2nef to generate NEF, args: {sys.argv}")
    fimg2nefError = img2nef.run()
    if fimg2nefError:
        printE(f"Attempt to generate NEF with 'img2nef' failed")
    sys.argv = argvSaved
    return fimg2nefError


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

    :return: Output filename. sys.exit() is called for the case where we can't overwrite an existing file
    """

    outputFilename = Config.args.outputfilename
    if outputFilename is None:
        # user didn't specify an output filename - generate one ourselves
        outputFilename = "Overlay_"
        if Config.args.camera:
            outputFilename += f"{Config.args.camera}"
        else:
            outputFilename += f"{Config.args.jpgDimensions.columns}x{Config.args.jpgDimensions.rows}"
        for index, frameline in enumerate(Config.args.framelines):
            outputFilename += f"_Frame-{frameline.aspectRatio.columns}x{frameline.aspectRatio.rows}"
        for index, gridline in enumerate(Config.args.gridlines):
            outputFilename += f"_Grid-{gridline.gridDimensions.columns}x{gridline.gridDimensions.rows}"
        outputFilename = generateFilenameWithDifferentExtensionAndDir(outputFilename, Config.args.outputdir, Config.args.imageTypeExtension)
    else:
        # user specified output filename. if it didn't specify an extension, add it
        root, ext = os.path.splitext(outputFilename)
        if not ext:
            outputFilename = f"{outputFilename}.{Config.args.imageTypeExtension}"

        outputFilename = generateFilenameWithDifferentExtensionAndDir(outputFilename, Config.args.outputdir, None)

    match Config.args.ifexists:
        case IfFileExists.ADDSUFFIX:
            outputFilename = generateUniqueFilenameFromExistingIfNecessary(outputFilename)
        case IfFileExists.OVERWRITE:
             pass
        case IfFileExists.EXIT:
            if os.path.exists(outputFilename):
                printE(f"Output file \"{outputFilename}\" already exists. Exiting per --ifexists setting")
                sys.exit(1)

    return outputFilename


def calcAspectRatioDimensions(imageDimensions: Dimensions, desiredAspectRatioDimensions: Dimensions) -> Dimensions:

    """
    Calculates the dimensions of an aspect-ratio box that fits within the specified image dimensions

    :param imageDimensions: Image dimensions the aspect-ratio box must fit within
    :param desiredAspectRatioDimensions: Aspect ratio wanted
    :return: Dimensions of box that fit within the specified image dimensions and have the specified aspect ratio
    """

    imageAspectRatio = imageDimensions.columns / imageDimensions.rows
    desiredAspectRatio = desiredAspectRatioDimensions.columns / desiredAspectRatioDimensions.rows

    multiplier = imageAspectRatio / desiredAspectRatio

    if multiplier <= 1.0:
        # we will lose rows in image, ie use all image columns and calculate how many rows can fit
        columns = imageDimensions.columns
        rows = int(columns * (1/desiredAspectRatio))
    else:
        # we will lose columns in image, ie use all image rows and calculate how many columns can fit
        rows = imageDimensions.rows
        columns = int(rows * desiredAspectRatio)
    return Dimensions(columns, rows)


def calcLineWidthExpansion(coordinate: int, lineWidth: int, lineWidthExpansion: LineWidthExpansion) -> Tuple[int, int]:

    """
    Calculates how to draw the width of a line based on a specified expansion type. PIL's internal width implementation
    is always centered and doesn't handle fractional/remainders consistently, so we implement width ourselves by drawing
    multiple lines. This method determines how the pixels are distributed relative to the starting coordinate of the line

    :param coordinate: Starting coordinate to draw (either x or y coordinate, whichever is the variant)
    :param lineWidth: Width of line
    :param lineWidthExpansion: Determines how the line width is distributed around the coordinates. EXPAND_CENTERED splits
    the expansion evenly across both sides of the coordinate. EXPAND_RIGHT_DOWN expands to the right or down of the coordinate,
    while EXPAND_LEFT_UP expands to the left or up of the coordinate. EXPAND_RIGHT_DOWN and EXPAND_LEFT_UP are used to
    implement "inward" expansion, for example of a rectangle shape.
    :return: The starting and ending coordinate of the line, both inclusive
    """

    match lineWidthExpansion:
        case LineWidthExpansion.EXPAND_CENTERED:
            fIsOddWidth = lineWidth % 2 # if width is odd we'll including the remainder of one in ending coordinate
            start = coordinate-(lineWidth//2)
            end = coordinate+(lineWidth//2) + fIsOddWidth
        case LineWidthExpansion.EXPAND_RIGHT_DOWN:
            # y coordinate is a starting coordinate, so draw width by expanding down
            start = coordinate
            end = coordinate+lineWidth
        case LineWidthExpansion.EXPAND_LEFT_UP:
            # y coordinate is an ending coordinate, so draw width by expanding up
            start = (coordinate-lineWidth)+1 # note: ending coordinate is inclusive, so +1 to handle properly in for() loop below
            end = coordinate+1
    return (start, end)


def drawSolidHorzLine(draw: ImageDraw, x1: int, x2: int, y: int, lineWidth: int, lineWidthExpansion: LineWidthExpansion, lineColor: RGB):

    """
    Draws a solid horizontal line

    :param draw: Canvas to draw on
    :param x1: Starting x-coordiante
    :param x2: Ending x-coordinate (inclusive)
    :param y: y-coordinate
    :param lineWidth: Line width
    :param lineWidthExpansion: See calcLineWidthExpansion() documentation
    """

    sy, ey = calcLineWidthExpansion(y, lineWidth, lineWidthExpansion)
    for wy in range(sy, ey):
        draw.line([(x1, wy), (x2, wy)], width=1, fill=lineColor)


def drawSolidVertLine(draw: ImageDraw, y1: int, y2: int, x: int, lineWidth: int, lineWidthExpansion: LineWidthExpansion, lineColor: RGB):

    """
    Draws a solid vertical line

    :param draw: Canvas to draw on
    :param y1: Starting y-coordiante
    :param y2: Ending y-coordinate (inclusive)
    :param x: x-coordinate
    :param lineWidth: Line width
    :param lineWidthExpansion: See calcLineWidthExpansion() documentation
    :param lineColor: Color of line
    """

    sx, ex = calcLineWidthExpansion(x, lineWidth, lineWidthExpansion)
    for wx in range(sx, ex):
        draw.line([(wx, y1), (wx, y2)], width=1, fill=lineColor)


def calcDashedLineLastSegmentDrawLength(dashedLine: DashedLine, lineStart: int, lineEnd: int, lastDrawnCoordinate: int) -> int:

    """
    Calculates the length of the last segment of a dashed line. This is done to prevent a long gap in the corners of shape
    drawn with dashed lines.

    :param dashedLine: Dashed line specification
    :param lineStart: Starting line coordinate (x-coordinate for horizontal lines, y-coordinate for vertical lines)
    :param lineEnd: Ending line coordinate (x-coordinate for horizontal lines, y-coordinate for vertical lines)
    :param lastDrawnCoordinate: The ending coordinate of the last dashed line segment drawn
    :return: Length of an additional segment to draw, or zero if no additional segment is necessary
    """

    totalLineLen = (lineEnd - lineStart)+1
    maxEdgeGap = int(totalLineLen * .02) # debug: was .10
    edgeGap = (lineEnd - lastDrawnCoordinate)+1
    printD(f"Calc Dashed Last Segment: {totalLineLen=}, {maxEdgeGap=}, {edgeGap=}, return: {min(maxEdgeGap, dashedLine.dashLength) if edgeGap >= maxEdgeGap else 0}")
    if edgeGap < maxEdgeGap:
        return 0
    return min(maxEdgeGap, dashedLine.dashLength)


def drawHorzLine(draw: ImageDraw, x1: int, x2: int, y: int, lineWidth: int, lineWidthExpansion: LineWidthExpansion, dashedLine: DashedLine, lineColor: RGB, fCompleteDashedLineEdge: bool):

    """
    Draws a horizontal line, including support for dashed lines

    :param draw: Canvas to draw on
    :param x1: Starting x-coordiante
    :param x2: Ending x-coordinate (inclusive)
    :param y: y-coordinate
    :param lineWidth: Line width
    :param lineWidthExpansion: See drawSolidHorzLine() documentation
    :param dashedLine: Dashed line specification, or None for a solid line
    :param lineColor: Color of line
    :param fCompleteDashedLineEdge:
    """

    if not dashedLine:
        # solid line
        dashedLine = DashedLine(dashLength=sys.maxsize, dashGap=0)
    for x in range(x1, x2, dashedLine.dashLength + dashedLine.dashGap):
        endx = min(x + dashedLine.dashLength - 1, x2)
        drawSolidHorzLine(draw, x, endx, y, lineWidth, lineWidthExpansion, lineColor)
    if fCompleteDashedLineEdge:
        lastSegmentDrawLength = calcDashedLineLastSegmentDrawLength(dashedLine=dashedLine, lineStart=x1, lineEnd=x2, lastDrawnCoordinate=endx)
        if lastSegmentDrawLength > 0:
            drawSolidHorzLine(draw, x2-lastSegmentDrawLength, x2, y, lineWidth, lineWidthExpansion, lineColor)


def drawVertLine(draw: ImageDraw, y1: int, y2: int, x: int, lineWidth: int, lineWidthExpansion: LineWidthExpansion, dashedLine: DashedLine, lineColor: RGB, fCompleteDashedLineEdge: bool):

    """
    Draws a vertical line, including support for dashed lines

    :param draw: Canvas to draw on
    :param y1: Starting y-coordiante
    :param y2: Ending y-coordinate (inclusive)
    :param x: y-coordinate
    :param lineWidth: Line width
    :param lineWidthExpansion: See drawSolidHorzLine() documentation
    :param dashedLine: Dashed line specification, or None for a solid line
    :param lineColor: Color of line
    :param fCompleteDashedLineEdge:
    """

    if not dashedLine:
        # solid line
        dashedLine = DashedLine(dashLength=sys.maxsize, dashGap=0)
    for y in range(y1, y2, dashedLine.dashLength + dashedLine.dashGap):
        endy = min(y + dashedLine.dashLength - 1, y2)
        drawSolidVertLine(draw, y, endy, x, lineWidth, lineWidthExpansion, lineColor)
    if fCompleteDashedLineEdge:
        lastSegmentDrawLength = calcDashedLineLastSegmentDrawLength(dashedLine=dashedLine, lineStart=y1, lineEnd=y2, lastDrawnCoordinate=endy)
        if lastSegmentDrawLength > 0:
            drawSolidVertLine(draw, y2-lastSegmentDrawLength, y2, x, lineWidth, lineWidthExpansion, lineColor)


def drawRectangle(draw: ImageDraw, x1: int, y1: int, x2: int, y2: int, lineWidth: int, dashedLine: DashedLine, lineColor: RGB, fillColor: RGB, fCompleteCorners=True):

    """
    Draws a rectangle, including support for dashed lines

    :param draw: Canvas to draw on
    :param x1: x-coordinate of the top-left corner
    :param y1: y-coordinate of the top-left corner
    :param x2: x-coordinate of the bottom-right corner (inclusive)
    :param y2: y-coordinate of the bottom-right corner (inclusive)
    :param lineWidth: Width of lines
    :param dashedLine: Dashed-line specification, or None for solid line
    :param lineColor: Line color
    :param fillColor: Fill color
    :param fCompleteCorners: Make sure each of the rectangle's 4 corners has segments near them (for dashed lines)
    """

    if fillColor: # fill the rect if specified
        draw.rectangle([(x1+lineWidth, y1+lineWidth), (x2-lineWidth, y2-lineWidth)], outline=fillColor, fill=fillColor)

    if lineWidth > 0: # draw the rect if specified
        # draw top and bottom horizontal lines of rect
        drawHorzLine(draw, x1, x2, y1, lineWidth, LineWidthExpansion.EXPAND_RIGHT_DOWN, dashedLine, lineColor, fCompleteCorners)
        drawHorzLine(draw, x1, x2, y2, lineWidth, LineWidthExpansion.EXPAND_LEFT_UP, dashedLine, lineColor, fCompleteCorners)
        # draw left and right vertical lines of rect
        drawVertLine(draw, y1, y2, x1, lineWidth, LineWidthExpansion.EXPAND_RIGHT_DOWN, dashedLine, lineColor, fCompleteCorners)
        drawVertLine(draw, y1, y2, x2, lineWidth, LineWidthExpansion.EXPAND_LEFT_UP, dashedLine, lineColor, fCompleteCorners)


def drawFrameline(draw: ImageDraw, rawDimensions: Dimensions, jpgDimensions: Dimensions, aspectRatioDimensions: Dimensions, lineWidth: int, dashedLine: DashedLine, lineColor: RGB, fillColor: RGB, labelPos: LabelPos) -> None:

    """
    Draws framelines with the specified aspect ratio that fits within the specified jpg dimensions

    :param draw: Canvas to draw on
    :param rawDimensions: Camera's raw image dimensions
    :param jpgDimensions: Camera's jpg image dimensions
    :param aspectRatioDimensions: Aspect ratio of box
    :param lineWidth: Width of lines
    :param dashedLine: Optional dash/dashed-line specification. If not provided then solid
    :param lineColor: Color of lines
    :param fillColor: Color to fill area with
    :param labelPos: Position of text label for aspect ratio, or None for no label
    lines will be  used.
    """

    def getFontBySizeForPixelHeight(string: str, maxiumHeightWantedInPixels: int) -> Any:

        """
        Returns a font whose size is as close to "maxiumHeightWantedInPixels" as possible without
        going over when rendering the supplied string
        :param string: Text to calucate font size from
        :param maxiumHeightWantedInPixels: Maximum height of font desired, in pixels
        :return: Default font whose size meets criteria
        """

        fontSize = 16384 # abusrdly high value to handle largest fontSizePct possible (100%)
        while fontSize >= 8:
            prevFontSize = fontSize
            defaultFont = ImageFont.load_default(size=fontSize)
            left, top, right, bottom = draw.textbbox((0,0), string, font=defaultFont)
            textHeightPixels = int(bottom-top)
            textWidthPixels = int(right-left)
            if textHeightPixels <= maxiumHeightWantedInPixels:
                break
            multiple  = textHeightPixels // maxiumHeightWantedInPixels
            if multiple >= 2:
                fontSize //= multiple
            else:
                fontSize = int(math.floor(fontSize * .98))
            printD(f"Tried prevFontSize {prevFontSize}, yielded textHeight {textHeightPixels} vs max-wanted {maxiumHeightWantedInPixels} - next fontSize {fontSize}")
        printV(f"Selected fontSize {fontSize}, yielding text height of {textHeightPixels} (max-wanted {maxiumHeightWantedInPixels}), vs rawHeight {rawHeight} ({textHeightPixels/rawHeight*100:.2f}%), args.fontSizePct={Config.args.fontSizePct*100:.2f}%")
        return (textWidthPixels, textHeightPixels, defaultFont)

    rawWidth, rawHeight = rawDimensions
    jpgWidth, jpgHeight = jpgDimensions

    boxWidth, boxHeight = calcAspectRatioDimensions(jpgDimensions, aspectRatioDimensions)

    rawBorderLeft = rawBorderRight = (rawWidth-jpgWidth)//2
    rawBorderTop = rawBorderBottom = (rawHeight-jpgHeight)//2

    # calculate box starting x,y relative to jpg dimensions
    boxTopLeftInJpg_X = (jpgWidth - boxWidth)//2
    boxTopLeftInJpg_Y = (jpgHeight - boxHeight)//2

    # calculate box starting x,y relative to raw dimensions
    x = rawBorderLeft + boxTopLeftInJpg_X
    y = rawBorderTop + boxTopLeftInJpg_Y

    if (lineWidth is None) or (lineColor is None):
        lineWidth = 0

    drawRectangle(draw=draw, x1=x, y1=y, x2=x+boxWidth-1, y2=y+boxHeight-1,
        lineWidth=lineWidth, dashedLine=dashedLine, lineColor=lineColor, fillColor=fillColor, fCompleteCorners=True)

    if labelPos:

        text = f"{aspectRatioDimensions.columns}:{aspectRatioDimensions.rows}"
        textHeightInPixelsWanted = int(rawHeight*Config.args.fontSizePct)
        textWidthPixels, textHeightPixels, font = getFontBySizeForPixelHeight(text, textHeightInPixelsWanted)

        textPosOffset = 20
        match labelPos.horzPos:
            case HorzPos.LEFT:
                textX = x + lineWidth + textPosOffset
            case HorzPos.CENTER:
                textX = x + boxWidth/2 - textWidthPixels/2 - textPosOffset
            case HorzPos.RIGHT:
                textX = x + boxWidth - lineWidth - textWidthPixels - textPosOffset
        match labelPos.vertPos:
            case VertPos.TOP:
                textY = y + lineWidth + textPosOffset
            case VertPos.CENTER:
                textY = y + boxHeight/2 - textHeightPixels/2 - textPosOffset
            case VertPos.BOTTOM:
                textY = y + boxHeight - lineWidth - textHeightPixels - textPosOffset

        draw.text((textX, textY), text, fill=lineColor, font=font, anchor="lt")

    printI(f"Frameline: Aspect ratio \"{aspectRatioDimensions.columns}:{aspectRatioDimensions.rows}\", resolution is {boxWidth}x{boxHeight}")


def drawGridline(draw: ImageDraw, gridDimensions: Dimensions, rawDimensions: Dimensions, jpgDimensions: Dimensions, aspectRatioDimensions: Dimensions, lineWidth: int, dashedLine: DashedLine, lineColor: RGB) -> None:

    """
    Draws gridlines with the specified dimensions

    :param draw: Canvas to draw on
    :param gridDimensions: Dimensions with number of column and row segments.
    :param rawDimensions: Camera's raw image dimensions
    :param jpgDimensions: Camera's jpg image dimensions
    :param aspectRatioDimensions: Aspect ratio to constrain gridlines to, or None to use jpgDImensions as only constraint
    :param lineWidth: Width of lines
    :param dashedLine: Optional dash/dashed-line specification. If not provided then solid lines will be drawn.
    :param lineColor: Color of lines
    :param fillColor: Color to fill area with
    """

    rawWidth, rawHeight = rawDimensions
    jpgWidth, jpgHeight = jpgDimensions

    if aspectRatioDimensions:
        drawWidth, drawHeight = calcAspectRatioDimensions(jpgDimensions, aspectRatioDimensions)
    else:
        drawWidth, drawHeight = jpgDimensions

    rawBorderLeft = rawBorderRight = (rawWidth-jpgWidth)//2
    rawBorderTop = rawBorderBottom = (rawHeight-jpgHeight)//2

    # calculate starting x,y of drawing area relative to raw dimensions
    xOrigin = rawBorderLeft + (jpgWidth - drawWidth)//2
    yOrigin = rawBorderTop + (jpgHeight - drawHeight)//2

    # draw columns (vertical lines)
    if gridDimensions.columns:
        pixelsPerColumn = (drawWidth // gridDimensions.columns) + (drawWidth % gridDimensions.columns != 0)
        for x in range(pixelsPerColumn, drawWidth, pixelsPerColumn):
            drawVertLine(draw=draw, y1=yOrigin, y2=yOrigin+drawHeight, x=x+xOrigin, lineWidth=lineWidth, lineWidthExpansion=LineWidthExpansion.EXPAND_CENTERED, dashedLine=dashedLine, lineColor=lineColor, fCompleteDashedLineEdge=True)

    # draw row (horizontal lines)
    if gridDimensions.rows:
        pixelsPerRow = (drawHeight // gridDimensions.rows) + (drawHeight % gridDimensions.rows != 0)
        for y in range(pixelsPerRow, drawHeight, pixelsPerRow):
            drawHorzLine(draw=draw, x1=xOrigin, x2=xOrigin+drawWidth, y=y+yOrigin, lineWidth=lineWidth, lineWidthExpansion=LineWidthExpansion.EXPAND_CENTERED, dashedLine=dashedLine, lineColor=lineColor, fCompleteDashedLineEdge=True)

    # info print
    if aspectRatioDimensions:
        aspectRatioDesc = f" [inside aspect ratio \"{aspectRatioDimensions.columns}:{aspectRatioDimensions.rows}\"]"
    else:
        aspectRatioDesc =""
    printI(f"Gridline: {gridDimensions.columns}x{gridDimensions.rows}{aspectRatioDesc}, area {drawWidth}x{drawHeight}")


def run() -> bool:

    """
    main module routine

    :return: False if successful, True if error
    """

    Config.args = args = processCmdLine()
    if args is None:
        return True

    printI(f"{AppName} v{AppVersion}")
    printD(f"Args: {args}")

    # get raw and jpg dimensions, either form camera or those manually specified
    if args.camera:
        cameraInfo = cameras.getCamera(args.camera)
        if not cameraInfo:
            printE(f"There is no camera \"{args.camera}\" in the camera database. Use --list-cameras to see supported cameras.")
            return True
        if not args.dimensions:
            rawDimensions = cameraInfo.rawDimensions
            jpgDimensions = cameraInfo.embeddedJpgs[0].dimensions
        else:
            # the dimensions provided on the command-line override the camera dimensions
            rawDimensions = args.rawDimensions
            jpgDimensions = args.jpgDimensions
    else:
        cameraInfo = None
        rawDimensions = args.rawDimensions
        jpgDimensions = args.jpgDimensions

    printI(f"RAW resolution is {rawDimensions.columns}x{rawDimensions.rows}, JPG is {jpgDimensions.columns}x{jpgDimensions.rows}")

    if (rawDimensions.columns < jpgDimensions.columns) or (rawDimensions.rows < jpgDimensions.rows):
        printE("Raw dimensions must be >= jpg dimensions on both axis")
        return True

    # draw framelines
    img = Image.new('RGB', (rawDimensions.columns, rawDimensions.rows), args.backgroundColor)
    draw = ImageDraw.Draw(img)
    for frameline in args.framelines:
        drawFrameline(draw,
            rawDimensions,
            jpgDimensions,
            frameline.aspectRatio,
            lineWidth=frameline.lineWidth,
            dashedLine=frameline.dashedLine,
            lineColor=frameline.lineColor,
            fillColor=frameline.fillColor,
            labelPos=frameline.labelPos)

    # draw gridlines
    for gridline in args.gridlines:
        drawGridline(draw=draw,
            gridDimensions=gridline.gridDimensions,
            rawDimensions=rawDimensions,
            jpgDimensions=jpgDimensions,
            aspectRatioDimensions=gridline.aspectRatio,
            lineWidth=gridline.lineWidth,
            dashedLine=gridline.dashedLine,
            lineColor=gridline.lineColor)

    # Save the generated image
    outputFilename = generateOutputFilename()
    try:
        img.save(outputFilename)
    except Exception as e:
        printE(f"Unable to save output to \"{outputFilename}, error: {e}")
        return True
    printI(f"Successfully generated \"{os.path.realpath(outputFilename)}\"")

    # generate NEF if specified
    if args.generatenef:
        fError = runImg2nef(outputFilename)
        if fError:
            return True

    # open in viewer if specified
    if args.openInViewer:
        openFileInOS(outputFilename) # we ignore any viewer errors since it's not an essential operation

    return False


if __name__ == "__main__":
    fError = run()
    sys.exit(fError)