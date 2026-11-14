"""The host's part of the panel's Home Assistant API ("api":1): settings, select options and HA's page switches.

The panel runs the ESPHome-compatible server itself. The host only keeps it in step with `panel.homeassistant`,
tells it the profile and page names, and switches when Home Assistant picks one. The API key never passes here:
the control API fetches it for the editor on request (`/v1/api`) and nothing stores it.
"""
from panel_serial import api_matches, api_options_line, api_set_line, homeassistant_settings


class HomeAssistantMixin:
    def panel_supports_api(self) -> bool:
        panel = self.panel
        return (panel is not None and not self.connection_failed.is_set()
                and callable(getattr(panel, 'supports_api', None)) and panel.supports_api())

    def api_connected(self) -> None:
        """After a handshake: forget what an earlier panel had, and ask this one what it has."""
        self.api_state = self.api_sent = self.api_options_sent = None
        if self.panel_supports_api():
            self.panel.api_status()  # the answer arrives as a {"type":"api"} line

    def api_tick(self) -> None:
        """Send the names when they change, and the settings when they differ from what the panel has."""
        if not self.panel_supports_api():
            return
        profiles = list(self.config['profiles'])
        pages = list(self.config['profiles'].get(self.profile, {}).get('pages', {}))
        if (profiles, pages) != self.api_options_sent:
            self.panel.send_line(api_options_line(profiles, pages))
            self.api_options_sent = (profiles, pages)
        wanted = (self.config.get('panel') or {}).get('homeassistant')
        if wanted is None or self.api_state is None:
            return  # nothing set up on this PC (the panel keeps its own), or the panel has not reported yet
        wanted = homeassistant_settings(wanted)
        if self.api_sent is None and api_matches(self.api_state, wanted):
            self.api_sent = wanted  # the panel already has it: a reconnect does not restart its server
        if wanted != self.api_sent:
            self.panel.send_line(api_set_line(wanted))
            self.api_sent = wanted

    def ha_select(self, what, value) -> None:
        """Home Assistant picked a profile or a page on the panel's select entities; unknown names are ignored."""
        if what == 'profile' and value in self.config['profiles']:
            self.switch_profile(value)
        elif what == 'page' and value in self.config['profiles'][self.profile]['pages']:
            self.switch_page(value)
        else:
            self.log(f'Home Assistant asked for an unknown {what}; ignored')
