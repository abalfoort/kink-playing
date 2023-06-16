#!/usr/bin/env python3 -OO

""" Initialize KinkPlaying class """
# -OO: Turn on basic optimizations.  Given twice, causes docstrings to be discarded.

import sys
import subprocess
import getpass
import signal
import traceback
from pathlib import Path
from os.path import join
try:
    from .kink import KinkPlaying
    from .dialogs import error_dialog
except ImportError:
    from kink import KinkPlaying
    from dialogs import error_dialog

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

CAN_DEBUG = False
if __debug__:
    from pprint import pprint
    from types import BuiltinFunctionType, ModuleType
    if sys.stdin.isatty() and (sys.stdout.isatty() or sys.stderr.isatty()):
        try:
            import ipdb as pdb  # try to import the IPython debugger
            CAN_DEBUG = True
        except ImportError:
            try:
                import pdb
                CAN_DEBUG = True
            except ImportError:
                pass

# python3 TYPE fix
class _C:
    def _m(self):
        pass
ClassType = type(_C)
TypeType = type

def uncaught_excepthook(*args):
    """Exception hook function"""
    sys.__excepthook__(*args)
    if __debug__:
        tb = sys.last_traceback
        while tb.tb_next:
            tb = tb.tb_next
        print(('\nDumping locals() ...'))
        pprint({k:v for k,v in tb.tb_frame.f_locals.items()
                    if not k.startswith('_') and
                       not isinstance(v, (BuiltinFunctionType,
                                          ClassType, ModuleType, TypeType))})

        if CAN_DEBUG:
            print(('\nStarting interactive debug prompt ...'))
            pdb.pm()
    else:
        details = '\n'.join(traceback.format_exception(*args)).replace('<', '').replace('>', '')
        # Save to error file
        error_file = join(Path.home(), ".kink-playing/error.log")
        with open(file=error_file, mode='w', encoding='utf-8') as err_fle:
            err_fle.write(details)
        title = 'Unexpected error'
        msg = f"Please submit a bug report: {error_file}"
        error_dialog(title=title, text=f"<b>{msg}</b>" , text2=f"<tt>{details}</tt>")

    sys.exit(1)

sys.excepthook = uncaught_excepthook

def main():
    """Main function initiating KinkPlaying class"""
    KinkPlaying()
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    Gtk.main()

if __name__ == '__main__':
    main()
