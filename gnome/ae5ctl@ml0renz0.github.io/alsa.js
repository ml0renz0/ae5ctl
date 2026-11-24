import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {cards, selectCard, controlNumbers, decodeEnum, state, identical} from './alsa-logic.mjs';

Gio._promisify(Gio.File.prototype, 'load_contents_async');
Gio._promisify(Gio.Subprocess.prototype, 'communicate_utf8_async');

export class Ae5Alsa {
    constructor() {
        this._cancel = new Gio.Cancellable();
        this._children = new Set();
        this._cached = null;
        this._disposed = false;
    }

    async _cards() {
        const file = Gio.File.new_for_path('/proc/asound/cards');
        const [, data] = await file.load_contents_async(this._cancel);
        return selectCard(cards(new TextDecoder().decode(data)));
    }

    async _exec(card, ...args) {
        if (this._disposed)
            throw new Error('Extensión deshabilitada');
        const argv = ['amixer', '-c', String(card.index), ...args];
        const proc = new Gio.Subprocess({
            argv,
            flags: Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE,
        });
        proc.init(this._cancel);
        this._children.add(proc);
        const timeout = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 4, () => {
            proc.force_exit();
            return GLib.SOURCE_REMOVE;
        });
        try {
            const [stdout, stderr] = await proc.communicate_utf8_async(null, null);
            if (!proc.get_successful())
                throw new Error('amixer: ' + (stderr || 'Error ALSA').slice(0, 160));
            if (stdout.length > 262144)
                throw new Error('Respuesta ALSA demasiado grande');
            return stdout;
        } finally {
            GLib.Source.remove(timeout);
            this._children.delete(proc);
        }
    }

    async _read(card, numid) {
        return decodeEnum(await this._exec(card, 'cget', 'numid=' + numid), numid);
    }

    async status() {
        const card = await this._cards();
        let control = null;
        if (this._cached && this._cached.card.index === card.index &&
            this._cached.card.id === card.id && this._cached.card.name === card.name) {
            try {
                control = await this._read(card, this._cached.numid);
                if (!control || !structureEquals(control, this._cached.control))
                    throw new Error('La identidad del selector ha cambiado');
            } catch (error) {
                this._cached = null;
                throw error;
            }
        } else {
            this._cached = null;
            const numbers = controlNumbers(await this._exec(card, 'controls'));
            const possible = [];
            for (const numid of numbers) {
                const candidate = await this._read(card, numid);
                if (candidate && state(candidate))
                    possible.push(candidate);
                if (possible.length > 1)
                    break;
            }
            if (possible.length !== 1)
                throw new Error(possible.length ? 'Selector ALSA ambiguo' : 'Sin selector AE-5 válido');
            control = possible[0];
            this._cached = {card, numid: control.numid, control};
        }
        const output = state(control);
        if (!output)
            throw new Error('Estado físico no reconocido');
        return {card, control, ...output};
    }

    async switchOutput(target) {
        if (!['speakers', 'headphones'].includes(target))
            throw new Error('Destino inválido');
        const before = await this.status();
        if (before.output === target)
            return before;
        const currentCard = await this._cards();
        if (!sameCard(currentCard, before.card))
            throw new Error('La tarjeta cambió antes de escribir');
        const verify = await this._read(currentCard, before.control.numid);
        if (!identical(before.control, verify))
            throw new Error('Otro cliente ha modificado el selector ALSA');
        await this._exec(currentCard, 'cset', 'numid=' + verify.numid, String(before.targets[target]));
        if (!sameCard(await this._cards(), before.card))
            throw new Error('La identidad de tarjeta cambió; estado incierto');
        const after = await this._read(currentCard, verify.numid);
        if (!after || !structureEquals(after, verify) || state(after)?.output !== target)
            throw new Error('No se ha confirmado el cambio ALSA');
        return {card: currentCard, control: after, ...state(after)};
    }

    destroy() {
        this._disposed = true;
        this._cancel.cancel();
        for (const child of this._children)
            child.force_exit();
        this._children.clear();
        this._cached = null;
    }
}

function sameCard(a, b) {
    return a.index === b.index && a.id === b.id && a.name === b.name;
}

function structureEquals(a, b) {
    return a.numid === b.numid && a.name === b.name && a.items.size === b.items.size &&
        [...a.items].every(([index,label]) => b.items.get(index) === label);
}
