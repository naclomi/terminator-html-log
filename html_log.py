""" html_logger.py - Record the output of terminal sessions to a static,
    standalone HTML file that can be viewed in a web browser. """

# TODO:
#   only select/copy text written by the user (with option to turn it off)
#   be able to mouse over non-alpha-numerics to see both their name and a visual indicator of 
#   the keyboard location

import os
import sys
import termios
from gi.repository import Gtk
import terminatorlib.plugin as plugin
from terminatorlib.translation import _

html_header = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8" />
    <style type="text/css">
        body {{
            padding: 1em;
            background-color: {bgcolor};
            color: #DDDDDD;
            font-family: fixed;
            font-size: 1.5em;
        }}
        @media only screen and (max-width: 850px) {{
          body {{
            font-size: 2vw;
          }}
        }}
    </style>
</head>
<body>
<pre>
"""

html_footer = """
</pre>
<script type="text/javascript">
    window.scrollTo(0,document.body.scrollHeight);
    window.onbeforeunload = function () {
        window.scrollTo(0,document.body.scrollHeight);
    }
</script>
</body>
</html>
"""

AVAILABLE = ['HtmlLogger']

def pangoToHtmlColor(color):
    return "#{:02X}{:02X}{:02X}".format(
        int(((color[0]/0xFFFF)*255)), int((color[1]/0xFFFF)*255), int((color[2]/0xFFFF)*255)
    )

def gdkToHtmlColor(color):
    return "#{:02X}{:02X}{:02X}".format(
        int(color.red*255), int(color.green*255), int(color.blue*255)
    )

def getFileSelection(_widget):
    selection = None
    savedialog = Gtk.FileChooserDialog(title=_("Save Log File As"),
                                       action=Gtk.FileChooserAction.SAVE,
                                       buttons=(_("_Cancel"), Gtk.ResponseType.CANCEL,
                                                _("_Save"), Gtk.ResponseType.OK))
    savedialog.set_transient_for(_widget.get_toplevel())
    savedialog.set_do_overwrite_confirmation(True)
    savedialog.set_local_only(True)
    savedialog.show_all()
    response = savedialog.run()
    if response == Gtk.ResponseType.OK:
        try:
            selection = os.path.join(savedialog.get_current_folder(),
                                   savedialog.get_filename())
        except:
            e = sys.exc_info()[1]
            error = Gtk.MessageDialog(None, Gtk.DialogFlags.MODAL, Gtk.MessageType.ERROR,
                                      Gtk.ButtonsType.OK, e.strerror)
            error.set_transient_for(savedialog)
            error.run()
            error.destroy()
    savedialog.destroy()
    return selection

def vteTextToHtml(content, selectable):
    last_text_mode = None
    output = []
    content_bytes = content[0].encode()
    for idx, attr in enumerate(content[1]):
        bg = attr.back
        fg = attr.fore
        # TODO: .......how are the values of
        #       strikethrough and underline encoded?
        text_mode = (
            (bg.red, bg.green, bg.blue),
            (fg.red, fg.green, fg.blue),
            False, # attr.strikethrough,
            selectable[idx], # attr.underline
        )
        if text_mode != last_text_mode:
            if last_text_mode is not None:
                if last_text_mode[3]:
                    output.append(b"</u>")
                if last_text_mode[2]:
                    output.append(b"</s>")
                output.append(b"</span>")
            output.append("<span style='color: {:}; background-color: {:};'>".format(
                pangoToHtmlColor(text_mode[1]),
                pangoToHtmlColor(text_mode[0]),
            ).encode())
            if text_mode[2]:
                output.append(b"<s>")
            if text_mode[3]:
                output.append(b"<u>")

            last_text_mode = text_mode
        output.append(content_bytes[idx:idx+1])
    return b"".join(output)

def isCanonical(terminal):
    tty_mode = termios.tcgetattr(terminal.get_pty().get_fd())
    return (tty_mode[3] & termios.IEXTEN)!=0

class HtmlLogger(plugin.MenuItem):
    capabilities = ['terminal_menu']
    loggers = None

    def __init__(self):
        plugin.MenuItem.__init__(self)
        if not self.loggers:
            self.loggers = {}

    def callback(self, menuitems, menu, terminal):
        vte_terminal = terminal.get_vte()
        if vte_terminal not in self.loggers:
            item = Gtk.MenuItem.new_with_mnemonic(_('Start HTML _Logger'))
            item.connect("activate", self.start_logger, terminal)
        else:
            item = Gtk.MenuItem.new_with_mnemonic(_('Stop HTML _Logger'))
            item.connect("activate", self.stop_logger, terminal)
            item.set_has_tooltip(True)
            item.set_tooltip_text("Saving at '" + self.loggers[vte_terminal]["filepath"] + "'")
        menuitems.append(item)
        
    def write_content(self, terminal, row_start, col_start, row_end, col_end):
        content = terminal.get_text_range(row_start, col_start, row_end, col_end,
                                          lambda *a: True)
        fd = self.loggers[terminal]["fd"]
        if not self.loggers[terminal]["first-write"]:
            fd.seek(-len(html_footer), os.SEEK_CUR)

        selectable = [False] * len(content[1]) 

        fd.write(vteTextToHtml(content, selectable))
        fd.write(html_footer.encode())
        fd.flush()

        self.loggers[terminal]["first-write"] = False
        self.loggers[terminal]["col"] = col_end
        self.loggers[terminal]["row"] = row_end

    def sig_input(self, terminal, value, size):
        if not isCanonical(terminal):
            return

        if value.endswith("\r"):
            self.loggers[terminal]["log-output"] = True
        
    def sig_change(self, terminal):
        if not isCanonical(terminal):
            return

        # TODO: this breaks when using up/down to select
        #       commands from history. figure out a better
        #       way to skim changes
        last_saved_col = self.loggers[terminal]["col"]
        last_saved_row = self.loggers[terminal]["row"]
        (col, row) = terminal.get_cursor_position()
        if self.loggers[terminal]["log-output"]:
            self.write_content(terminal, last_saved_row, last_saved_col, row, col)
        self.loggers[terminal]["log-output"] = False

    def start_logger(self, _widget, Terminal):
        logfile = getFileSelection(_widget)
        # logfile = "/home/nacl/Desktop/foo.html"
        fd = open(logfile, 'wb')
        vte_terminal = Terminal.get_vte()
        (col, row) = vte_terminal.get_cursor_position()

        self.loggers[vte_terminal] = {
            "filepath":logfile,
            "handlers":[],
            "fd":fd,
            "col":0, "row":0,
            "log-output": True,
            "first-write": True}
        self.loggers[vte_terminal]["handlers"].append(vte_terminal.connect('commit', self.sig_input))
        self.loggers[vte_terminal]["handlers"].append(vte_terminal.connect('contents-changed', self.sig_change))
        # self.loggers[vte_terminal]["handlers"].append(vte_terminal.connect('text-inserted', lambda *x: print("text-insert", x)))
        # self.loggers[vte_terminal]["handlers"].append(vte_terminal.connect('commit', lambda *x: print("commit", x)))

        fd.write(html_header.format(
            bgcolor=gdkToHtmlColor(Terminal.bgcolor)
        ).encode())

        self.write_content(vte_terminal, 0, 0, row, col)

    def stop_logger(self, _widget, Terminal):
        vte_terminal = Terminal.get_vte()
        self.sig_change(vte_terminal)
        self.loggers[vte_terminal]["fd"].close()
        for handler in self.loggers[vte_terminal]["handlers"]:
            vte_terminal.disconnect(handler)
        del(self.loggers[vte_terminal])

    def unload(self):
        for terminal, logger in self.loggers.items():
            self.sig_change(terminal)
            logger["fd"].close()
            for handler in logger["handlers"]:
                terminal.disconnect(handler)