#!/usr/bin/env python3

"""Create Dialog objects:
   - Message
   - Error
   - Warning
   - Question

Returns:
    Dialog object
"""

from os.path import exists
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib


DIALOG_TYPES = {
    Gtk.MessageType.INFO: 'MessageDialog',
    Gtk.MessageType.ERROR: 'ErrorDialog',
    Gtk.MessageType.WARNING: 'WarningDialog',
    Gtk.MessageType.QUESTION: 'QuestionDialog',
}


class Dialog(Gtk.MessageDialog):
    """_summary_
        Show message dialog
        Usage:
        MessageDialog(_("My Title"), "Your message here")
        Use safe=False when calling from a thread

    Args:
        Gtk (MessageDialog): MessageDialog object
    """
    def __init__(self, message_type, buttons, title, text, 
                 text2=None, parent=None, safe=True, icon=None):
        parent = parent or next((w for w in Gtk.Window.list_toplevels() if w.get_title()), None)
        Gtk.MessageDialog.__init__(self,
                                   parent=None,
                                   modal=True,
                                   destroy_with_parent=True,
                                   message_type=message_type,
                                   buttons=buttons,
                                   text=text)
        self.set_position(Gtk.WindowPosition.CENTER)
        if parent is not None:
            self.set_icon(parent.get_icon())
        elif icon is not None:
            if exists(icon):
                self.set_icon_from_file(icon)
            else:
                self.set_icon_name(icon)
        self.set_title(title)
        self.set_markup(text)
        self.desc = text[:30] + ' ...' if len(text) > 30 else text
        self.dialog_type = DIALOG_TYPES[message_type]
        if text2:
            self.format_secondary_markup(text2)
        self.safe = safe
        if not safe:
            self.connect('response', self._handle_clicked)

    def _handle_clicked(self, *args):
        self.destroy()

    def show(self):
        if self.safe:
            return self._do_show_dialog()
        else:
            return GLib.timeout_add(0, self._do_show_dialog)

    def _do_show_dialog(self):
        """ Show the dialog.
            Returns True if user response was confirmatory.
        """
        #print(('Showing {0.dialog_type} ({0.desc})'.format(self)))
        try:
            return self.run() in (Gtk.ResponseType.YES, Gtk.ResponseType.APPLY,
                                  Gtk.ResponseType.OK, Gtk.ResponseType.ACCEPT)
        finally:
            if self.safe:
                self.destroy()
            else:
                return False


def MessageDialog(*args):
    """Message Dialog object"""
    return Dialog(Gtk.MessageType.INFO, Gtk.ButtonsType.OK, *args).show()


def QuestionDialog(*args):
    """Question Dialog object"""
    return Dialog(Gtk.MessageType.QUESTION, Gtk.ButtonsType.YES_NO, *args).show()


def WarningDialog(*args):
    """Warning Dialog object"""
    return Dialog(Gtk.MessageType.WARNING, Gtk.ButtonsType.OK, *args).show()


def ErrorDialog(*args):
    """Error Dialog object"""
    return Dialog(Gtk.MessageType.ERROR, Gtk.ButtonsType.OK, *args).show()
