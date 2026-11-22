# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# XBMC Config Menu
# ------------------------------------------------------------

from __future__ import division
import sys, os, inspect, xbmcgui, xbmc
PY3 = False
if sys.version_info[0] >= 3: PY3 = True; unicode = str; unichr = chr; long = int
from builtins import range
from past.utils import old_div

from core import channeltools, servertools, scrapertools
from platformcode import config, logger, platformtools
from core.support import info, dbg, match


class SettingsWindow(xbmcgui.WindowXMLDialog):
    """
    Derived class that allows you to use custom configuration boxes.

    This class is derived from xbmcgui.WindowXMLDialog and allows you to create a dialog box with controls of the type:
    Radio Button (bool), Text Box (text), List (list) and Information Labels (label).
    We can also customize the box by adding a title (title).

    Construction method:
        SettingWindow(list_controls, dict_values, title, callback, item)
            Parameters:
                list_controls: (list) List of controls to include in the window, according to the following scheme:
                    (opcional)list_controls= [
                                {'id': "nameControl1",
                                  'type': "bool",                       # bool, text, list, label
                                  'label': "Control 1: type RadioButton",
                                  'color': '0xFFee66CC',                # text color in hexadecimal ARGB format
                                  'default': True,
                                  'enabled': True,
                                  'visible': True
                                },
                                {'id': "nameControl2",
                                  'type': "text",                       # bool, text, list, label
                                  'label': "Control 2: type text box",
                                  'color': '0xFFee66CC',
                                  'default': "Valor por defecto",
                                  'hidden': False,                      # only for type = text Indicates whether to hide the text (for passwords)
                                  'enabled': True,
                                  'visible': True
                                },
                                {'id': "nameControl3",
                                  'type': "list",                       # bool, text, list, label
                                  'label': "Control 3: type List",
                                  'color': '0xFFee66CC',
                                  'default': 0,                         # Default value index in lvalues
                                  'enabled': True,
                                  'visible': True,
                                  'lvalues':["item1", "item2", "item3", "item4"],  # only for type = list
                                },
                                {'id': "nameControl4",
                                  'type': "label",                       # bool, text, list, label
                                  'label': "Control 4: tipo Etiqueta",
                                  'color': '0xFFee66CC',
                                  'enabled': True,
                                  'visible': True
                                }]
                    If the controls list is not included, an attempt is made to obtain the json of the channel from which the call is made.

                    The format of the controls in the json is:
                        {
                            ...
                            ...
                            "settings": [
                                {
                                   "id": "name_control_1",
                                    "type": "bool",
                                    "label": "Control 1: type RadioButton",
                                    "default": false,
                                    "enabled": true,
                                    "visible": true,
                                    "color": "0xFFee66CC"
                                },
                                {
                                    "id": "name_control_2",
                                    "type": "text",
                                    "label": "Control 2: type text box",
                                    "default": "Default value",
                                    "hidden": true,
                                    "enabled": true,
                                    "visible": true,
                                    "color": "0xFFee66CC"
                                },
                                {
                                    "id": "name_control_3",
                                    "type": "list",
                                    "label": "Control 3: type List",
                                    "default": 0,
                                    "enabled": true,
                                    "visible": true,
                                    "color": "0xFFee66CC",
                                    "lvalues": [
                                        "item1",
                                        "item2",
                                        "item3",
                                        "item4"
                                    ]
                                },
                                {
                                    "id": "name_control_4",
                                    "type": "label",
                                    "label": "Control 4: tipo Etiqueta",
                                    "enabled": true,
                                    "visible": true,
                                    "color": "0xFFee66CC"
                                },
                            ]
                        }

                The fields 'label', 'default', 'enabled' and 'lvalues' can be a number preceded by '@'. In which case
                it will look for the literal in the string.xml file of the selected language.
                The 'enabled' and 'visible' fields support the comparators eq (), gt () and it () and their operation is
                described at: http://kodi.wiki/view/Add-on_settings#Different_types

                (opcional) dict_values: (dict) Dictionary representing the pair (id: value) of the controls in the list.
                If any control in the list is not included in this dictionary, it will be assigned the default value.
                        dict_values={"nameControl1": False,
                                     "nameControl2": "Esto es un ejemplo"}

                (opcional) caption: (str) Configuration window title. It can be located by a number preceded by '@'
                (opcional) callback (str) Name of the function, of the channel from which the call is made, which will be
                invoked when pressing the accept button in the window. This function will be passed as parameters the
                object 'item' and the 'dict_values' dictionary. If this parameter does not exist, the channel is searched for
                 function called 'cb_validate_config' and if it exists it is used as a callback.

            Retorno: If 'callback' is specified or the channel includes 'cb_validate_config' what that function returns will be returned. If not return none

    Usage examples:
        platformtools.show_channel_settings(): As such, without passing any argument, the window detects which channel the call has been made,
                                               and read the json settings and load the controls, when you click OK, save them again.

        return platformtools.show_channel_settings(list_controls=list_controls, dict_values=dict_values, callback='cb', item=item):
            This opens the window with the passed controls and the dict_values values, if dict_values is not passed, it loads the default values of the controls,
            when you accept, it calls the 'callback' function of the channel from where it was called, passing as parameters, item and dict_values
    """

    def start(self, list_controls=None, dict_values=None, caption="", callback=None, item=None, custom_button=None, channelpath=None):
        info()

        # Media Path
        self.mediapath = os.path.join(config.get_runtime_path(), 'resources', 'skins', 'Default', 'media')

        # Params
        self.list_controls = list_controls
        self.values = dict_values
        self.caption = caption
        self.callback = callback
        self.item = item

        if isinstance(custom_button, dict):
            self.custom_button = {}
            self.custom_button["label"] = custom_button.get("label", "")
            self.custom_button["function"] = custom_button.get("function", "")
            self.custom_button["visible"] = bool(custom_button.get("visible", True))
            self.custom_button["close"] = bool(custom_button.get("close", False))
        else:
            self.custom_button = None

        # Load Channel Settings
        if not channelpath:
            channelpath = inspect.currentframe().f_back.f_back.f_code.co_filename
        self.channel = os.path.basename(channelpath).replace(".py", "")
        self.ch_type = os.path.basename(os.path.dirname(channelpath))
        # If list_controls does not exist, it is removed from the channel json
        if not self.list_controls:

            # If the channel path is in the "channels" folder, we get the controls and values using chaneltools
            if os.path.join(config.get_runtime_path(), "channels") in channelpath or os.path.join(config.get_runtime_path(), "specials") in channelpath:

                # The call is made from a channel
                self.list_controls, default_values = channeltools.get_channel_controls_settings(self.channel)
                self.kwargs = {"channel": self.channel}
                self.channelName = channeltools.get_channel_json(self.channel)['name']

            # If the channel path is in the "servers" folder, we get the controls and values through servertools
            elif os.path.join(config.get_runtime_path(), "servers") in channelpath:

                # The call is made from a channel
                self.list_controls, default_values = servertools.get_server_controls_settings(self.channel)
                self.kwargs = {"server": self.channel}
                self.channelName = servertools.get_server_parameters(self.channel)['name']

            # Else Exit
            else:
                return None

        # If dict_values are not passed, create a blank dict
        if self.values is None:
            self.values = {}

        # Make title
        if self.caption == "":
            self.caption = str(config.get_localized_string(30100)) + ' - ' + self.channelName

        matches = match(self.caption, patron=r'@(\d+)').matches
        if matches:
            for m in matches:
                self.caption = self.caption.replace('@' + match, config.get_localized_string(int(m)))

        # Show Window
        self.return_value = None
        self.doModal()
        return self.return_value

    @staticmethod
    def set_enabled(c, val):
        if c["type"] == "list":
            c["control"].setEnabled(val)
            c["label"].setEnabled(val)
        else:
            c["control"].setEnabled(val)

    @staticmethod
    def set_visible(c, val):
        if c["type"] == "list":
            c["control"].setVisible(val)
            c["label"].setVisible(val)
        else:
            c["control"].setVisible(val)

    def evaluate_conditions(self):
        for c in self.list_controls:
            c["active"] = self.evaluate(self.list_controls.index(c), c["enabled"])
            self.set_enabled(c, c["active"])
            c["show"] = self.evaluate(self.list_controls.index(c), c["visible"])
            if not c["show"]:
                self.set_visible(c, c["show"])
        self.visible_controls = [c for c in self.list_controls if c["show"]]

    def evaluate(self, index, cond):
        import re

        ok = False

        # If the condition is True or False, there is nothing else to evaluate, that is the value
        if isinstance(cond, bool):
            return cond

        # Get the conditions
        # dbg()
        conditions = re.compile(r'''(!?eq|!?gt|!?lt)?\s*\(\s*([^, ]+)\s*,\s*["']?([^"'\)]+)["']?\)([+|])?''').findall(cond)
        for operator, id, value, next in conditions:
            matches = match(value, patron=r'@(\d+)').matches
            if matches:
                for m in matches:
                    value = value.replace('@' + m, config.get_localized_string(int(m)))
            try:
                id = int(id)
            except:
                return False

            # The control to evaluate on has to be within range, otherwise it returns False
            if index + id < 0 or index + id >= len(self.list_controls):
                return False

            else:
                # Obtain the value of the control on which it is compared
                c = self.list_controls[index + id]
                if c["type"] == "bool": control_value = bool(c["control"].isSelected())
                if c["type"] == "text": control_value = c["control"].getText()
                if c["type"] == "list": control_value = c["label"].getLabel()
                if c["type"] == "label": control_value = c["control"].getLabel()

            # Operations lt "less than" and gt "greater than" require comparisons to be numbers, otherwise it returns
            # False
            if operator in ["lt", "!lt", "gt", "!gt"]:
                try:
                    value = int(value)
                except ValueError:
                    return False

            # Operation eq "equal to"
            if operator in ["eq", "!eq"]:
                # int
                try:
                    value = int(value)
                except ValueError:
                    pass

                # bool
                if not isinstance(value, int) and value.lower() == "true":
                    value = True
                elif not isinstance(value, int) and value.lower() == "false":
                    value = False

            # Operation eq "equal to"
            if operator == "eq":
                if control_value == value:
                    ok = True
                else:
                    ok = False

            # Operation !eq "not equal to"
            if operator == "!eq":
                if not control_value == value:
                    ok = True
                else:
                    ok = False

            # operation "gt" "greater than"
            if operator == "gt":
                if control_value > value:
                    ok = True
                else:
                    ok = False

            # operation "!gt" "not greater than"
            if operator == "!gt":
                if not control_value > value:
                    ok = True
                else:
                    ok = False

            # operation "lt" "less than"
            if operator == "lt":
                if control_value < value:
                    ok = True
                else:
                    ok = False

            # operation "!lt" "not less than"
            if operator == "!lt":
                if not control_value < value:
                    ok = True
                else:
                    ok = False

            # Next operation, if it is "|" (or) and the result is True, there is no sense to follow, it is True
            if next == "|" and ok is True:
                break
            # Next operation, if it is "+" (and) and the result is False, there is no sense to follow, it is False
            if next == "+" and ok is False:
                break

        return ok


    def add_control_label(self, c):
        control = xbmcgui.ControlLabel(0, -100, self.controls_width + 20, 40, "", alignment=4, font=self.font, textColor=c["color"])

        self.addControl(control)

        control.setVisible(False)
        control.setLabel(c["label"])
        c["control"] = control


    def add_control_list(self, c):
        control = xbmcgui.ControlButton(0, -100, self.controls_width + 10, self.height_control, c["label"],
                                        os.path.join(self.mediapath, 'Controls', 'MenuItemFO.png'),
                                        os.path.join(self.mediapath, 'Controls', 'MenuItemNF.png'),
                                        10, textColor=c["color"], font=self.font)
        label = xbmcgui.ControlLabel(0, -100, self.controls_width, self.height_control,  "", font=self.font, textColor=c["color"], alignment= 1 | 4)

        self.addControl(control)
        self.addControl(label)

        control.setVisible(False)
        label.setVisible(False)
        label.setLabel(c["lvalues"][self.values[c["id"]]])

        c["control"] = control
        c["label"] = label


    def add_control_text(self, c):
        control = xbmcgui.ControlEdit(0, -100, self.controls_width, self.height_control,
                                    c["label"], self.font, c["color"], '', 4,
                                    focusTexture='',
                                    noFocusTexture='')

        image = xbmcgui.ControlImage(0, -100, self.controls_width + 10, self.height_control, os.path.join(self.mediapath, 'Controls', 'MenuItemFO.png'))

        self.addControl(image)
        self.addControl(control)
        image.setVisibleCondition('Control.HasFocus(%s)' % control.getId(), True) 

        control.setVisible(False)
        control.setLabel(c["label"])
        if c['hidden']: control.setType(xbmcgui.INPUT_TYPE_PASSWORD, c["label"])
        # frodo fix
        s = self.values[c["id"]]
        if s is None: s = c['default'] if 'default' in c else ''

        control.setText(s)
        control.setWidth(self.controls_width-10)
        control.setHeight(self.height_control)

        c["control"] = control
        c['image'] = image

    def add_control_bool(self, c):
        # Old versions do not support some textures
        if xbmcgui.__version__ in ["1.2", "2.0"]:
            control = xbmcgui.ControlRadioButton(0, -100, self.controls_width + 20, self.height_control,
                                                 label=c["label"], font=self.font, textColor=c["color"],
                                                 focusTexture=os.path.join(self.mediapath, 'Controls', 'MenuItemFO.png'),
                                                 noFocusTexture=os.path.join(self.mediapath, 'Controls', 'MenuItemNF.png'))
        else:
            control = xbmcgui.ControlRadioButton(0, -100, self.controls_width + 20,
                                                 self.height_control, label=c["label"], font=self.font,
                                                 textColor=c["color"],
                                                 focusTexture=os.path.join(self.mediapath, 'Controls', 'MenuItemFO.png'),
                                                 noFocusTexture=os.path.join(self.mediapath, 'Controls', 'MenuItemNF.png'),
                                                 focusOnTexture=os.path.join(self.mediapath, 'Controls', 'radiobutton-focus.png'),
                                                 noFocusOnTexture=os.path.join(self.mediapath, 'Controls', 'radiobutton-focus.png'),
                                                 focusOffTexture=os.path.join(self.mediapath, 'Controls', 'radiobutton-nofocus.png'),
                                                 noFocusOffTexture=os.path.join(self.mediapath, 'Controls', 'radiobutton-nofocus.png'))
       
        image = xbmcgui.ControlImage(0, -100, self.controls_width + 10, self.height_control, os.path.join(self.mediapath, 'Controls', 'MenuItemFO.png'))
        self.addControl(image)
        self.addControl(control)
        image.setVisibleCondition('Control.HasFocus(%s)' % control.getId(), True) 
        control.setVisible(False)
        control.setRadioDimension(x=self.controls_width - (self.height_control - 5), y=0, width=self.height_control - 5, height=self.height_control - 5)
        control.setSelected(self.values[c["id"]])

        c["control"] = control
        c['image'] = image

    def onInit(self):
        self.getControl(10004).setEnabled(False)
        self.getControl(10005).setEnabled(False)
        self.getControl(10006).setEnabled(False)
        self.ok_enabled = False
        self.default_enabled = False

        # Kodi 18 compatibility
        if config.get_platform(True)['num_version'] < 18:
            if xbmcgui.__version__ == "1.2":
                self.setCoordinateResolution(1)
            else:
                self.setCoordinateResolution(5)

        # Title
        self.getControl(10002).setLabel(self.caption)

        if self.custom_button is not None:
            if self.custom_button['visible']:
                self.getControl(10006).setLabel(self.custom_button['label'])
            else:
                self.getControl(10006).setVisible(False)

        # Control Area Dimensions
        self.controls_width = self.getControl(10007).getWidth() - 30
        self.controls_height = self.getControl(10007).getHeight() -100
        self.controls_pos_x = self.getControl(10007).getPosition()[0] + self.getControl(10001).getPosition()[0] + 10
        self.controls_pos_y = self.getControl(10007).getPosition()[1] + self.getControl(10001).getPosition()[1]
        self.height_control = 60
        self.font = "font16"

        # In old versions: we create 5 controls, from the contrary when clicking the second control,
        # automatically change third party label to "Short By: Name" I don't know why ...
        if xbmcgui.ControlEdit == ControlEdit:
            for x in range(5):
                control = xbmcgui.ControlRadioButton(-500, 0, 0, 0, "")
                self.addControl(control)

        for c in self.list_controls:
            # Skip controls that do not have the appropriate values
            if "type" not in c: continue
            if "label" not in c: continue
            if c["type"] != "label" and "id" not in c: continue
            if c["type"] == "list" and "lvalues" not in c: continue
            if c["type"] == "list" and not isinstance(c["lvalues"], list): continue
            if c["type"] == "list" and not len(c["lvalues"]) > 0: continue
            if c["type"] != "label" and len([control.get("id") for control in self.list_controls if c["id"] == control.get("id")]) > 1: continue

            # Translation label and lvalues
            if c['label'].startswith('@') and unicode(c['label'][1:]).isnumeric(): c['label'] = config.get_localized_string(int(c['label'][1:]))
            if c['type'] == 'list':
                lvalues = []
                for li in c['lvalues']:
                    if li.startswith('@') and unicode(li[1:]).isnumeric(): lvalues.append(config.get_localized_string(int(li[1:])))
                    else: lvalues.append(li)
                c['lvalues'] = lvalues

            # Default values in case the control does not have them
            if c["type"] == "bool": default = False
            elif c["type"] == "list": default = 0
            else: default = "" # label or text

            c["default"] = c.get("default", default)
            c["color"] = c.get("color", "0xFFFFFFFF")
            c["visible"] = c.get("visible", True)
            c["enabled"] = c.get("enabled", True)

            if c["type"] == "label" and "id" not in c: c["id"] = None
            if c["type"] == "text": c["hidden"] = c.get("hidden", False)

            # Decide whether to use the default value or the saved value
            if c["type"] in ["bool", "text", "list"]:
                if c["id"] not in self.values:
                    if not self.callback: self.values[c["id"]] = config.get_setting(c["id"], **self.kwargs)
                    else: self.values[c["id"]] = c["default"]

            if c["type"] == "bool": self.add_control_bool(c)
            elif c["type"] == 'text': self.add_control_text(c)
            elif c["type"] == 'list': self.add_control_list(c)
            elif c["type"] == 'label': self.add_control_label(c)
        self.list_controls = [c for c in self.list_controls if "control" in c]

        self.evaluate_conditions()
        self.index = -1
        self.dispose_controls(0)
        self.getControl(100010).setVisible(False)
        self.getControl(10004).setEnabled(True)
        self.getControl(10005).setEnabled(True)
        self.getControl(10006).setEnabled(True)
        self.ok_enabled = True
        self.default_enabled = True
        self.check_default()
        self.check_ok(self.values)

    def dispose_controls(self, index, focus=False, force=False):
        show_controls = old_div(self.controls_height, self.height_control) - 1

        visible_count = 0

        if focus:
            if not index >= self.index or not index <= self.index + show_controls:
                if index < self.index: new_index = index
                else: new_index = index - show_controls
            else:new_index = self.index
        else:
            if index + show_controls >= len(self.visible_controls): index = len(self.visible_controls) - show_controls - 1
            if index < 0: index = 0
            new_index = index

        if self.index != new_index or force:
            for x, c in enumerate(self.visible_controls):
                if x < new_index or visible_count > show_controls or not c["show"]:
                    self.set_visible(c, False)
                else:
                    c["y"] = self.controls_pos_y + visible_count * self.height_control
                    visible_count += 1

                    if c["type"] == "list":
                        c["control"].setPosition(self.controls_pos_x, c["y"])
                        if xbmcgui.__version__ == "1.2": c["label"].setPosition(self.controls_pos_x + self.controls_width - 30, c["y"])
                        else: c["label"].setPosition(self.controls_pos_x, c["y"])

                    else:
                        if c["type"] == "bool": c["control"].setPosition(self.controls_pos_x, c["y"])
                        elif c['type'] == 'text': c["control"].setPosition(self.controls_pos_x +10, c["y"])
                        else: c["control"].setPosition(self.controls_pos_x, c["y"])
                        if c['type'] in ['bool', 'text']:c['image'].setPosition(self.controls_pos_x, c["y"])

                    self.set_visible(c, True)

            # Calculate the position and size of the ScrollBar
            hidden_controls = len(self.visible_controls) - show_controls - 1
            if hidden_controls < 0: hidden_controls = 0

            scrollbar_height = self.getControl(10008).getHeight() - (hidden_controls * 3)
            scrollbar_y = self.getControl(10008).getPosition()[1] + (new_index * 3)
            self.getControl(10009).setPosition(self.getControl(10008).getPosition()[0], scrollbar_y)
            self.getControl(10009).setHeight(scrollbar_height)

        self.index = new_index

        if focus:
            self.setFocus(self.visible_controls[index]["control"])

    def check_ok(self, dict_values=None):
        if not self.callback:
            if dict_values:
                self.init_values = dict_values.copy()
                self.getControl(10004).setEnabled(False)
                self.ok_enabled = False

            else:
                if self.init_values == self.values:
                    self.getControl(10004).setEnabled(False)
                    self.ok_enabled = False
                else:
                    self.getControl(10004).setEnabled(True)
                    self.ok_enabled = True

    def check_default(self):
        if self.custom_button is None:
            def_values = dict([[c["id"], c.get("default")] for c in self.list_controls if not c["type"] == "label"])

            if def_values == self.values:
                self.getControl(10006).setEnabled(False)
                self.default_enabled = False
            else:
                self.getControl(10006).setEnabled(True)
                self.default_enabled = True

    def onClick(self, id):
        # Default values
        if id == 10006:
            if self.custom_button is not None:
                if self.custom_button["close"]:
                    self.close()

                if '.' in self.callback: package, self.callback = self.callback.rsplit('.', 1)
                else: package = '%s.%s' % (self.ch_type, self.channel)

                try: cb_channel = __import__(package, None, None, [package])
                except ImportError: logger.error('Imposible importar %s' % package)
                else:
                    self.return_value = getattr(cb_channel, self.custom_button['function'])(self.item, self.values)
                    if not self.custom_button["close"]:
                        if isinstance(self.return_value, dict) and "label" in self.return_value: self.getControl(10006).setLabel(self.return_value['label'])

                        for c in self.list_controls:
                            if c["type"] == "text": c["control"].setText(self.values[c["id"]])
                            if c["type"] == "bool": c["control"].setSelected(self.values[c["id"]])
                            if c["type"] == "list": c["label"].setLabel(c["lvalues"][self.values[c["id"]]])

                        self.evaluate_conditions()
                        self.dispose_controls(self.index, force=True)

            else:
                for c in self.list_controls:
                    if c["type"] == "text":
                        c["control"].setText(c["default"])
                        self.values[c["id"]] = c["default"]
                    if c["type"] == "bool":
                        c["control"].setSelected(c["default"])
                        self.values[c["id"]] = c["default"]
                    if c["type"] == "list":
                        c["label"].setLabel(c["lvalues"][c["default"]])
                        self.values[c["id"]] = c["default"]

                self.evaluate_conditions()
                self.dispose_controls(self.index, force=True)
                self.check_default()
                self.check_ok()

        # Cancel button [X]
        if id == 10003 or id == 10005:
            self.close()

        # OK button
        if id == 10004:
            self.close()
            if self.callback and '.' in self.callback: package, self.callback = self.callback.rsplit('.', 1)
            else: package = '%s.%s' % (self.ch_type, self.channel)

            cb_channel = None

            try: cb_channel = __import__(package, None, None, [package])
            except ImportError:logger.error('Impossible to import %s' % package)

            if self.callback:
                # If there is a callback function we invoke it...
                self.return_value = getattr(cb_channel, self.callback)(self.item, self.values)
            else:
                # if not, we test if there is a 'cb_validate_config' function in the channel...
                try:
                    self.return_value = getattr(cb_channel, 'cb_validate_config')(self.item, self.values)
                except AttributeError:
                    # if 'cb_validate_config' doesn't exist either ...
                    for v in self.values:
                        config.set_setting(v, self.values[v], **self.kwargs)

        # Adjustment controls, if the value of an adjustment is changed, we change the value saved in the value dictionary
        # Get the control that has been clicked
        # control = self.getControl(id)

        # We look it up in the list of controls
        for cont in self.list_controls:

            if cont['type'] == "list" and cont["control"].getId() == id:
                select = platformtools.dialog_select(config.get_localized_string(30041), cont["lvalues"], self.values[cont["id"]])
                if select >= 0:
                    cont["label"].setLabel(cont["lvalues"][select])
                    self.values[cont["id"]] = select

            # If the control is a "bool", we save the new value True / False
            if cont["type"] == "bool" and cont["control"].getId() == id: self.values[cont["id"]] = bool(cont["control"].isSelected())

            # If the control is a "text", we save the new value
            if cont["type"] == "text" and cont["control"].getId() == id:
                # Older versions require opening the keyboard manually
                if xbmcgui.ControlEdit == ControlEdit:
                    keyboard = xbmc.Keyboard(cont["control"].getText(), cont["control"].getLabel(), cont["control"].isPassword)
                    keyboard.setHiddenInput(cont["control"].isPassword)
                    keyboard.doModal()
                    if keyboard.isConfirmed(): cont["control"].setText(keyboard.getText())

                self.values[cont["id"]] = cont["control"].getText()

        self.evaluate_conditions()
        self.dispose_controls(self.index, force=True)
        self.check_default()
        self.check_ok()

    # Older versions require this feature
    def onFocus(self, a):
        pass

    def onAction(self, raw_action):
        # Get Focus
        focus = self.getFocusId()

        action = raw_action.getId()
        # On Left
        if action == 1:
            # if Focus is on close button
            if focus == 10003:
                self.dispose_controls(0, True)
                self.setFocusId(3001)

            # if focus is on List
            else:
                if self.ok_enabled:
                    self.setFocusId(10004)
                else:
                    self.setFocusId(10005)

        # On Right
        elif action == 2:
            # if Focus is on button
            if focus in [10004, 10005, 10006]:
                self.dispose_controls(0, True)
                self.setFocusId(3001)

            # if focus is on List
            else:
                self.setFocusId(10003)

        # On Down
        elif action == 4:
            # if focus is on List
            if focus not in [10004, 10005, 10006]:
                try:
                    focus_control = [self.visible_controls.index(c) for c in self.visible_controls if c["control"].getId() == self.getFocus().getId()][0]
                    focus_control += 1

                except:
                    focus_control = 0

                while not focus_control == len(self.visible_controls) and (self.visible_controls[focus_control]["type"] == "label" or not self.visible_controls[focus_control]["active"]):
                    focus_control += 1

                if focus_control >= len(self.visible_controls):
                    focus_control = 0
                    self.setFocusId(3001)

                self.dispose_controls(focus_control, True)

            # Else navigate on main buttons
            elif focus in [10004]:
                self.setFocusId(10005)
            elif focus in [10005]:
                if self.default_enabled: self.setFocusId(10006)
                elif self.ok_enabled: self.setFocusId(10004)
            elif focus in [10006]:
                if self.ok_enabled: self.setFocusId(10004)
                else: self.setFocusId(10005)

        # On Up
        elif action == 3:
            # if focus is on List
            if focus not in [10003, 10004, 10005, 10006]:
                try:
                    focus_control = \
                        [self.visible_controls.index(c) for c in self.visible_controls if c["control"].getId() == self.getFocus().getId()][0]
                    focus_control -= 1

                    while not focus_control == -1 and (self.visible_controls[focus_control]["type"] == "label" or not
                    self.visible_controls[focus_control]["active"]):
                        focus_control -= 1

                    if focus_control < 0: 
                        focus_control = len(self.visible_controls) - 1

                except:
                    focus_control = 0

                self.dispose_controls(focus_control, True)

            # Else navigate on main buttons
            elif focus in [10004]:
                if self.default_enabled: self.setFocusId(10006)
                else: self.setFocusId(10005)
            elif focus in [10005]:
                if self.ok_enabled: self.setFocusId(10004)
                elif self.default_enabled: self.setFocusId(10006)
            elif focus in [10006]:
                self.setFocusId(10005)



        # Accion 104: Scroll Down
        elif action == 104:
            self.dispose_controls(self.index - 1)

        # Accion 105: Scroll Up
        elif action == 105:
            self.dispose_controls(self.index + 1)

        # ACTION_PREVIOUS_MENU 10
        # ACTION_NAV_BACK 92
        elif action in [10, 92]:
            self.close()

        elif action == 501:
            self.xx = int(raw_action.getAmount2())

        elif action == 504:

            if self.xx > raw_action.getAmount2():
                if old_div((self.xx - int(raw_action.getAmount2())), self.height_control):
                    self.xx -= self.height_control
                    self.dispose_controls(self.index + 1)
            else:
                if old_div((int(raw_action.getAmount2()) - self.xx), self.height_control):
                    self.xx += self.height_control
                self.dispose_controls(self.index - 1)
            return



