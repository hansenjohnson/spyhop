// Resights: later sightings of animals already recorded. A sighting whose ResightOf holds another
// sighting's SightNo is a resight of it; chains are followed to the first sighting (the original).
// A ResightOf naming no sighting leaves the row counted as a sighting of its own.
// The same rules are in spyhop/resights.py.

const key = (v) => {
  const s = String(v ?? '').trim().replace(/^#/, '');
  const f = Number(s);
  return s !== '' && Number.isFinite(f) && f === Math.trunc(f) ? String(f) : s;
};

export class Resights {
  constructor(rows) {
    this.rows = rows || [];
    this.bySightNo = new Map();
    for (const r of this.rows) { const k = key(r.SightNo); if (k && !this.bySightNo.has(k)) this.bySightNo.set(k, r); }
    this.orig = new Map();
    for (const r of this.rows) this.orig.set(r.RowID, this.originalOf(r));
  }

  originalOf(r) {
    const seen = new Set([r]);
    let cur = r;
    for (;;) {
      const ref = key(cur.ResightOf);
      const nxt = ref ? this.bySightNo.get(ref) : null;
      if (!nxt || seen.has(nxt)) return cur;
      seen.add(nxt);
      cur = nxt;
    }
  }

  original(r) { return this.orig.get(r.RowID) || r; }
  isResight(r) { return this.original(r) !== r; }
  primaries() { return this.rows.filter((r) => !this.isResight(r)); }

  // the original's group: itself, then its resights in time order
  group(r) {
    const o = this.original(r);
    const res = this.rows.filter((x) => x !== o && this.original(x) === o)
      .sort((a, b) => new Date(a.DateTime) - new Date(b.DateTime));
    return [o, ...res];
  }

  groups() { return this.primaries().map((o) => this.group(o)); }

  // the table's rows with each sighting's resights straight after it (time order within a group)
  nested() {
    const out = [];
    for (const o of this.primaries()) out.push(...this.group(o));
    return out;
  }
}

// Summary figures for one group: the largest number and calves seen on the sighting or any resight (counts usually
// get better on approach), and every FieldID used.
export function groupCounts(group) {
  const max = (k) => Math.max(0, ...group.map((r) => +r[k] || 0));
  const ids = [...new Set(group.map((r) => r.FieldID).filter(Boolean))];
  return { number: max('Count'), calves: max('Calves'), fieldIds: ids, resights: group.length - 1 };
}
