# OctoPrint-GcodeLeveling

This plugin creates a model of the work surface (using the least squares method on user provided points), allowing for leveling of machines through gcode that otherwise cannot be leveled (e.g. for a grbl machine). A user just needs to measure some z values at a variety of x and y values (e.g. with the paper test), then configure a couple of settings, and the plugin will handle the leveling on file upload.

This plugin really only makes sense it you have no other way of leveling out stuff (i.e. your firmware doesn't offer that feature). Also note, that the plugin will stop leveling upon a `G91` command.

## Setup

Install via the bundled [Plugin Manager](https://docs.octoprint.org/en/master/bundledplugins/pluginmanager.html)
or manually using this URL:

    https://github.com/willmac16/OctoPrint-GcodeLeveling/archive/master.zip

+ The plugin depends on numpy, so it will need to install this (if it is not already installed), which can take some time on a raspberry pi.
    - Numpy in a python3 environment requires libatlas3-base, so some instances may need to run ```sudo apt install libatlas3-base``` to install properly.

## Configuration

+ The polynomial degree settings determine how many curves you can have in each direction.
    - For example:
        * A degree of 0 will just be a flat constant height.
        * A degree of 1 will be a sloped line (in each direction so a setting of x:1 y:1 could handle a slightly tilted surface).
        * A degree of 2 will curve down and up.
     - If you are just worried about a bit of sag on an axis then something like a degree of 2 would make sense. If you use too large of a degree, like 10 in each direction with only 5 points, then the model of the surface will really closely match at your entered points, but it will be so curvy that it will be useless between the points.
        * Start with a smaller degree (e.g. 1 or 2)
        * Adjust existing points if you are having issues at the places you measured
        * or consider increasing the degree by 1
        * Add points between existing values if you are having issues in that area

+ The minimum and maximum z values are safeguards against bad combinations of gcode and configuration that would spit out positions outside of machines range.
    - If the plugin detects that a movement would fall outside this range, then the file upload will display an error and you should consider changing the configuration.

+ The invert setting is not needed by most normal configurations, and should be left disabled.
    - In my specific setup, I have a G0 Z0 sent to the printer place my toolhead as high as it can go, and a G0 Z71 takes the toolhead right to the surface. With this setting enabled, I can have the gcode files I upload to OctoPrint say that a Z of 0 is right on the surface and a z of 10 is 10 mm above it.

+ The unmodified original option creates a copy of the uploaded file with `_NO-GCL` on the end of its name, that this plugin will not modify.

+ The segment length option breaks up long moves into shorter ones that follow the height model at each of the endpoints.
    - Set the distance to 0.0 to disable this feature; otherwise, all moves longer than the specified length will be broken into smaller moves.

+ The calibration points are used to create a model of the surface.
    - Enter the x and y coordinate, then the measured z coordinate.
