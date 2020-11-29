/*
 * View model for OctoPrint-GcodeLeveling
 *
 * Author: Will MacCormack
 * License: AGPLv3
 */
$(function() {
    function GcodeLevelingViewModel(parameters) {
        var self = this;

        // assign the injected parameters, e.g.:
        self.loginState = parameters[0];
        self.settingsViewModel = parameters[1];

        self.addPoint = function() {
            self.settingsViewModel.settings.plugins.gcodeleveling.points.push([0.0, 0.0, 0.0]);
        }

        self.removePoint = function() {
            self.settingsViewModel.settings.plugins.gcodeleveling.points.remove(this);
        }

        // This is a function to trigger so that the enter key doesn't delete points
        self.safetyButton = function() {
            return
        }
    }

    /* view model class, parameters for constructor, container to bind to
     * Please see http://docs.octoprint.org/en/master/plugins/viewmodels.html#registering-custom-viewmodels for more details
     * and a full list of the available options.
     */
    OCTOPRINT_VIEWMODELS.push({
        construct: GcodeLevelingViewModel,
        // ViewModels your plugin depends on, e.g. loginStateViewModel, settingsViewModel, ...
        dependencies: [ "loginStateViewModel", "settingsViewModel" ],
        // Elements to bind to, e.g. #settings_plugin_gcodeleveling, #tab_plugin_gcodeleveling, ...
        elements: [ "#settings_plugin_gcodeleveling" ]
    });
});
