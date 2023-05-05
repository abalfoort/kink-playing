#! /usr/bin/env python3

"""Common utilities"""

import subprocess
import shlex
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gio


def open_text_file(file_path):
    """ Open text file in default application and wait until done. """

    # Get default application
    app = subprocess.check_output(['xdg-mime',
	                               'query',
								   'default',
								   'text/plain']).decode('utf-8').strip()

    # Get command to run
    command = Gio.DesktopAppInfo.new(app).get_commandline()

    # Handle file paths with spaces by quoting the file path
    file_path_quoted = "'" + file_path + "'"

    # Replace field codes with the file path
    # Also handle special case of the atom editor
    command = command.replace('%u', file_path_quoted)\
    .replace('%U', file_path_quoted)\
    .replace('%f', file_path_quoted)\
    .replace('%F', file_path_quoted if app != 'atom.desktop' else '--wait ' + file_path_quoted)

    # Run the default application, and wait for it to terminate
    process = subprocess.Popen(
    shlex.split(command), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    process.wait()

    # Now the exit code of the text editor process is available as process.returncode
    return process.returncode

def str_int(nr_str, default_int):
    """ Convert string to integer or return default value. """
    try:
        return int(nr_str)
    except ValueError:
        return default_int
