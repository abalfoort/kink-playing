#! /usr/bin/env python3

"""_summary_
    show notification what song Kink is playing.

    Files:        $HOME/.kink-playing
    References:
    i18n:         http://docs.python.org/3/library/gettext.html
    notify:       https://lazka.github.io/pgi-docs/#Notify-0.7
    appindicator: https://lazka.github.io/pgi-docs/#AyatanaAppIndicator3-0.1
    requests:     https://requests.readthedocs.io/en/latest
    vlc:          https://www.olivieraubert.net/vlc/python-ctypes/doc/
    Author:       Arjen Balfoort, 08-05-2023
"""

import gettext
import os
import subprocess
import json
from enum import Enum
from shutil import copyfile
from pathlib import Path
from configparser import ConfigParser
from os.path import abspath, dirname, join, exists
from threading import Event, Thread
try:
    from .utils import open_text_file, str_int
except ImportError:
    from utils import open_text_file, str_int

import vlc
import requests
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Notify', '0.7')
from gi.repository import Gtk, Notify
try:
    gi.require_version('AyatanaAppIndicator3', '0.1')
    from gi.repository import AyatanaAppIndicator3 as AppIndicator3
except ValueError:
    gi.require_version('AppIndicator3', '0.1')
    from gi.repository import AppIndicator3

APP_ID = 'kink-playing'
APP_NAME = 'ꓘINK Playing'
_ = gettext.translation(APP_ID, fallback=True).gettext

class DefaultSettings(Enum):
    """ Enum with default settings.ini values """
    SITE = 'https://kink.nl'
    KINK = 'https://playerservices.streamtheworld.com/pls/KINK.pls'
    DNA = 'http://playerservices.streamtheworld.com/pls/KINK_DNA.pls'
    DISTRO = 'https://playerservices.streamtheworld.com/pls/KINK_DISTORTION.pls'
    JSON = 'https://api.kink.nl/static/now-playing.json'
    STATION = 'kink'
    WAIT = '10'
    SHOW_NOTIFICATION = '10'
    AUTOSTART = '0'
    AUTOPLAY = '1'

class MenuIcons(Enum):
    """ Enum with icon names or paths """
    PLAY = 'media-playback-start'
    PAUSE = 'media-playback-pause'
    SELECT = 'dialog-ok-apply'


