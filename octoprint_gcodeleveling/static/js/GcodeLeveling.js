/*
 * View model for OctoPrint-GcodeLeveling
 *
 * Author: Will MacCormack
 * License: AGPLv3
 */
$(function() {
    function GcodeLevelingViewModel(parameters) {
        var self = this;

        self.loginState = parameters[0];
        self.settingsViewModel = parameters[1];
        self.access = parameters[2];

        self.probe = function() {
            $.ajax({
                url: API_BASEURL + "plugin/gcodeleveling",
                type: "POST",
                dataType: "json",
                data: JSON.stringify({
                    command: "probe",
                    x: parseInt(self.settingsViewModel.settings.plugins.gcodeleveling.x()),
                    y: parseInt(self.settingsViewModel.settings.plugins.gcodeleveling.y()),
                    xMin: parseFloat(self.settingsViewModel.settings.plugins.gcodeleveling.xMin()).toFixed(3),
                    xMax: parseFloat(self.settingsViewModel.settings.plugins.gcodeleveling.xMax()).toFixed(3),
                    yMin: parseFloat(self.settingsViewModel.settings.plugins.gcodeleveling.yMin()).toFixed(3),
                    yMax: parseFloat(self.settingsViewModel.settings.plugins.gcodeleveling.yMax()).toFixed(3),
                    clearZ: parseFloat(self.settingsViewModel.settings.plugins.gcodeleveling.clearZ()).toFixed(3),
                    probeZ: parseFloat(self.settingsViewModel.settings.plugins.gcodeleveling.probeZ()).toFixed(3),
                    probeRegex: self.settingsViewModel.settings.plugins.gcodeleveling.probeRegex(),
                    probePosCmd: self.settingsViewModel.settings.plugins.gcodeleveling.probePosCmd(),
                    homeCmd: self.settingsViewModel.settings.plugins.gcodeleveling.homeCmd(),
                    probeFeedrate: parseFloat(self.settingsViewModel.settings.plugins.gcodeleveling.probeFeedrate()).toFixed(3),
                    xOffset: parseFloat(self.settingsViewModel.settings.plugins.gcodeleveling.xOffset()).toFixed(3),
                    yOffset: parseFloat(self.settingsViewModel.settings.plugins.gcodeleveling.yOffset()).toFixed(3),
                    zOffset: parseFloat(self.settingsViewModel.settings.plugins.gcodeleveling.zOffset()).toFixed(3),
                    finalZ: parseFloat(self.settingsViewModel.settings.plugins.gcodeleveling.finalZ()).toFixed(3),
                    sendBedLevelVisualizer: self.settingsViewModel.settings.plugins.gcodeleveling.sendBedLevelVisualizer()
                }),
                contentType: "application/json; charset=UTF-8"
            });
        }

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
        self.onDataUpdaterPluginMessage = function(plugin, data) {
            if (plugin === "gcodeleveling") {
                if (data.state === "startProbing") {
                    self.probePoints = data.totalPoints;
                    self.probingNotify = new PNotify({
                        title: 'Started Probing',
                        type: 'info',
                        textTrusted: true,
                        text: `Currently Homing: @ Point (0/${self.probePoints}) <br />
                            <div class="progress progress-striped active"><div class="bar" style="width: 0%"></div></div>`,
                        hide: false
                    });
                } else if (data.state === "updateProbing") {
                    if (!self.probingNotify) {
                        self.probePoints = data.totalPoints;
                        self.probingNotify = new PNotify({
                            title: 'Probing',
                            type: 'info',
                            textTrusted: true,
                            text: `@ Point (${data.currentPoint}/${self.probePoints}) <br />
                                <div class="progress progress-striped active"><div class="bar" style="width: ${data.currentPoint/self.probePoints*100.0}%"></div></div>`,
                            hide: false
                        });
                    } else {
                        pointUpdate = {
                            title: 'Probing',
                            text: `@ Point (${data.currentPoint}/${self.probePoints}) <br />
                                <div class="progress progress-striped active"><div class="bar" style="width: ${data.currentPoint/self.probePoints*100.0}%"></div></div>`
                        }
                        self.probingNotify.update(pointUpdate);
                    }
                } else if (data.state === "finishedProbing") {
                    if (!self.probingNotify) {
                        self.probePoints = data.totalPoints;
                        self.probingNotify = new PNotify({
                            title: 'Finished Probing',
                            type: 'info',
                            textTrusted: true,
                            text: `${self.probePoints} were probed and saved <br />
                                <div class="progress progress-striped active"><div class="bar" style="width: 100%"></div></div>`,
                            hide: false
                        });
                    } else {
                        finishUpdate = {
                            title: 'Finished Probing',
                            text: `${self.probePoints} points were probed and saved <br />
                                <div class="progress progress-striped active"><div class="bar" style="width: 100%"></div></div>`
                        }
                        self.probingNotify.update(finishUpdate);
                    }
                }
            }
        }

        self.onDataUpdaterReconnect = function () {
            self.notifies = {};
        }
    }

    /* view model class, parameters for constructor, container to bind to
     * Please see http://docs.octoprint.org/en/master/plugins/viewmodels.html#registering-custom-viewmodels for more details
     * and a full list of the available options.
     */
    OCTOPRINT_VIEWMODELS.push({
        construct: GcodeLevelingViewModel,
        // ViewModels your plugin depends on, e.g. loginStateViewModel, settingsViewModel, ...
        dependencies: [ "loginStateViewModel", "settingsViewModel", "accessViewModel" ],
        // Elements to bind to, e.g. #settings_plugin_gcodeleveling, #tab_plugin_gcodeleveling, ...
        elements: [ "#settings_plugin_gcodeleveling" ]
    });
});
