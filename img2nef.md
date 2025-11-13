# img2nef
Command-line utility that converts any image file into a Nikon NEF losslessly-compressed raw. Includes additional utilities that make use ofutilize img2nef, such as [createoverlay](createoverlay.md)makevf for creating viewfinder overlays with custom aspect ratio framing guides and display grids.

## Requirements
img2nef supports all Nikon cameras that support lossless 14-bit raw compression, which is most models except their entry-level cameras.

img2nef runs on Windows, Mac, and Linux. It requires Python 3.10 or later, which can be [downloaded here](https://www.python.org/downloads/). The following additional Python packages are required:

    pip install opencv-python
    pip install pillow
    pip install numpy

ExifTool is also required ([download link](https://exiftool.org/))  and must be in your system path.

## Installation
Download img2nef by [clicking here](https://github.com/horshack-dpreview/img2nef/archive/refs/heads/main.zip) and unzip into a directory of your choice, or if you have git:

 `git clone https://github.com/horshack-dpreview/img2nef.git`

## Running
Depending on your platform, img2nef can be started in one of the following ways:
* python img2nef.py
* python3 img2nef.py
* imgn2ef.py

## Quick StartBasic parameters
img2nef has many options but there are only two basic parameters are required:
* Nikon Camera Model (or Template NEF)
* Source Image File

### Examples:
`python img2nef.py Z6III sunset.jpg`
Converts the image sunset.jpg into a Nikon Z6 III raw, using the built-in template NEF for the Z6 III.

`python imgn2nef.py IMG_0085.NEF sunset.jpg`
Converts the image `sunset.jpg` into a Nikon raw, using the supplied template NEF. The model for the generated raw will match the model `IMG_0085.NEF` was shot with.

img2nef also supports Numpy (.npy) file sources. See [Numpy Sources](#numpy-sources) for details.

### Template NEFs
You can specify either a camera model or a template NEF.

When you specify a camera model, img2nef will use the template NEF included with img2nef for that model. If no camera model is specified then you must provide your own template NEF.

A template NEF is the source raw file that img2nef uses as the skeleton to generate the new raw file. Here's a summary of the process:

 1. img2nef reads the template NEF into memory,  minus any raw data
 2. img2nef converts your source image into Nikon's proprietary lossless compressed format
 3. img2nef merges the generated raw data into the template NEF that it read into memory
 4. img2nef writes out the new NEF

The template NEF is never modified.

The result is an NEF that's identical to the template NEF but with the raw data replaced. img2nef also replaces the embedded jpgs - embedded jpgs are used by cameras and image viewers as a quicker way to preview the raw data without having to develop it. For example, when you use your Nikon camera's playback feature it displays the embedded jpg rather than actually processing the raw data.

See the [tips for creating template NEFs](#template-nef-tips) for best practices when creating your own template NEFs.

## Automatic output filename
When no output filename was specified img2nef will automatically generate one, which by default is the concatenation of the model/template NEF and source file names. For the first example this will be `Z6III_sunset.NEF`, stored in the same directory as `sunset.jpg`

## More output options
`<output filename>`
You can explicitly specify the output filename by providing a third argument. It can include an optional path as well. If any part of the path or filename has spaces you must enclose the entire text in double quotes. Example:

`img2nef Z6III sunset.jpg "c:\My Documents\sunset.NEF"`

### `--outputdir <path>`
Directory to store the generated NEF into. If this is specified without an `<output filename>` then img2nef will generate the output filename automatically and store it in the `--outputdir` path.

### `--outputfilenamemethod`
Method used to automatically generate the output filename when the `<output filename>` is not specified. Options are:
* `TEMPLATENEF_AND_INPUTFILE` - Combine the camera model / template NEF and input filenames (default)
* `TEMPLATENEF` - Use the template NEF filename
* `INPUTFILE` - Use the input filename (but with a .NEF extension)
* `NONE` - Don't automatically generate an output filename. The output filename must be specified explicitly.

Example:

`img2nef Z6III sunset.jpg --outputdir c:\docs --outputfilenamemethod INPUTFILE`

Converts sunset.jpg, storing result to `c:\docs\sunset.NEF`

### `--ifexists ADDSUFFIX | OVERWRITE | EXIT`

Action to take if the output file already exists. `ADDSUFFIX` iteratively adds a numerical suffix to the filename until a unique name is generated (ex: "file-1.nef", "file-2.nef", etc...). `OVERWRITE` overwrites the existing file. `EXIT` terminates the app without writing the output. Default is `ADDSUFFIX`.

### `--openinviewer yes | no`

Open the generated NEF in your computer's default image editor when complete. Default is no. If a yes/no value is not specified then the option is interpreted as `yes`.

## Image Processing Options
### Resizing
While img2nef supports several automatic resizing options of your source image, for best results I recommend that you resize your source image to the raw dimensions of your camera model prior to running img2nef. Note that each models' true raw dimensions are slightly larger than the advertised dimensions you typically see in your raw processing software like Photoshop and Lightroom, which typically match the camera's jpg dimensions instead. You can get the true raw dimensions for all Nikon Z cameras by running the following command:

`python cameras.py`

Here are the true raw sizes for all current Nikon Z models, along with the processed raw (jpg) equivalents:

| Model   | Raw Size | JPG Size  |
| ------- | -------- |---------- |
|Z30 | Not Supported | Not Supported |
|Z50 | Not Supported | Not Supported |
|Zfc | Not Supported | Not Supported |
|Z5 | 6040x4032 | 6016x4016 |
|Z5 II | 6064x4040 | 6048x4032 |
| Z50 II | 5600x3728 | 5568x3712 |
| Z6 | 6064x4040 | 6048x4024 |
| Z6 II | 6064x4040 | 6048x4024 |
| Z6 III | 6064x4040 | 6048x4032 |
| Z7 | 8288x5520 | 8256x5504 |
| Z7 II | 8288x5520 | 8256x5504 |
| Z8 | 8280x5520 | 8256x5504 |
| Z9 | 8280x5520 | 8256x5504 |
| Zf | 6064x4040 | 6048x4032 |
| ZR | ?x? | ?x? |

### Resizing Options
All resizing options have a "re." prefix

### `--.re.geometry FULL | MINIMUM | NONE`
This option controls how the source image is resized relative to the raw dimensions. The options are `FULL`, `MINIMUM`, and `NONE`.

The default `FULL` resizes the source to the full raw dimensions, which means both axis. This typically involves resizing larger than the raw dimensions since by default the aspect ratio is maintained, and then cropping down as necessary. For example, a 1000x1000 1:1 source image for a 6000x4000 3:2 raw will be resized to 6000x6000, then cropped to 6000x4000 to meet the raw's 3:2 aspect ratio.

`MINIMUM` resizes the source image only to its nearest axis (in size) to meet a raw axis, with the other raw output axis potentially padded with a border. For example, a 1000x1000 1:1 source image for a 6000x4000 3:2 raw will be resized to 4000x4000 (raw's "row" axis is closest in size to source image), with 1000 pixels of border on both horizontal sides of the raw image to fill out the raw's 6000 horizontal pixels.

`NONE` does no resizing. Source images smaller than the raw dimensions will be positioned in the raw frame according to the `--re.horzalign` and `--re.vertalign` options (default is centered), with a border around them to fill out the raw dimensions.

### `--re.maintainaspectratio yes | no`
Maintain aspect ratio of source. When `--re.maintainaspectratio=NO`, `--re.geometry` isn't applicable since the aspect ratio constraints it addresses don't exist when the source image aspect ratio doesn't need to be maintained. For example, a 1000x1000 1:1 source image can be resized directly to a 6000x4000 3:2 raw output without needing to oversize it to 6000x600 first. Default is yes. If a yes/no value is not specified then the option is interpreted as `yes`.

### `--re.horzalign CENTER|LEFT|RIGHT`
Horizontal alignment of source image position or crop. Options are `CENTER`, `LEFT`, and `RIGHT` For example, if resizing is disabled via `--re.geometry=NONE` and `--re.horzalign=CENTER`, a source image of 2000x2000 for a 6000x4000 raw will have 1500 padding pixels on both horizontal sides, with source image centered in frame. Default is `CENTER`.

### `--re.vertalign CENTER|TOP|BOTTOM`
Vertical alignment of source image position or crop. Options are `CENTER`, `TOP`, and `BOTTOM`. Default is CENTER.

### `--re.borderfillcolor #RRGGBB (hex)`
Border color when source image doesn't fill out raw frame for resize parameters used. Default is #000000 (black).

### `--re.resizealgo LANCZOS4 | CUBIC | AREA | LINEAR | NEAREST`
Pixel-level algorithm to use wIf you specify a camera model then img2nef will use one of the template NEFs that's included with img2nef, otherwise it will use the template NEF you supply. A template NEF is the skeleton raw file that img2nef uses to generate its output - it reads the template NEF (minus the raw data), converts your source image into Nikon's proprietary lossless compressed format, then creates a new NEF from the template, merging in the converted data.

Then resizing. Default is `LANCZOS4`.

### Image Processing
These options control how the source image is processed and converted into bayered raw data. Note these options don't apply when the image source is a Numpy (.npy) file. All source image processing options have a "src." prefix

### `--src.wbmultipliers Red Value, Green Value`

Image sensors have uneven sensitivity to color across the light frequency spectrum, with less sensitivity to blue and red light vs green light. To account for this, raw files include white balance multipliers in their metadata that specify how the red and blue pixel values should be multiplied to match the intensity of green pixels. Raw image processors like Photoshop apply these multipliers when rendering the raw data to an image with a given white balance.

Since img2nef goes in the opposite direction, ie from a rendered image back to raw data, it has to apply the inverse of these multipliers, to simulate the lower sensitivity of the red and blue pixels. Normally img2nef uses the WB multipliers in the template NEF, which were shot with a "sunny" WB to handle normal white-balanced source images. The `--src..wbmultipliers` lets you specify a different set of WB multipliers to inversely apply. All values are in floating-point. Example:

`--src.wbmultipliers=1.3568,1.72325`
Applies a 1/3.3568 multiplier to the red pixels and 1/1.72325 multiplier to the blue pixels.

### `--src.hsl H,S,L`
Applies the specified Hue, Saturation, and Lightness adjustment to source data during conversion to raw. Each value is a normalized floating-value between 0.0 and 1.0. By default img2nef applies `--src.hsl 1.0,0.5,1.0`, which reduces the saturation by 50%. This is done to handle a base level of over saturation when converting back to raw, and to account for img2nef's current lack of support for 3x3 raw color matrix handling for more accurate raw color reproduction (I'm researching any copyright implications of using the available color matrices available, including from commercial sources).

For certain computer-generated images you'll probably want to override img2nef's default desaturation HSL. For example, `createoverlay.py` passes `--src.hsl 1.0,1.0,1.0` to img2nef when converting a viewfinder overlay to raw.

### `--src.srgbtolinear yes | no`
Assume source is encoded in sRGB and convert to linear RGB during the raw conversion. Default is yes. If a yes/no value is not specified then the option is interpreted as `yes`.

### `--src.grayscale yes | no`
Convert source image to grayscale. Default is no. If a yes/no value is not specified then the option is interpreted as `yes`.

## Numpy Sources
In additional to normal RGB image sources img2nef also supports Numpy array files as source. These have the extension .npy and are created via the numpy.save() method. Img2nef supports the following Numpy array configurations:

Pixel Rows x Pixel Columns x Bayer color channels (4)
In this 3D array configuration, each bayer color channel dimension contains a 2D matrix of pixel values for that color. The color channels are arranged as RGGB.

Bayered Row X Bayered Columns
In this 2D array configuration, the pixel values are bayered in the same arrangement as on the sensor, with pixel values for the first row alternating between Red and Green_1 values and values for the second row alternating between Green_2 and Blue values. This repeats in pairs of rows.

None of img2nef's image processing options are available for Numpy arrays except for the simple cropping/padding resizing options, so all your image processing steps must be performed prior to exporting your Numpy array supplied to img2nef. The data type should be uint16, with all values normalized to 14-bit raw linear values. For proper rendering of the generated NEF, all pixel values should include any black-level bias associated with the template NEF, unless of course you want to intentionally leave them out for experimental / image research purposes.

### `--embeddedimg <image filename>`
Because there is no RGB image available for Numpy sources you must supply a separate RGB image to serve as the source for the embedded jpgs. Use the `--embeddedimg` option for this. The RGB image should be equal in size to the largest embedded jpgs of the raw, ie the embedded jpg tagged as "JpgFromRaw", which is typically equal to the native full-sized jpg for raw images processed on the camera. img2nef will resize this image appropriately for each of the other embedded jpgs present in the template NEF.

For best quality use 4:2:2 chroma subsampling for the supplied embedded image, as 4:2:2 is the native format supported by Nikon cameras.

Note that `--embeddedimg` can be used with non-Numpy image sources as well. Use this when you want to use your own embedded image rather than an embedded image based on the source image that's converted to raw data.

## Specifying options in separate file, including default options
In addition to supplying options on the command line, you can also place additional options in a text file and supply its filename by placing a `!` before it. For example:

`img2nef !myoptions.txt --src.grayscale`

In the text file each option must be on a separate line, and any values for the option must be connected via an equal sign instead of space, otherwise the value will be interpreted as a different option. Example `myoptions.txt`
```
--src.srgbtolinear
--re.horzalign=CENTER
```
Besides your own option text files, createoverlay will always load any option text file named `.img2nef-defaultoptions` in its directory. The options in this file will be loaded and applied before any of the options you specify, allowing you to create your own application defaults.

## Troubleshooting Options
These options help debug issues.

### `--showperfstats yes | no`
Show performance statistics. Implicitly enabled when `--verbosity` is >= `VERBOSE`. Default is no. If a yes/no value is not specified then the option is interpreted as `yes`.

### `--verbosity SILENT | WARNING | INFO | VERBOSE | DEBUG`
Verbosity of output during execution. Default is `INFO`. When `SILENT`, only error messages are displayed.

## Template NEF Tips
There are instances where it may be useful to supply your own template NEFs instead of using the template NEFs included with img2nef. The only hard requirement for template NEFs is that they be shot using your model's 14-bit Lossless Compression option. Note that newer Z models only shoot 14-bit for raw so you'll only need to assure you've selected the lossless option.

Here are some additional recommendations on getting the best results when shooting your template NEFs:

### Shoot at base ISO, daylight WB, neutral picture profile, Active D-Lighting disabled
Because you'll likely be developing your generated raws in either raw-processing software or with in-camera features like retouching or multiple exposure, you'll want to use a neutral set of settings for your template NEF. This is because the generated NEF inherits all its settings from the template NEF. For example, shooting at base ISO assures a minimal amount of noise reduction, since your generated NEF's likely have no noise due to how you generated them (for example, AI-generated images). Same for white balance, picture profiles, etc...

### Shoot a highly-detailed scene with good exposure
Since img2nef doesn't use the raw image data from template NEFs, the content of the scene you shoot doesn't directly matter. However, img2nef does have sensitivity to scene content for a different reason - embedded jpgs. For maximum compatibility, img2nef replaces the embedded jpgs of the template NEF when generating the output NEF by overwriting them the jpgs "in-place", meaning it doesn't try to rearrange the EXIF sections. This means the embedded jpgs in your template NEF need to be large enough to accommodate the embedded jpgs img2nef creates from your source image, otherwise img2nef is forced to increase the jpg compression level to make sure the embedded jpg fits. In the worst case scenario, img2nef will be unable to fit the embedded jpg(s) even when using maximum compression, meaning the generated NEF will have the original template embedded jpg.

To prevent this, shoot your template NEF with a scene with lots of detail and well-exposed. This will create the maximum embedded jpg size possible, leaving enough room for the high-quality embedded jpgs img2nef will create. The template NEFs I included img2nef were shot using a noise pattern displayed on a computer monitor - you can download that image [here](https://photos.smugmug.com/photos/i-Lv7XTmQ/0/MPXGZcjMCj3DKHrnsR4nHPRMMm53PXSb8dLKXvfL3/O/i-Lv7XTmQ.png).

### Shoot with lens electrically disconnected
Nikon Z cameras embed lens correction profiles into raw files. These profiles are automatically applied by both raw image processors like Photoshop and by the camera itself (in-camera multiple exposure and retouching features). These profiles are intended to correct geometric distortions from the projection of the lens, along with various aberrations and vignetting.

The source images you supply to img2nef for conversion usually don't need any lens corrections because they've either been generated entirely on the computer without a lens or were processed from an image shot with a camera where lens corrections have already been applied. If a lens correction profile is subsequently applied to this source image it will induce distortions rather than correct them. For example, if a profile correcting lens barrel distortion is applied it will result in an image with pincushion distortion, the opposite of barrel distortion. This is because it will be convolving against an image that already has straight lines, resulting in those lines turning inward as pincushion distortion.

To avoid this I highly recommend that you shoot your template NEFs with the lens electrically disconnected. This will prevent the camera from identifying the lens and thus from embedding a correction profile. During development I experiment with modifying the EXIF of the template NEF to remove the lens identification information and correction profiles to accomplish this but found the camera uses undocumented fields of the EXIF to find and apply corrections, so until those fields can be reversed-engineered it's best to shoot with the lens electrically disconnected.

To accomplish this, press on the camera's lens release button and slightly turn the lens just enough so that the electrical connection is lost. You can tell when this occurs when the f/stop display changes to "F--". Be careful to not allow the lens to fall off the mount when doing this - I suggest holding onto the lens barrel after turning it while taking the template NEF exposure.

Be careful not to nudge the focus ring when disconnecting the lens - that way the focus you acquired on your highly-detailed subject (recommended above) will be maintained when you take the exposure.

If you're not comfortable with this procedure then the next-best option is to shoot with a lens that has no electrical contacts. Note that even adapted lens including from third-party mounts and adapters can embed correction profiles so you'll want an adapter or lens that has no electrical contacts to the body.

The next best option is to shoot with a lens that has very little optical distortion / aberrations / vignetting, so that any correction profile applied to your converted source images will be minimal.

## Technical details
### C-optimized NEF encoder
img2nef is written primarily in Python, with the NEF encoder logic written in C for performance. A pre-compiled version of the encoder is included in the Windows, Mac, and Linux directories, each of which is automatically loaded based on the detected platform. Before loading the platform-specific library img2nef will first check for the library in its base directory - this allows you to compile/use the NEF encoding module for non-standard platforms as well. The encoder module should compile without modification on any platform - it's coded to work with various native integer sizes and on both small and big endian configurations. You can compile the module via the following gcc invocation:

`gcc -shared -O2 -o nefencode.so nefencode.c -fPIC`ult is an NEF that's identical to the template NEF but with the raw data and embedded jpgs replaced (embedded jpgs are used by image viewers to preview the raw data without having to develop it first, including the in-camera playback functionality). The template NEF is never modified.
