// Pure ALSA state handling shared with the GNOME test suite.
export class AlsaStateError extends Error {}

export function cards(text) {
    const found = [];
    for (const line of text.split(/\r?\n/)) {
        if (!line.trim() || line.trim() === '--- no soundcards ---')
            continue;
        const match = /^\s*(\d+)\s+\[([^\]]+)\]\s*:\s*(.+)$/.exec(line);
        if (match) {
            const index = Number(match[1]);
            if (found.some(card => card.index === index))
                throw new AlsaStateError('Tarjeta ALSA duplicada');
            found.push({index, id: match[2].trim(), name: match[3].trim()});
        } else if (/^\s/.test(line) && found.length) {
            found[found.length - 1].name += ' ' + line.trim();
        } else {
            throw new AlsaStateError('Listado ALSA inválido');
        }
    }
    return found;
}

export function selectCard(list) {
    const matched = list.filter(card => /(?<![a-z0-9])ae[- ]?5(?![a-z0-9])/i.test(card.id + ' ' + card.name));
    if (matched.length !== 1)
        throw new AlsaStateError(matched.length ? 'Tarjetas AE-5 ambiguas' : 'No se detecta la AE-5');
    return matched[0];
}

export function controlNumbers(text) {
    const numbers = new Set();
    for (const line of text.split(/\r?\n/)) {
        if (!line.trim())
            continue;
        const match = /^\s*numid=(\d+),.*name='.*'/.exec(line);
        if (!match || Number(match[1]) < 1 || numbers.has(Number(match[1])) || numbers.size >= 512)
            throw new AlsaStateError('Controles ALSA inválidos');
        numbers.add(Number(match[1]));
    }
    return [...numbers];
}

export function decodeEnum(text, expectedId) {
    const lines = text.split(/\r?\n/).filter(line => line.trim());
    const head = /^\s*numid=(\d+),.*name='(.*)'(?:,|$)/.exec(lines[0] || '');
    if (!head || Number(head[1]) !== expectedId)
        throw new AlsaStateError('ALSA devolvió otro control');
    const attrs = lines.slice(1).filter(line => /\btype=/.test(line));
    if (attrs.length !== 1)
        throw new AlsaStateError('Metadatos ALSA inválidos');
    const type = /\btype=([A-Z0-9_]+)/.exec(attrs[0])?.[1];
    if (type !== 'ENUMERATED')
        return null;
    const count = Number(/\bitems=(\d+)/.exec(attrs[0])?.[1]);
    const valueCount = Number(/\bvalues=(\d+)/.exec(attrs[0])?.[1]);
    if (!Number.isInteger(count) || count < 2 || count > 64 || valueCount !== 1)
        throw new AlsaStateError('Enumerado inválido');
    const items = new Map();
    let current = null;
    for (const line of lines.slice(1)) {
        const item = /^\s*;\s*Item #(\d+) '(.*)'\s*$/.exec(line);
        const value = /^\s*:\s*values=(\d+)\s*$/.exec(line);
        if (item) {
            const index = Number(item[1]);
            if (index >= count || items.has(index))
                throw new AlsaStateError('Enumerado duplicado');
            items.set(index, item[2]);
        } else if (value) {
            if (current !== null)
                throw new AlsaStateError('Valores duplicados');
            current = Number(value[1]);
        } else if (line.includes('Item #') || /:\s*values=/.test(line)) {
            throw new AlsaStateError('Enumerado corrupto');
        }
    }
    if (items.size !== count || !items.has(current))
        throw new AlsaStateError('Enumerado incompleto');
    return {numid: expectedId, name: head[2], items, current};
}

function output(label) {
    if (/^headphones?$/i.test(label || ''))
        return 'headphones';
    if (/^speakers?$/i.test(label || ''))
        return 'speakers';
    return null;
}

export function state(control) {
    if (!control)
        return null;
    const headphones = [...control.items].filter(([,label]) => output(label) === 'headphones');
    const speakers = [...control.items].filter(([,label]) => output(label) === 'speakers');
    if (headphones.length !== 1 || speakers.length !== 1)
        return null;
    const active = output(control.items.get(control.current));
    if (!active)
        throw new AlsaStateError('Salida física desconocida');
    return {output: active, targets: {headphones: headphones[0][0], speakers: speakers[0][0]}};
}

export function identical(a, b) {
    return a && b && a.numid === b.numid && a.name === b.name &&
        a.current === b.current && a.items.size === b.items.size &&
        [...a.items].every(([index, label]) => b.items.get(index) === label);
}
