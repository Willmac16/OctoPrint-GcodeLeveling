# OctoPrint-GcodeLeveling

This plugin creates a model of the work surface (using the least squares method on user provided points), allowing for leveling of machines through gcode that otherwise cannot be leveled (e.g. for a grbl machine). A user just needs to measure some z values at a variety of x and y values (e.g. with the paper test), then configure a couple of settings, and the plugin will handle the leveling on file upload.

This plugin really only makes sense it you have no other way of leveling out stuff (i.e. your firmware doesn't offer that feature or you are working on a warped material).

## Gcode Support

* This plugin should be fine with most gcode since it only changes movement commands; however, for movement commands and commands that change how movement commands function (e.g. changes in relative/absolute movement) support needs to be added to the plugin.

### Supported Commands
+ `G0`
+ `G1`
+ `G2`/`G3`
    - See the note on `G17-19`
+ `M82`/`M83`

### Monitored Commands
+  `G90` `G91`
    - the plugin will not change any values in relative positioning mode
+ `G17` `G18` `G19`
    - the plugin only modifies arcs in XY workspace mode
+ `G92`
    - extruder position resets will be respected, any other position resets will stop the plugin from changing any future values on a file

## Setup

Install via the bundled [Plugin Manager](https://docs.octoprint.org/en/master/bundledplugins/pluginmanager.html)
or manually using this URL:

    https://github.com/willmac16/OctoPrint-GcodeLeveling/archive/master.zip

+ The plugin depends on numpy, so it will need to install this (if it is not already installed), which can take some time on a raspberry pi.
    - Numpy in a python3 environment requires libatlas3-base, so some instances may need to run ```sudo apt install libatlas3-base``` to install properly.

## Configuration

+ The Surface Complexity settings determine how many curves you can have in each direction.
    - For example:
        * A degree of 0 will just be a flat constant height.
        * A degree of 1 will fit any four corner points.
        * A degree of 2 will curve down and up in all directions.
    - Aim to measure a grid with one more point in each direction than the Surface Complexity number
        * 2x2 grid for Model complexity (1, 1)
        * 3x3 grid for Model complexity (2, 2)
    - If you are just worried about a bit of sag on an axis then something like a degree of 2 would make sense. If you use too large of a degree, like 10 in each direction with only 5 points, then the model of the surface will really closely match at your entered points, but it will be so curvy that it will be useless between the points.
        * Start with a smaller degree (e.g. 1 with 4 points or 2)
        * Adjust existing points if you are having issues at the places you measured
        * or consider increasing the degree by 1
        * Add points between existing values if you are having issues in that area

+ The minimum and maximum z values are safeguards against bad combinations of gcode and configuration that would spit out positions outside of machines range.
    - If the plugin detects that a movement would fall outside this range, then the file upload will display an error and you should consider changing the configuration.
    - You can check the octoprint.log to see where the issue happened (v0.3.0+)

+ The invert setting is not needed by most normal configurations, and should be left disabled.
    - In my specific setup, I have a G0 Z0 sent to the printer place my toolhead as high as it can go, and a G0 Z71 takes the toolhead right to the surface. With this setting enabled, I can have the gcode files I upload to OctoPrint say that a Z of 0 is right on the surface and a z of 10 is 10 mm above it.

+ The unmodified original option creates a copy of the uploaded file with `_NO-GCL` on the end of its name, that this plugin will not modify.

+ The segment length option breaks up long moves into shorter ones that follow the height model at each of the endpoints.
    - Set the distance to 0.0 to disable this feature; otherwise, all moves longer than the specified length will be analyzed to find the best set of subdivisions.

+ The arc segment length option breaks up arcs into arcs that follow the height model at the endpoints.
    - Set the distance to 0.0 to disable this feature; otherwise, all arcs longer than the specified length will be analyzed to find the best set of subdivisions.

+ The calibration points are used to create a model of the surface.
    - Enter the x and y coordinate, then the measured z coordinate.

### Auto Probing (0.4.0)
+ Probing automatically probes a grid for the surface points.
    - Probe Regex is used to properly convert whatever your firmware converts into points this plugin can use.
        * For example: if your marlin firmware returns `ok X:200.0 Y:40.0 Z:10.0 E:0.0 Count: A:20000 B:4000 C:1000`
        * Marlin: `^ok X:(?P<x>[0-9]+\.[0-9]+) Y:(?P<y>[0-9]+\.[0-9]+) Z:(?P<z>[0-9]+\.[0-9]+)` would return the 3 position values to the plugin
        * GRBL: `\[PRB:(?P<x>[0-9]+\.[0-9]{3}),(?P<y>[0-9]+\.[0-9]{3}),(?P<z>[0-9]+\.[0-9]+):1\]`
        * If you are crafting your own regex, make sure that each pos value gets its own regex group labeling each pos with the correct id `?P<x>` for x.
    - Probe Position Command is run to ask your firmware for the position when the probe triggers
        * Marlin: `M114`
        * GRBL: leave it blank since it will autoreport the probe position
    - The x and y settings determine how many points to probe and the rectangle to probe them in
    - The different z values determine how high the plugin should move the probe:
        * When moving above and clear of the surface--clearZ
        * What height the probe should trigger by (for the firmware `G38.2` value)--probeZ
        * When probing is done and the tool moves back to the origin-finalZ
    - Offset helps with probes that are not inline with toolheads. Give the offset in mm to go from the toolhead position to the probe.
    - Send Mesh to BedLevelVisualizer will send the probed points from this plugin when enabled.
        * If you want the BLV `Update Mesh Now` button to work, then set your BedLevelVisualizer `Gcode Command for Mesh Update Process` to `@GCODELEVELING-AUTOPROBE`

## Performance

+ Due to the current implementation of this plugin, it will cause the interface to hang while processing a file upload.
    - For truly large files (I tested with a 130 MB print file and the 85 MB arc welded version of it) it can take a number of minutes (11.5 and 14 respectively on a pi4) settings dependent.
+ File size as of 0.3.0 will increase from 20% to 60% depending on the complexity of your bed surface.
    - Disabling the original copy option will save space.

## How Does this Plugin work (the technical version)

* N.B. This plugin is a bunch of applied multivariable calculus, so the following may or may not make sense.

* This plugin takes in the bed surface points and fits a polynomial model using a least squares algorithm.
    + Which just finds the optimal set of polynomials to minimize distance squared at all of the points.
* In the file preprocessing stage, the plugin works its way through a gcode file keeping track of current and previous state.
* The plugin computes the z value that the polynomial model of the surface predicts at the endpoints of a movement and applies this offset to the z value in the gcode.
* When line break distance and arc segment distance options are not 0, the plugin examines any moves longer than their respective break value and locates the positions along the movement that least match the model of the surface.
    + This is done with a path-wise gradient ascent; in other words, the plugin follows the derivative of surface model in the direction of the movement to find the maximum distance deviation point.
    + This allows for smaller files sizes since movements are only broken up when necessary; however, this does require additional computation during the file preprocessing stage.
* After file preprocessing, the plugin's work is done, and the file behaves like any other gcode file.

## Donating (optional)
If you enjoy this plugin and would like to give me a tip, here is my [PayPal][paypal-me].   [![Tip via PayPal][paypal-button]][paypal-me]

[paypal-button]: https://img.shields.io/badge/Donate-PayPal-green.svg
[paypal-me]: https://www.paypal.me/WillMacCormack
