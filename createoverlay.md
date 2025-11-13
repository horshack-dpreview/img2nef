# createoverlay
Command-line utility for creating viewfinder overlays with custom aspect ratio framelines and grid lines, which can then be converted into Nikon NEF raw files and used with Nikon's multiple exposure overlay feature for shooting with Nikon Z cameras - see the  [Using overlays with Nikon's multiple exposure feature](#using-overlays-with-nikon-multiple-exposure-feature) for details.

## Requirements
createoverlay is part of [img2nef](img2nef.md) and runs on Windows, Mac, and Linux. It requires Python 3.10 or later, which can be [downloaded here](https://www.python.org/downloads/). The following additional Python packages are required:

    pip install pillow

createoverlay is part of the img2nef project, which is required to convert the generated overlay into a Nikon NEF raw.

## Installation
Download img2nef by [clicking here](https://github.com/horshack-dpreview/img2nef/archive/refs/heads/main.zip) and unzip into a directory of your choice, or if you have git:

 `git clone https://github.com/horshack-dpreview/img2nef.git`

## Running
Depending on your platform, createoverlay can be started in one of the following ways:
* python createoverlay.py
* python3 createoverlay.py
* createoverlay.py

## Quick Start
createoverlay has many options but only two parameters are typically required:
* Nikon Camera Model
* At least one frameline or gridline specification

### Examples:
`python createoverlay.py Z6III --frameline 16:9`  
Creates a 16:9 frameline with default line and fill characteristics for a Nikon Z6 III as a PNG file, then converts the PNG to a NIkon Z6 III NEF raw. The resulting PNG is opened in your system's default image viewer.

![Sample 16:9 frameline](https://photos.smugmug.com/photos/i-6J6gFbr/0/KNRxzW5D5R4MGQsbtCfb6HtQJxd4q3TDtC5kv8TDd/S/i-6J6gFbr-S.png)

`python createoverlay.py Z6III --gridline 4x4`  
Creates a 4x4 gridline with default line and fill characteristics for a Nikon Z6 III.
<br clear="all">
![Sample 4x4 Gridline](https://photos.smugmug.com/photos/i-CjBJhH3/0/KTr95dS96C2QR3RHrT5wLH8spZDzfd3MVz2tFLd8d/S/i-CjBJhH3-S.png)

`python createoverlay.py Z6III --frameline 16:9 --frameline 1:1,dashedline=50-50,linecolor=#ff0000`  
Creates a 16:9 solid-line white frameline and a 1:1 dashed red frameline.
<br clear="all">
![Sample 16:9 and 1:1 framelines](https://photos.smugmug.com/photos/i-jbH2CpP/0/LHjtkJDbB3ZzpHjWtcPJhTKg9MwfkRMQQHxg5KwMM/S/i-jbH2CpP-S.png)

## Automatic output filename
When no output filename is specified createoverlay will automatically generate one, which by default is the concatenation of the camera model and each of the frameline and gridlines you specified, stored in the current working directory. For the first example this will be `Overlay_Z6III_Frame-16x9.PNG` and the second `Overlay_Z6III_Grid-4x4.PNG`.

## More output options
`<output filename>`  
You can explicitly specify the output filename by providing an additional argument. It can include an optional path as well. If any part of the path or filename has spaces you must enclose the entire text in double quotes. Example:

`createoverlay Z6III --frameline 16:9 "c:\My Documents\MyGrid.PNG"`  

### `--outputdir <path>`
Directory to store the generated overlay into. If this is specified without an `<output filename>` then createoverlay will generate the output filename automatically and store it in the `--outputdir` path.

### `--ifexists ADDSUFFIX | OVERWRITE | EXIT`

Action to take if the output file already exists. `ADDSUFFIX` iteratively adds a numerical suffix to the filename until a unique name is generated (ex: "file-1.nef", "file-2.nef", etc...). `OVERWRITE` overwrites the existing file. `EXIT` terminates the app without writing the output. Default is `ADDSUFFIX`.

## All options

### `--frameline aspectratio=columns:rows, linewidth=#pixels, dashedline=dashlen-gaplen, linecolor=#RRGGBB, fillcolor=#RRGGBB, labelpos=vert-horz`

Each frameline parameter is separated with commas, with no spaces allowed - a space will be interpreted as the next command-line option.

`aspectratio` is the relationship of width vs height for the frameline. This parameter is required. All other parameters are optional.

`linewidth` is the width of the line drawn for the frameline, in pixels. Default is 32.

`dashedline` sets a repeating dashed pattern for the line. The first value is the length of the drawn segment, the second is the length of the gap between segments. Specify 'none' or no value for a solid line. Default is none (solid line).

`linecolor` sets the color of the line, specified in three 2-digit RGB hex values. Default is #000000 (black).

`fillcolor` sets the interior color of the aspect ratio box, specified in three 2-digit RGB hex values.  Default is none (no fill), which means the global `--backgroundcolor` setting will determine the interior color of the aspect ratio area. You can experiment with different fill colors/brightnesses vs the various compositing modes supporting by Nikon's multiple exposure feature to visually isolate the aspect ratio area to your preference.

`labelpos` sets the label position and visibility of the aspect ratio label. Values for `vertpos` are `Top, Center, Bottom` and for `horzpos` are `Left, Center, Right`. For no label specify `none` or no value. Default is Bottom-Left.

The `aspectratio` parameter is required - all others are optional. Any parameter not specified will use the default for that setting, which can be set separately via that option name outside of a `--frameline`. For example:

`--frameline 4:3 --frameline 16:9,linecolor=#ff0000 --linecolor=#0000ff`  
Creates a 4:3 frameline using all default values; the default `linecolor` was specified as blue, so the 4:3 frameline will be blue. A 16:9 frameline is also created with a line color of red since that color was specified for that frameline. 

You can optionally leave out the parameter name and just provide the values instead. Use an empty field to skip a value. For example:

`--frameline 1:1,16,5-10,,,center-left`  
Creates a 1:1 frameline with a line width of 16 pixels, dash pattern of 5 pixels with 10 pixel gaps, default line and fill colors (empty fields), and an aspect ratio label position vertically centered on the left side of the frame.

### `--gridline griddimensions=columns x rows, aspectratio=columns:rows, linewidth=#pixels,dashedline=dashlen-gaplen, linecolor=#RRGGBB`

Each gridline parameter is separated with commas, with no spaces allowed - a space will be interpreted as the next command-line option.

Multiple `--gridline` options can be specified, although note they'll typically overlap each other visually.

`griddimensions`sets the dimensions of the grid, as number of columns and rows. One of the axis can be zero if desired, creating only rows or columns.

Each column/row is demarcated by vertical and horizontal lines, so the number of lines will be  the column/row values minus 1. For example, here is a `--gridline 4x4`
<br clear="all">
![4x4 Gridline with 3 lines on each axis](https://photos.smugmug.com/photos/i-CjBJhH3/0/KTr95dS96C2QR3RHrT5wLH8spZDzfd3MVz2tFLd8d/S/i-CjBJhH3-S.png)
<br clear="all">
Note there are three horizontal and vertical lines, creating 4 columns and 4 rows.

`aspectratio` optionally confines the grid to an aspect ratio. The full 3:2 sensor area is used for the grid when `aspectratio` is not specified.

`linewidth` is the width of the line drawn for the frameline, in pixels. Default is 32.

`dashedline` sets a repeating dashed pattern for the line. The first value is the length of the drawn segment, the second is the length of the gap between segments. Specify 'none' or no value for a solid line. Default is none (solid line).

`linecolor` sets the color of the line, specified in three 2-digit RGB hex values. Default is #000000 (black).

You can optionally leave out the parameter name and just provide the values instead. Use an empty field to skip a value. For example:

`--gridline 4x4,,16,,#ff0000`  
Creates a 4:4 grid with default aspect ratio (3:2),  a line width of 16 pixels, no dash pattern (solid line by default), and line color of red.

### `--linewidth #pixels`
Sets the default line width, used when not explicitly specified in a `--frameline` and `--gridline` specification. Default is 32.

### `-linecolor #RRGGBB`
Sets the default line color, used when not explicitly specified in a `--frameline` and `--gridline` specification. Default is #000000 (black).

### `-dashedline dashlen-gaplen`
Sets the default line type, used when not explicitly specified in a `--frameline` and `--gridline` specification. The first value is the length of the drawn segment, the second is the length of the gap between segments. Specify 'none' or no value for a solid line. Default is none (solid line).

### `--labelpos vertpos-horzpos`
Sets the default label position and visibility, used when not explicitly specified in a `--frameline` Values for `vertpos` are `Top, Center, Bottom` and for `horzpos` are `Left, Center, Right`. For no label specify `none` Default is bottom-left.

### `--backgroundcolor #RRGGBB`
Sets the "global" background color of the entire overlay. This color will be visible for any portion of the frame not covered by a frameline box as well as any frameline box with no fill color. Default is #000000 (black).

### `--fontsizepct font-size-pct`
Sets the size of the aspect ratio label as a percentage of the raw picture height. Default is 5%. Note the font size cannot be set on a per-frameline basis (ie, applies to all framelines that enable a label).

### `--dimensions raw columns x rows, jpg columns x rows`
Normally the raw and jpg dimensions are established by the camera model specified. You can override those dimensions with this option, or provide them when no model is specified. Example:

`--dimensions 6048x4032,6000x4000`  

### `--imagetype extension`
Determines the image format of the generated overlay, specified via the file extension of the format. Default is PNG.

### `--openinviewer yes | no`
Open the generated overlay in your system's default image viewer. Default is yes. If a yes/no value is not specified then the option is interpreted as `yes`.

### `--generatenef yes | no`
Use img2nef to generate a Nikon raw NEF from the overlay created. The NEF location and filename will be the same as the generated overlay image but with a .NEF extension. If set to no then only the overlay image will be created and no NEF. Default is yes. If a yes/no value is not specified then the option is interpreted as `yes`.

### `--list-cameras`
Show list of predefined camera models and their raw+jpg resolutions. Same as running `python cameras.py`.

### `--verbosity SILENT | WARNING | INFO | VERBOSE | DEBUG`
Verbosity of output during execution. Default is `INFO`. When `SILENT`, only error messages are displayed.

## Specifying options in separate file, including default options
In addition to supplying options on the command line, you can also place additional options in a text file and supply its filename by placing a `!` before it. For example:

`createoverlay !myoptions.txt --generatenef no`  

In the text file each option must be on a separate line, and any values for the option must be connected via an equal sign instead of space, otherwise the value will be interpreted as a different option. Example `myoptions.txt`
```
--openinviewer=no
--fontsizepct=15% 
```
Besides your own option text files, createoverlay will always load any option text file named `.createoverlay-defaultoptions` in its directory. The options in this file will be loaded and applied before any of the options you specify, allowing you to create your own application defaults.

## Using Overlays with Nikon Multiple Exposure Feature
Once you've created your viewfinder overlay (including its conversion to raw) you can use it with Nikon's in-camera Multiple Exposure feature. This feature allows you to combine multiple exposures into a single composite jpg, including optionally saving each individual raw taken in the process. It also provides an option to supply an existing raw file as the first image in the composite, and includes the ability to view that raw file as an overlay while shooting. With this ability you can use the overlays created by `createoverlay` as framing guides during shoot.

### Copying overlay raws to the media card
Normally the camera only allows you to specify raw images taken by the camera itself, since the camera's feature wasn't designed with the possibility that users could supply their own raws. Specifically, the camera will only let you choose a raw image that it believes it created and put on the card. The camera knows which files it has shot via the `NC_FILLST.DAT` file it manages in each image directory. To get the camera to "see" our overlay files we must replace an existing raw image with the overlay file, using that existing raw's filename. That way the camera will believe it shot the overlay and allow you to select it. This means you'll need to take a throwaway raw photo so that you'll have an image to replace (ie, one you don't mind deleting).

Here's the procedure:

 1. Take a throw-away raw photo with the camera, or multiple photos if you're planning to use multiple overlays.
 2. Mount the media card in a card reader on your computer and navigate to the DCIM directory containing the raw images you just shot.
 3. Copy the overlay raws you created from the computer to the DCIM directory on the card.
 4. Identify the file on the card associated with the "throwaway" photo you took with the camera. For example, `DSC_0169.NEF`. Copy that filename to the clipboard if possible, then delete the file.
 5. Select the overlay raw on the card and rename it to whatever the throwaway's filename was. For example, renaming `Overlay_Z6III_Frame-16x9.NEF` to `DSC_0169.NEF`. The easiest way to rename the overlay is using your Operating System's context menu on the throwaway file and choosing "rename", then pasting the filename you copied from step 4. Be careful the renamed file has only one extension (.NEF), as some renaming options only select the root filename and so pasting the full filename might result in two .NEF extensions.
 6. Repeat steps 4 and 5 for each throwaway file that you're replacing with an overlay.
 7. Safely dismount the media card and insert it back into the camera.

### Configuring the Multiple Exposure feature

1. Go to the PHOTO SHOOTING MENU and enter the Muliple exposure option.

![PHOTO SHOOTING MENU](https://photos.smugmug.com/photos/i-BKsDdxK/0/MVzJWzKTmd8XS9vdNQNqBCLnr64pt4Gcc8fh8ncZ8/S/i-BKsDdxK-S.png)

3. Set the multiple exposure options to:
* Multiple exposure mode to "On (series)",
* Number of shots to 2
* Overlay mode to Ligthen (you can experiment with different modes to preference)
* Save individual pictures (RAW) to "ON"
* Overlay shooting to "ON"

![Multiple Exposure menu options](https://photos.smugmug.com/photos/i-5c8Gvg7/0/LwRhvQJGv2MKpB6rJzDnT7k5jv8wkWx5mfcbT3Kf6/S/i-5c8Gvg7-S.png)

4. Use `Select first exposure (RAW)` and navigate to the overlay raw you'd like to use.

![Selecting overlay as first exposure](https://photos.smugmug.com/photos/i-7K6VzPK/0/KkGhp93nQbHd9Wc8JCLrDFrXGfHn3FLDs9r9MBh3G/S/i-7K6VzPK-S.png)

5. Half-press the shutter to return to shooting mode. 

### Shooting with the Multiple Exposure feature

The camera previews the multiple exposure by compositing the overlay raw you selected over the active scene.
![Viewfinder display with overlay](https://photos.smugmug.com/photos/i-D8cfxWs/0/KmRKm3g3HhVdfZRGH7c2wQR74kcK5KF3bcXxZVfzk/S/i-D8cfxWs-S.jpg)

When you take a picture the camera stores two images on the card - a composite jpg that combines content from the overlay raw with the scene content, using whichever composting mode you selected, and a raw imge, which has only the scene content that is no different than if it were shot outside of the multiple exposure mode.

Note that the composite jpg will not look the same as the previewed composite that was presented while shooting - apparently the camera applies a different compositing algorithm for its Live View preview than it does for the resulting composite photo.

After shooting the multiple exposure photo the camera unfortunately resets the configuration you set for the first raw, which means if you start another multiple exposure sequence it will not automatically use the overlay raw you configured. You'll either need to dive back into the multiple exposure menu to configure the overlay again or preferably, use the following procedure to create a shortcut which does this.

Note: You'll probably want to turn off the camera's [Image Frame option](https://onlinemanual.nikonimglib.com/z6III/en/csmd_image_frame_251.html) - this option draws a white border around the frame that can visually clashes with the overlay.

### Configuring and using shortcut for setting the overlay raw

After every multiple exposure photo the camera resets the configured overlay raw, requiring you to set it again to use for the next photo. I've developed the following shortcut that helps workaround this limitation, or at least reduce it to a set of fixed camera control inputs that you can memorize and use without having to look at the menu system.

1. Add Multiple exposure to the top of your MY MENU by going to `MY MENU` -> `Add items` -> `PHOTO SHOOTING MENU` -> `Multiple exposure` and choosing the first position in your MY MENU. You can also use `Rank items` to reposition `Multiple exposure` to the top of the menu.
![Multiple exposure at the top of MY MENU](https://photos.smugmug.com/photos/i-vSt2TwF/0/NNrMM7VXwJXdGGjsppVvbznh5ds7DNrPFrpCmzhP6/S/i-vSt2TwF-S.png)

2. Configure a function control to `Access top item in MY MENU` by going to `CUSTOM SETTINGS MENU` -> `Controls` -> `Custom controls (shooting)` and selecting a control to assign

![Selecting a custom controls](https://photos.smugmug.com/photos/i-3ZGvtQK/0/NdRf4NXkfNxPdnFNmtLdTnnPQgTVNBKC6tcT2CFRP/S/i-3ZGvtQK-S.png)

Select the desired control and assign it to `Access top item in MY MENU`.

![Assigning control to top of MY MENU](https://photos.smugmug.com/photos/i-LPLzt45/0/KHRxZcWCnTmQL3nG36p3257S6pZNbbRhsM5VB9pfJ/S/i-LPLzt45-S.png)

3. Ideally you want your overlay raw to be the first file on the media card. This is because the camera always defaults to the most recent raw when you're prompted to `Select first exposure (RAW)`. By having the overlay as the oldest raw, you can always select it via a single right-button click on the multi-control dial because that will wrap the selection around from the newest to oldest image.

The easiest way to make the overlay the oldest raw on the camera is to format the card in-camera, take a throwaway picture with the camera (raw), then replace the throwaway raw with your overlay raw, ie rename the overlay raw to the throwaway raw.

#### Using the shortcut
With all that setup out of the way, the procedure to re-select your overlay raw for every photo is:

1. Press the Fn button you assigned to `Access top item in MY MENU` to open the Multiple exposure menu with the last sub-menu item used selected, which will be `Select first exposure (RAW)`.
2. Press the right-button on the rear multi-selector to enter `Select first exposure (RAW)` image selection.
3. Press the right-button on the rear multi-selector to moves selection from newest to oldest raw.
4. Press the center button on the rear multi-selector to accept the oldest raw selection.
5. Half-press the shutter to re-enter shooting mode.

![Shortcut sequence to re-select oldest overlay raw for multiple exposure](https://photos.smugmug.com/photos/i-fT3qQvr/0/MtLwCqWkzhHHgDPSnvHDftMxKxDbRQhB6sr4XxXsF/O/i-fT3qQvr.png)

Obviously these are more clicks than ideal but the sequence is easy commit to muscle memory and perform without having to actually look at the menus while you perform them.