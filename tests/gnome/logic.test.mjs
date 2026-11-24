import assert from 'node:assert/strict';
import test from 'node:test';

import {cards, selectCard, controlNumbers, decodeEnum, state, identical} from '../../gnome/ae5ctl@ml0renz0.github.io/alsa-logic.mjs';

const listing = ' 0 [PCH]: Intel - Audio\n 7 [Creative]: HDA - Sound Blaster AE-5';
const before = "numid=37,iface=MIXER,name='Output Select'\n" +
    '  ; type=ENUMERATED,access=rw------,values=1,items=2\n' +
    "  ; Item #0 'Headphone'\n  ; Item #1 'Speakers'\n  : values=0";

test('detects physical AE-5 card uniquely', () => {
    assert.equal(selectCard(cards(listing)).id, 'Creative');
    assert.throws(() => selectCard(cards(listing + '\n 8 [AE5]: HDA - AE-5')), /ambiguas/);
});

test('discovers ALSA numids and rejects duplicates', () => {
    assert.deepEqual(controlNumbers("numid=12,iface=MIXER,name='A'\nnumid=37,iface=MIXER,name='B'"), [12, 37]);
    assert.throws(() => controlNumbers("numid=1,iface=MIXER,name='A'\nnumid=1,iface=MIXER,name='B'"));
});

test('parses exact enumerated options, not hardcoded position', () => {
    const control = decodeEnum(before, 37);
    assert.equal(state(control).output, 'headphones');
    assert.equal(state(control).targets.speakers, 1);
    assert.equal(state(decodeEnum(before.replace(': values=0', ': values=1'), 37)).output, 'speakers');
});

test('rejects stale metadata and malformed ALSA values', () => {
    const control = decodeEnum(before, 37);
    assert.equal(identical(control, decodeEnum(before.replace('Headphone', 'Stereo'), 37)), false);
    assert.throws(() => decodeEnum(before, 38));
    assert.throws(() => decodeEnum(before.replace(': values=0', ': values=9'), 37));
    assert.throws(() => decodeEnum(before.replace("  ; Item #1 'Speakers'\n", ''), 37));
});

test('rejects enumerations unrelated to physical AE-5 selection', () => {
    const other = before.replace('Headphone', 'Digital');
    assert.equal(state(decodeEnum(other, 37)), null);
});
