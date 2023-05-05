#! /usr/bin/env python3

"""_summary_
    show notification what song Kink is playing.

    Files:        $HOME/.kink-playing
    References:
    i18n:         http://docs.python.org/3/library/gettext.html
    notify:       https://lazka.github.io/pgi-docs/#Notify-0.7
    appindicator: https://lazka.github.io/pgi-docs/#AyatanaAppIndicator3-0.1
    csv:          https://docs.python.org/3/library/csv.html
    requests:     https://requests.readthedocs.io/en/latest
    vlc:          https://www.olivieraubert.net/vlc/python-ctypes/doc/
    Author:       Arjen Balfoort, 01-05-2023
"""

import gettext
import os
import csv
import subprocess
import requests
import json
import vlc
from shutil import copyfile
from pathlib import Path
from configparser import ConfigParser
from os.path import abspath, dirname, join, exists
from threading import Event, Thread
try:
    from .utils import open_text_file, str_int
except ImportError:
    from utils import open_text_file, str_int

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

APPINDICATOR_ID = 'kink-playing'
_ = gettext.translation(APPINDICATOR_ID, fallback=True).gettext


class KinkPlaying():
    """ Connect to Kink player on network and show info in system tray. """
    def __init__(self):
        # Initiate variables
        self.scriptdir = abspath(dirname(__file__))
        self.home = str(Path.home())
        self.local_dir = join(self.home, '.kink-playing')
        self.conf = join(self.local_dir, 'settings.ini')
        self.csv = join(self.local_dir, 'kink-playing.csv')
        self.tmp_thumb = '/tmp/kink-playing.jpg'
        self.autostart_dt = join(self.home, '.config/autostart/kink-playing-autostart.desktop')
        self.grey_icon = join(self.scriptdir, 'kink-playing-grey.svg')
        self.instance = vlc.Instance("--intf dummy")
        self.list_player = self.instance.media_list_player_new()
        self.media_list = self.instance.media_list_new()
        self.list_player.set_media_list(self.media_list)
        self.station = 'kink'

        # to keep comments, you have to trick configparser into believing that
        # lines starting with ";" are not comments, but they are keys without a value.
        # Set comment_prefixes to a string which you will not use in the config file
        self.config = ConfigParser(comment_prefixes='/', allow_no_value=True)

        # Create local directory
        os.makedirs(self.local_dir, exist_ok=True)
        # Create conf file if it does not already exist
        if not exists(self.conf):
            cont = ''
            # Get default settings
            with open(file=join(self.scriptdir, 'settings.ini'), mode='r', encoding='utf-8') as f:
                cont = f.read()
            # Save settings.ini
            with open(file=self.conf, mode='w', encoding='utf-8') as f:
                f.write(cont)
            # Let the user configure the settings and block the process until done
            self.show_settings()

        # Read the ini into a dictionary
        self.read_config()

        # Check if configured for autostart
        if self.autostart == 1:
            if not exists(self.autostart_dt):
                copyfile(join(self.scriptdir, 'kink-playing-autostart.desktop'), self.autostart_dt)
        else:
            if exists(self.autostart_dt):
                os.remove(self.autostart_dt)

        # Create event to use when thread is done
        self.check_done_event = Event()
        # Create global indicator object
        self.indicator = AppIndicator3.Indicator.new(APPINDICATOR_ID,
                                                     'kink-playing',
                                                     AppIndicator3.IndicatorCategory.OTHER)
        self.indicator.set_title('KINK Playing')
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_menu(self.build_menu())

        # Init notifier
        Notify.init('ꓘINK')

        # Load the configured playlist
        self.add_playlist()
        self.pause_kink()
        if self.autoplay == 1:
            self.play_kink()

        # Start thread to check for connection changes
        Thread(target=self.run_check).start()

    def run_check(self):
        """ Poll Kink for currently playing song. """
        # Initiate csv file (tab delimited)
        open(file=self.csv, mode='w', encoding='utf-8').close()
        # Initiate variables
        prev_title = ''
        was_connected = True

        while not self.check_done_event.is_set():
            # Check if kink server is online
            if not self.is_connected():
                # Show lost connection message
                if was_connected:
                    self.indicator.set_menu(self.build_menu())
                    self.indicator.set_icon_full(self.grey_icon, '')
                    unable_string = _('Unable to connect to:')
                    self.show_notification(summary=f"{unable_string} {self.station}",
                                           thumb='kink-playing')
                    was_connected = False
            else:
                # In case we had lost our connection
                if not was_connected:
                    # Build menu and show normal icon
                    self.indicator.set_menu(self.build_menu())
                    self.indicator.set_icon_full('kink-playing', '')
                    was_connected = True

                # Retrieve the title first
                playing = self.get_playing()
                if playing:
                    if playing['title'] and playing['title'] !=  prev_title:
                        # Logging
                        with open(file=self.csv, mode='a', encoding='utf-8') as csv_fle:
                            csv_fle.write(f"{self.station}\t{playing['artist']}\t{playing['title']}"
                                    f"\t{playing['program']}\t{playing['album_art']}\n")
                        # Send notification
                        self.show_song_info()

                        # Save the title for the next loop
                        prev_title = playing['title']

            # Wait until we continue with the loop
            self.check_done_event.wait(self.wait)

    # ===============================================
    # Kink functions
    # ===============================================

    def show_song_info(self, index=1):
        """ Show song information in notification. """
        # Get last two songs from csv data
        csv_data = []
        i = 0
        with open(file=self.csv, mode='r', encoding='utf-8') as csv_fle:
            for row in reversed(list(csv.reader(csv_fle, delimiter='\t'))):
                i += 1
                # We need to save the selected song
                # and the previous song to compare thumbnails
                if len(row) >= 5 and i in (index, index + 1):
                    csv_data.append(row)
                    if i == index + 1:
                        break

        if csv_data:
            artist_title = _('Artist')
            title_title = _('Title')
            artist_str = ''
            title_str = ''
            spaces = '<td> </td><td> </td><td> </td><td> </td>'

            # Artist
            if csv_data[0][1]:
                artist_str = (f"<tr><td><b>{artist_title}</b></td><td>:"
                              f"</td>{spaces}<td>{csv_data[0][1]}</td></tr>")

            # Title
            if csv_data[0][2]:
                title_str = (f"<tr><td><b>{title_title}</b></td><td>:"
                              f"</td>{spaces}<td>{csv_data[0][2]}</td></tr>")

            # Album art
            if csv_data[0][4]:
                # Check with previous song before downloading thumbnail
                if not exists(self.tmp_thumb) or len(csv_data) == 1:
                    self.save_thumb(csv_data[0][4])
                elif len(csv_data) > 1:
                    if csv_data[0][4] != csv_data[1][4] or index > 1:
                        self.save_thumb(csv_data[0][4])

            # Show notification
            if self.notification_timeout > 0:
                print((f"Now playing: {csv_data[0][1]} - {csv_data[0][2]}"))
                self.show_notification(summary=f"{self.station}: {csv_data[0][3]}",
                                       body=(f"<table>{artist_str}{title_str}</table>"),
                                       thumb=self.tmp_thumb)
            try:
                # If runnin from terminal: show info
                # Crashes when terminal has been closed afterwards
                print(','.join(csv_data))
            except Exception:
                pass

    def save_thumb(self, url):
        """ Retrieve image data from url and save to path """
        res = requests.get(url, timeout=self.wait)
        if res.status_code == 200:
            with open(self.tmp_thumb, 'wb') as file:
                file.write(res.content)

    def json_request(self):
        """ Return json data from Kink. """
        try:
            res = requests.get(self.json, timeout=self.wait)
        except Exception:
            return ''
        return json.loads(res.text)

    def get_stations(self):
        """ Get lists of Kink stations """
        obj = self.json_request()
        try:
            s_dict = obj['stations']
        except Exception:
            return []
        stations = list(s_dict.keys())
        stations.sort()
        return stations

    def switch_station(self, station):
        """ Switch station """
        if station == self.station:
            return
        self.station = station
        print((f"Switch station: {self.station}"))

        was_playing = False
        if self.list_player.is_playing():
            self.stop_kink()
            was_playing = True
        self.add_playlist()
        if was_playing:
            self.play_kink()

        self.indicator.set_menu(self.build_menu())

    def get_playing(self):
        """ Get what's playing data from Kink. """
        obj = self.json_request()
        try:
            artist = obj['extended'][self.station]['artist']
            title = obj['extended'][self.station]['title']
            album_art = obj['extended'][self.station]['album_art']['320']
            program = obj['extended'][self.station]['program']['title']
        except Exception:
            return {}
        return {"artist": artist, "title": title, "album_art": album_art, "program": program}

    def is_connected(self):
        """ Check if Kink is online. """
        try:
            res = requests.get(self.json, timeout=self.wait)
            if res.status_code == 200:
                return True
            return False
        except Exception:
            return False

    def get_pls(self):
        """ Get the station playlist url """
        if 'dna' in self.station:
            return self.streams['dna']
        if 'indie' in self.station:
            return self.streams['indie']
        if 'distortion' in self.station:
            return self.streams['distortion']
        return self.streams['kink']

    def add_playlist(self):
        """ Add playlist to VLC """
        url = self.get_pls()
        print((f"Playlist: {url}"))
        self.media_list.add_media(url)

    def play_kink(self):
        """ Play playlist """
        self.list_player.play()
        self.indicator.set_menu(self.build_menu())

    def pause_kink(self):
        """ Pause playlist """
        self.list_player.pause()
        self.indicator.set_menu(self.build_menu())

    def stop_kink(self):
        """ Stop playlist """
        self.list_player.stop()

    # ===============================================
    # System Tray Icon
    # ===============================================
    def get_image(self, icon):
        """ Get GtkImage from icon name or path """
        if os.path.exists(icon):
            img = Gtk.Image.new_from_file(icon, Gtk.IconSize.MENU)
        else:
            img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU)
        return img

    def menu_item(self, label="", icon=None, function=None, arguments=None):
        """ Return a MenuItem with given arguments """
        item = Gtk.MenuItem.new()
        item_box = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 6)

        if icon:
            item_box.pack_start(self.get_image(icon=icon), False, False, 0)
        if label:
            item_box.pack_start(Gtk.Label.new(label), False, False, 0)

        item.add(item_box)
        item.show_all()

        if function and arguments:
            item.connect("activate", lambda * a: function(arguments))
        elif function:
            item.connect("activate", lambda * a: function())
        return item

    def build_menu(self):
        """ Build menu for the tray icon. """
        menu = Gtk.Menu()

        # Kink menu
        item_kink = Gtk.MenuItem.new_with_label('ꓘINK')
        sub_menu = Gtk.Menu()
        sub_menu.append(self.menu_item(label=self.site[self.site.rfind('/') + 1:],
                                       function=self.show_site))
        sub_menu.append(Gtk.SeparatorMenuItem())
        sub_menu.append(self.menu_item(label=_('Show played songs'),
                                       function=self.show_csv))
        sub_menu.append(Gtk.SeparatorMenuItem())
        sub_menu.append(self.menu_item(label=_('Settings'),
                                       function=self.show_settings))
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
                    select_icon = "dialog-ok-apply"
                sub_menu.append(self.menu_item(label=station,
                                               icon=select_icon,
                                               function=self.switch_station,
                                               arguments=station))
            item_stations.set_submenu(sub_menu)
        menu.append(item_stations)

        # Now playing menu
        menu.append(Gtk.SeparatorMenuItem())
        item_now_playing = self.menu_item(label=_('Now playing'),
                                          function=self.show_current)
        menu.append(item_now_playing)

        # Play/pause menu
        menu.append(Gtk.SeparatorMenuItem())
        if self.list_player.is_playing():
            item_play_pause = self.menu_item(label=_('Pause'),
                                             icon="media-playback-pause",
                                             function=self.play_pause)
        else:
            item_play_pause = self.menu_item(label=_('Play'),
                                             icon="media-playback-start",
                                             function=self.play_pause)
        menu.append(item_play_pause)

        # Quit menu
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(self.menu_item(label=_('Quit'),
                                   function=self.quit))

        # Decide what can be used
        item_now_playing.set_sensitive(True)
        item_stations.set_sensitive(True)
        item_play_pause.set_sensitive(True)
        if not self.is_connected():
            item_now_playing.set_sensitive(False)
            item_stations.set_sensitive(False)
            item_play_pause.set_sensitive(False)

        # Show the menu and return the menu object
        menu.show_all()
        return menu

    def show_current(self, widget=None):
        """ Show last played song. """
        self.show_song_info()
        if exists(self.tmp_thumb):
            os.remove(self.tmp_thumb)

    def show_csv(self, widget=None):
        """ Open kink-playing.csv in default editor. """
        subprocess.call(['xdg-open', self.csv])

    def show_site(self, widget=None):
        """ Show site in default browser """
        subprocess.call(['xdg-open', self.site])

    def play_pause(self, widget=None):
        """ Play or pause Kink radio """
        if self.list_player.is_playing():
            self.pause_kink()
        else:
            self.play_kink()

    def show_settings(self, widget=None):
        """ Open settings.ini in default editor. """
        if exists(self.conf):
            open_text_file(self.conf)
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

    def check_conf_key(self, key, default_value):
        """ Check key in settings.ini and append missing key """
        try:
            value = self.kink_dict['kink'][key]
        except KeyError:
            value = default_value
            with open(file=self.conf, mode='a', encoding='utf-8') as conf:
                conf.write(f"\n{key} = {value}\n")
        return value

    def read_config(self):
        """ Read settings.ini, save in dictionary and check some variables. """
        self.config.read(self.conf)
        self.kink_dict = {s:dict(self.config.items(s)) for s in self.config.sections()}

        self.site = self.check_conf_key('site', 'https://kink.nl')
        self.streams = {'kink': self.check_conf_key('stream_kink',
                                                    'https://playerservices.streamtheworld.com/pls/KINK.pls'),
                        'dna': self.check_conf_key('stream_dna',
                                                   'http://playerservices.streamtheworld.com/pls/KINK_DNA.pls'),
                        'indie': self.check_conf_key('stream_indie',
                                                     'https://playerservices.streamtheworld.com/pls/KINKINDIE.pls'),
                        'distortion': self.check_conf_key('stream_distortion',
                                                          'https://playerservices.streamtheworld.com/pls/KINK_DISTORTION.pls')}
        self.json = self.check_conf_key('json',
                                        'https://api.kink.nl/static/now-playing.json')
        self.station = self.check_conf_key('station', 'kink')
        self.wait = str_int(self.check_conf_key('wait', '10'), 10)
        self.wait = max(self.wait, 1)
        self.notification_timeout = str_int(self.check_conf_key('show_notification', '10'), 10)
        self.autostart = str_int(self.check_conf_key('autostart', '0'), 0)
        self.autoplay = str_int(self.check_conf_key('autoplay', '1'), 1)

    def save_station(self):
        ''' Save station to the config file '''
        if 'kink' not in self.config.sections():
            self.config.add_section('kink')
        self.config.set('kink', 'station', self.station)
        with open(file=self.conf, mode='w', encoding='utf-8') as conf:
            self.config.write(conf)

    def show_notification(self, summary, body=None, thumb=None):
        """ Show the notification. """
        notification = Notify.Notification.new(summary, body, thumb)
        notification.set_timeout(self.notification_timeout * 1000)
        notification.set_urgency(Notify.Urgency.LOW)
        notification.show()