class ControlEdit(xbmcgui.ControlButton):
    def __new__(cls, *args, **kwargs):
        del kwargs["isPassword"]
        del kwargs["window"]
        args = list(args)
        return xbmcgui.ControlButton.__new__(cls, *args, **kwargs)

    def __init__(self, *args, **kwargs):
        self.isPassword = kwargs["isPassword"]
        self.window = kwargs["window"]
        self.label = ""
        self.text = ""
        self.textControl = xbmcgui.ControlLabel(self.getX(), self.getY(), self.getWidth(), self.getHeight(), self.text,
                                                font=kwargs["font"], textColor=kwargs["textColor"], alignment= 4 | 1)
        self.window.addControl(self.textControl)

    def setLabel(self, val):
        self.label = val
        xbmcgui.ControlButton.setLabel(self, val)

    def getX(self):
        return xbmcgui.ControlButton.getPosition(self)[0]

    def getY(self):
        return xbmcgui.ControlButton.getPosition(self)[1]

    def setEnabled(self, e):
        xbmcgui.ControlButton.setEnabled(self, e)
        self.textControl.setEnabled(e)

    def setWidth(self, w):
        xbmcgui.ControlButton.setWidth(self, w)
        self.textControl.setWidth(old_div(w, 2))

    def setHeight(self, w):
        xbmcgui.ControlButton.setHeight(self, w)
        self.textControl.setHeight(w)

    def setPosition(self, x, y):
        xbmcgui.ControlButton.setPosition(self, x, y)
        if xbmcgui.__version__ == "1.2":
            self.textControl.setPosition(x + self.getWidth(), y)
        else:
            self.textControl.setPosition(x + old_div(self.getWidth(), 2), y)

    def setText(self, text):
        self.text = text
        if self.isPassword:
            self.textControl.setLabel("*" * len(self.text))
        else:
            self.textControl.setLabel(self.text)

    def getText(self):
        return self.text


if not hasattr(xbmcgui, "ControlEdit"):
    xbmcgui.ControlEdit = ControlEdit
