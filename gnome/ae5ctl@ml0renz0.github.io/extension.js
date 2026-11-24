import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as QuickSettings from 'resource:///org/gnome/shell/ui/quickSettings.js';

import {Ae5Alsa} from './alsa.js';

const Ae5Toggle = GObject.registerClass(
class Ae5Toggle extends QuickSettings.QuickMenuToggle {
    constructor(callbacks) {
        super({
            title: 'ae5ctl',
            subtitle: 'Buscando AE-5…',
            iconName: 'audio-card-symbolic',
            toggleMode: false,
        });
        this.menu.setHeader('audio-card-symbolic', 'ae5ctl', 'Salida física ALSA');
        this._status = new PopupMenu.PopupMenuItem('Leyendo tarjeta…', {reactive: false});
        this.menu.addMenuItem(this._status);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._phones = this.menu.addAction('Auriculares', () => callbacks.switch('headphones'));
        this._speakers = this.menu.addAction('Altavoces', () => callbacks.switch('speakers'));
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this.menu.addAction('Actualizar estado', () => callbacks.refresh());
        this.connect('clicked', () => this.menu.open());
        this.menu.connect('open-state-changed', (_menu, opened) => {
            if (opened)
                callbacks.refresh();
        });
        this.unavailable('Esperando respuesta ALSA');
    }

    busy() {
        this.subtitle = 'Cambiando salida…';
        this._status.label.text = 'Verificando selector físico…';
        this._phones.setSensitive(false);
        this._speakers.setSensitive(false);
    }

    show(info) {
        const headphones = info.output === 'headphones';
        this.subtitle = headphones ? 'Auriculares' : 'Altavoces';
        this.iconName = headphones ? 'audio-headphones-symbolic' : 'audio-speakers-symbolic';
        this._status.label.text = info.card.name + ' · ' + info.control.name;
        this._phones.label.text = (headphones ? '✓ ' : '') + 'Auriculares';
        this._speakers.label.text = (!headphones ? '✓ ' : '') + 'Altavoces';
        this._phones.setSensitive(!headphones);
        this._speakers.setSensitive(headphones);
    }

    unavailable(reason) {
        this.subtitle = 'AE-5 no disponible';
        this.iconName = 'audio-card-symbolic';
        this._status.label.text = String(reason).slice(0, 150);
        this._phones.setSensitive(false);
        this._speakers.setSensitive(false);
    }
});

const Ae5Indicator = GObject.registerClass(
class Ae5Indicator extends QuickSettings.SystemIndicator {
    constructor(callbacks) {
        super();
        this._icon = this._addIndicator();
        this._icon.icon_name = 'audio-card-symbolic';
        this.toggle = new Ae5Toggle(callbacks);
        this.quickSettingsItems.push(this.toggle);
    }

    destroy() {
        this.quickSettingsItems.forEach(item => item.destroy());
        super.destroy();
    }
});

export default class Ae5Extension extends Extension {
    enable() {
        this._active = true;
        this._busy = false;
        this._backend = new Ae5Alsa();
        this._indicator = new Ae5Indicator({
            refresh: () => { void this._refresh(); },
            switch: target => { void this._switch(target); },
        });
        Main.panel.statusArea.quickSettings.addExternalIndicator(this._indicator);
        void this._refresh();
        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 10, () => {
            void this._refresh();
            return GLib.SOURCE_CONTINUE;
        });
    }

    async _refresh() {
        if (!this._active || this._busy)
            return;
        this._busy = true;
        try {
            const result = await this._backend.status();
            if (this._active)
                this._indicator.toggle.show(result);
        } catch (error) {
            if (this._active)
                this._indicator.toggle.unavailable(error.message);
        } finally {
            this._busy = false;
        }
    }

    async _switch(output) {
        if (!this._active || this._busy)
            return;
        this._busy = true;
        this._indicator.toggle.busy();
        try {
            const result = await this._backend.switchOutput(output);
            if (this._active)
                this._indicator.toggle.show(result);
        } catch (error) {
            if (this._active) {
                this._indicator.toggle.unavailable(error.message);
                Main.notify('ae5ctl', 'Cambio físico no confirmado: ' + error.message);
            }
        } finally {
            this._busy = false;
        }
        if (this._active)
            void this._refresh();
    }

    disable() {
        this._active = false;
        if (this._timer)
            GLib.Source.remove(this._timer);
        this._timer = 0;
        this._backend?.destroy();
        this._backend = null;
        this._indicator?.destroy();
        this._indicator = null;
    }
}