class KinkPlaying():
    """ Connect to Kink player on network and show info in system tray. """
    def __init__(self):
        # Initiate variables
        scriptdir = abspath(dirname(__file__))
        home = str(Path.home())
        local_dir = join(home, f".{APP_ID}")
        autostart_dt = join(home, f".config/autostart/{APP_ID}-autostart.desktop")
        self.playlist = join(local_dir, f"{APP_ID}.txt")
        self.settings = join(local_dir, 'settings.ini')
        self.tmp_thumb = join(local_dir, 'album_art.jpg')
        self.grey_icon = join(scriptdir, f"{APP_ID}-grey.svg")
        self.instance = vlc.Instance('--intf dummy')
        self.list_player = self.instance.media_list_player_new()
        self.station = None
        self.cur_playing = {'station': '', 'program': '',
                            'artist': '','title': '', 'album_art': ''}
        # Use dict to negate the mutability of self.cur_playing
        self.prev_playing = dict(self.cur_playing)

        # to keep comments, you have to trick configparser into believing that
        # lines starting with ";" are not comments, but they are keys without a value.
        # Set comment_prefixes to a string which you will not use in the config file
        self.conf_parser = ConfigParser(comment_prefixes='/', allow_no_value=True)

        # Create local directory
        os.makedirs(local_dir, exist_ok=True)
        # Create conf file if it does not already exist
        if not exists(self.settings):
            cont = ''
            # Get default settings
            with open(file=join(scriptdir, 'settings.ini'),
                      mode='r', encoding='utf-8') as def_settings_fle:
                cont = def_settings_fle.read()
            # Save settings.ini
            with open(file=self.settings, mode='w', encoding='utf-8') as settings_fle:
                settings_fle.write(cont)
            # Let the user configure the settings and block the process until done
            self.show_settings()

        # Read the ini into a dictionary
        self.read_config()

        # Check if configured for autostart
        if self.autostart == 1:
            if not exists(autostart_dt):
                copyfile(join(scriptdir, 'kink-playing-autostart.desktop'), autostart_dt)
        else:
            if exists(autostart_dt):
                os.remove(autostart_dt)

        # Create event to use when thread is done
        self.check_done_event = Event()
        # Create global indicator object
        self.indicator = AppIndicator3.Indicator.new(APP_ID,
                                                     APP_ID,
                                                     AppIndicator3.IndicatorCategory.OTHER)
        self.indicator.set_title(APP_NAME)
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_menu(self._build_menu())

        # Init notifier
        Notify.init(APP_NAME)

        # Reset log
        if exists(self.playlist):
            os.remove(self.playlist)

        # Load the configured playlist
        self._add_playlist()
        if self.autoplay == 1:
            self.play_kink()
        else:
            self.pause_kink()

        # Start thread to check for connection changes
        Thread(target=self._run_check).start()

    def _run_check(self):
        """ Poll Kink for currently playing song. """
        was_connected = True

        while not self.check_done_event.is_set():
            # Check if kink server is online
            if not self._is_connected():
                # Show lost connection message
                if was_connected:
                    self.indicator.set_menu(self._build_menu())
                    self.indicator.set_icon_full(self.grey_icon, '')
                    unable_string = _('Unable to connect to:')
                    self.show_notification(summary=f"{unable_string} {self.station}",
                                           thumb=APP_ID)
                    was_connected = False
            else:
                # In case we had lost our connection
                if not was_connected:
                    # Build menu and show normal icon
                    self.indicator.set_menu(self._build_menu())
                    self.indicator.set_icon_full(APP_ID, '')
                    was_connected = True

                # Check if there is new playing data
                self._fill_cur_playing()
                if self.cur_playing != self.prev_playing:
                    # Get album art
                    self._save_thumb(self.cur_playing['album_art'])

                    # Send notification
                    self.show_song_info()

                    # Keep a simple log
                    playing = (f"{self.station}: "
                               f"{self.cur_playing['artist']} - {self.cur_playing['title']}")
                    print((playing))
                    with open(file=self.playlist, mode='a', encoding='utf-8') as log:
                        log.write(f"{playing}\n")

                    # Save playing data for the next loop
                    self.prev_playing = dict(self.cur_playing)

            # Wait until we continue with the loop
            self.check_done_event.wait(self.wait)

    # ===============================================
    # Kink functions
    # ===============================================

    def show_song_info(self):
        """ Show song information in notification. """
        if self.cur_playing and self.notification_timeout > 0:
            # Show notification
            artist = _('Artist')
            title = _('Title')
            self.show_notification(summary=f"{self.station}: {self.cur_playing['program']}",
                                    body=(f"<b>{artist}</b>: {self.cur_playing['artist']}\n"
                                            f"<b>{title}</b>: {self.cur_playing['title']}"),
                                    thumb=self.tmp_thumb)

    def _save_thumb(self, url):
        """Retrieve image data from url and save to path

        Args:
            url (str): image url
        """
        if not url:
            if exists(self.tmp_thumb):
                os.remove(self.tmp_thumb)
            return
        res = requests.get(url, timeout=self.wait)
        if res.status_code == 200:
            with open(file=self.tmp_thumb, mode='wb') as file:
                file.write(res.content)

    def _json_request(self):
        """Get json data from KINK.

        Returns:
            json: now playing data from KINK
        """
        res = requests.get(self.json, timeout=self.wait)
        if res.status_code == 200:
            return json.loads(res.text)
        return None

    def get_stations(self):
        """Get lists of Kink stations

        Returns:
            list: list with available KINK stations
        """
        obj = self._json_request()
        if obj:
            s_dict = obj['stations']
        else:
            return []
        stations = list(s_dict.keys())
        stations.sort()

        # kink-indie is not used
        stations.remove('kink-indie')

        return stations

    def switch_station(self, station):
        """Switch KINK station.

        Args:
            station (str): KINK station name
        """
        if station == self.station:
            return
        self.station = station
        print((f"Switch station: {self.station}"))

        was_playing = False
        if self.list_player.is_playing():
            self.stop_kink()
            was_playing = True
        self._add_playlist()
        if was_playing:
            self.play_kink()

        self.indicator.set_menu(self._build_menu())

    def _fill_cur_playing(self):
        """Get what's playing data from Kink."""
        obj = self._json_request()
        program = ''
        artist = ''
        title = ''
        album_art = ''
        if obj:
            try:
                artist = obj['extended'][self.station]['artist']
            except Exception:
                pass
            try:
                title = obj['extended'][self.station]['title']
            except Exception:
                pass
            try:
                album_art = obj['extended'][self.station]['album_art']['320']
            except Exception:
                pass
            try:
                program = obj['extended'][self.station]['program']['title']
            except Exception:
                pass

        self.cur_playing['station'] = self.station
        self.cur_playing['program'] = program
        self.cur_playing['artist'] = artist
        self.cur_playing['title'] = title
        self.cur_playing['album_art'] = album_art

    def _is_connected(self):
        """Check if Kink is online.

        Returns:
            bool: able to connect to KINK or not
        """
        res = requests.get(self.json, timeout=self.wait)
        if res.status_code == 200:
            return True
        return False

    def _get_pls(self):
        """Get the station playlist url

        Returns:
            str: play list url for current station
        """
        if 'dna' in self.station:
            return self.streams['dna']
        if 'distortion' in self.station:
            return self.streams['distortion']
        return self.streams['kink']

    def _add_playlist(self):
        """ Add playlist to VLC """
        url = self._get_pls()
        print((f"Playlist: {url}"))
        media_list = self.instance.media_list_new()
        media_list.add_media(url)
        self.list_player.set_media_list(media_list)

    def play_kink(self):
        """ Play playlist """
        self.list_player.play()
        self.indicator.set_menu(self._build_menu())

    def pause_kink(self):
        """ Pause playlist """
        self.list_player.pause()
        self.indicator.set_menu(self._build_menu())

    def stop_kink(self):
        """ Stop playlist """
        self.list_player.stop()

    # ===============================================
    # System Tray Icon
    # ===============================================
    def _get_image(self, icon):
        """Get GtkImage from icon name or path

        Args:
            icon (string): icon path

        Returns:
            Gtk.Image: image binary from path
        """
        if not icon:
            return None
        if exists(icon):
            img = Gtk.Image.new_from_file(icon, Gtk.IconSize.MENU)
        else:
            img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU)
        return img

    def _menu_item(self, label="", icon=None, function=None, argument=None):
        """Create MenuItem with given arguments

        Args:
            label (str, optional): label. Defaults to "".
            icon (str, optional): icon name/path. Defaults to None.
            function (obj, optional): function to call when clicked. Defaults to None.
            argument (str, optional): function argument. Defaults to None.

        Returns:
            Gtk.MenuItem: menu item for Gtk.Menu
        """
        item = Gtk.MenuItem.new()
        item_box = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 6)

        if icon:
            item_box.pack_start(self._get_image(icon=icon), False, False, 0)
        if label:
            item_box.pack_start(Gtk.Label.new(label), False, False, 0)

        item.add(item_box)
        item.show_all()

        if function and argument:
            item.connect('activate', lambda * a: function(argument))
        elif function:
            item.connect('activate', lambda * a: function())
        return item

    def _build_menu(self):
        """Build menu for the tray icon.

        Returns:
            Gtk.Menu: indicator menu
        """
        menu = Gtk.Menu()

        # Kink menu
        item_kink = Gtk.MenuItem.new_with_label('ꓘINK')
        sub_menu = Gtk.Menu()
        sub_menu.append(self._menu_item(label=self.site[self.site.rfind('/') + 1:],
                                        function=self.show_site))
        sub_menu.append(Gtk.SeparatorMenuItem())
        sub_menu.append(self._menu_item(label=_('Settings'),
                                        function=self.show_settings))
        sub_menu.append(Gtk.SeparatorMenuItem())
        sub_menu.append(self._menu_item(label=_('Playlist'),
                                        function=self.show_log))
        item_kink.set_submenu(sub_menu)
        menu.append(item_kink)

        # Stations
        menu.append(Gtk.SeparatorMenuItem())
        item_stations = Gtk.MenuItem.new_with_label(_('Stations'))
        stations = self.get_stations()
        if stations:
            sub_menu = Gtk.Menu()
            for station in stations:
                select_icon = ""
                if station == self.station:
                    select_icon = MenuIcons.SELECT.value
                sub_menu.append(self._menu_item(label=station,
                                                icon=select_icon,
                                                function=self.switch_station,
                                                argument=station))
            item_stations.set_submenu(sub_menu)
        menu.append(item_stations)

        # Now playing menu
        menu.append(Gtk.SeparatorMenuItem())
        item_now_playing = self._menu_item(label=_('Now playing'),
                                           function=self.show_current)
        menu.append(item_now_playing)

        # Play/pause menu
        menu.append(Gtk.SeparatorMenuItem())
        if self.list_player.is_playing():
            item_play_pause = self._menu_item(label=_('Pause'),
                                              icon=MenuIcons.PAUSE.value,
                                              function=self.play_pause)
        else:
            item_play_pause = self._menu_item(label=_('Play'),
                                              icon=MenuIcons.PLAY.value,
                                              function=self.play_pause)
        menu.append(item_play_pause)

        # Quit menu
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(self._menu_item(label=_('Quit'),
                                    function=self.quit))

        # Decide what can be used
        item_now_playing.set_sensitive(True)
        item_stations.set_sensitive(True)
        item_play_pause.set_sensitive(True)
        if not self._is_connected():
            item_now_playing.set_sensitive(False)
            item_stations.set_sensitive(False)
            item_play_pause.set_sensitive(False)

        # Show the menu and return the menu object
        menu.show_all()
        return menu

    def show_current(self, widget=None):
        """ Show last played song. """
        self.show_song_info()

    def show_site(self, widget=None):
        """ Show site in default browser """
        subprocess.call(['xdg-open', self.site])

    def show_log(self, widget=None):
        """ Show site in default browser """
        subprocess.call(['xdg-open', self.playlist])

    def play_pause(self, widget=None):
        """ Play or pause Kink radio """
        if self.list_player.is_playing():
            self.pause_kink()
        else:
            self.play_kink()

    def show_settings(self, widget=None):
        """ Open settings.ini in default editor. """
        if exists(self.settings):
            open_text_file(self.settings)
            self.read_config()

    # ===============================================
    # General functions
    # ===============================================

    def quit(self, widget=None):
        """ Quit the application. """
        self.check_done_event.set()
        self.stop_kink()
        self.save_station()
        Notify.uninit()
        Gtk.main_quit()

    def _check_conf_key(self, key):
        """Check key in settings.ini and append to file if missing.

        Args:
            key (str): settings key.
            
        Returns:
            str: value of the key
        """
        try:
            value = self.kink_dict['kink'][key]
        except KeyError:
            value = DefaultSettings[key.upper()].value
            with open(file=self.settings, mode='a', encoding='utf-8') as conf:
                conf.write(f"\n{key} = {value}\n")
        return value

    def read_config(self):
        """ Read settings.ini, save in dictionary and check some variables. """
        self.conf_parser.read(self.settings)
        self.kink_dict = {s:dict(self.conf_parser.items(s)) for s in self.conf_parser.sections()}
        self.site = self._check_conf_key('site')
        self.streams = {'kink': self._check_conf_key('stream_kink'),
                        'dna': self._check_conf_key('stream_dna'),
                        'distortion': self._check_conf_key('stream_distortion')}
        self.json = self._check_conf_key('json')
        self.station = self._check_conf_key('station')
        self.wait = str_int(self._check_conf_key('wait'))
        self.wait = max(self.wait, 1)
        self.notification_timeout = str_int(self._check_conf_key('show_notification'))
        self.autostart = str_int(self._check_conf_key('autostart'))
        self.autoplay = str_int(self._check_conf_key('autoplay'))

    def save_station(self):
        ''' Save station to the config file '''
        if 'kink' not in self.conf_parser.sections():
            self.conf_parser.add_section('kink')
        self.conf_parser.set('kink', 'station', self.station)
        with open(file=self.settings, mode='w', encoding='utf-8') as conf:
            self.conf_parser.write(conf)

    def show_notification(self, summary, body=None, thumb=None):
        """Show the notification.

        Args:
            summary (str): notification summary.
            body (str, optional): notification body text. Defaults to None.
            thumb (str, optional): icon path. Defaults to None.
        """
        notification = Notify.Notification.new(summary, body, thumb)
        notification.set_timeout(self.notification_timeout * 1000)
        notification.set_urgency(Notify.Urgency.LOW)
        notification.show()
