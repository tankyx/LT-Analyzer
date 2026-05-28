import {
  buildTrackTrie,
  searchTrackTrie,
  tokenize,
} from '@/app/components/RaceDashboard/lib/trackTrie';

const tracks = [
  { track_id: 1, track_name: 'Karting Mariembourg' },
  { track_id: 2, track_name: 'Spa-Francorchamps Karting' },
  { track_id: 184, track_name: 'Buckmore Park' },
  { track_id: 25, track_name: 'Whilton Mill' },
  { track_id: 186, track_name: 'Teesside Karting Autodrome' },
  { track_id: 185, track_name: 'Rye House Karting' },
  { track_id: 212, track_name: 'Ardennes Karting' },
  { track_id: 192, track_name: 'Borough 19 (London)' },
  { track_id: 211, track_name: 'Norway Motorsport Park' },
];

describe('tokenize', () => {
  test('lowercases and splits on whitespace + punctuation', () => {
    expect(tokenize('Spa-Francorchamps Karting')).toEqual([
      'spa',
      'francorchamps',
      'karting',
    ]);
    expect(tokenize('Borough 19 (London)')).toEqual(['borough', '19', 'london']);
    expect(tokenize('   ')).toEqual([]);
  });
});

describe('searchTrackTrie', () => {
  const root = buildTrackTrie(tracks);

  test('empty query returns null (no filter)', () => {
    expect(searchTrackTrie(root, '')).toBeNull();
    expect(searchTrackTrie(root, '   ')).toBeNull();
  });

  test('prefix match finds tracks whose first token starts with the query', () => {
    const ids = searchTrackTrie(root, 'buc');
    expect(ids && Array.from(ids)).toEqual([184]); // Buckmore
  });

  test('matches any token of a multi-word track name', () => {
    // "kart" hits the second token "Karting" in Mariembourg / Spa / Teesside /
    // Rye / Ardennes; should NOT include Buckmore/Whilton/Borough/Norway.
    const ids = searchTrackTrie(root, 'kart');
    expect(ids).toEqual(new Set([1, 2, 186, 185, 212]));
  });

  test('case-insensitive', () => {
    expect(searchTrackTrie(root, 'KART')).toEqual(searchTrackTrie(root, 'kart'));
    expect(searchTrackTrie(root, 'Whi')).toEqual(searchTrackTrie(root, 'whi'));
  });

  test('handles tokenized punctuation in track names', () => {
    // Spa-Francorchamps Karting -> "spa", "francorchamps", "karting"
    expect(searchTrackTrie(root, 'fran')).toEqual(new Set([2]));
    // Borough 19 (London) -> "borough", "19", "london"
    expect(searchTrackTrie(root, 'lond')).toEqual(new Set([192]));
  });

  test('multi-token query intersects matches (every word must hit)', () => {
    // "park" matches Buckmore Park (184) + Norway Motorsport Park (211).
    // "norway" matches only Norway Motorsport Park (211).
    // Intersection: just 211.
    const ids = searchTrackTrie(root, 'park norway');
    expect(ids).toEqual(new Set([211]));
  });

  test('no match returns empty set, not null', () => {
    const ids = searchTrackTrie(root, 'xyz123');
    expect(ids).toEqual(new Set());
    expect(ids).not.toBeNull();
  });

  test('partial multi-token where one token mismatches returns empty', () => {
    // "kart" matches many; "zzz" matches none → intersection empty.
    expect(searchTrackTrie(root, 'kart zzz')).toEqual(new Set());
  });

  test('extra_tokens are searchable alongside the name (provider filter)', () => {
    const tagged = [
      { track_id: 1, track_name: 'Karting Mariembourg', extra_tokens: ['apex'] },
      { track_id: 184, track_name: 'Buckmore Park', extra_tokens: ['alphahub'] },
      { track_id: 25, track_name: 'Whilton Mill', extra_tokens: ['alphahub'] },
      { track_id: 212, track_name: 'Ardennes Karting', extra_tokens: ['apex'] },
    ];
    const t = buildTrackTrie(tagged);
    // "alpha" -> only AlphaHub tracks
    expect(searchTrackTrie(t, 'alpha')).toEqual(new Set([184, 25]));
    // "apex" -> only Apex tracks
    expect(searchTrackTrie(t, 'apex')).toEqual(new Set([1, 212]));
    // Multi-token still intersects across name + extra_tokens.
    // "kart alpha" -> Buckmore? No, Buckmore has no "kart" token. Should be empty.
    expect(searchTrackTrie(t, 'kart alpha')).toEqual(new Set());
    // "kart apex" -> Karting Mariembourg + Ardennes Karting.
    expect(searchTrackTrie(t, 'kart apex')).toEqual(new Set([1, 212]));
  });

  test('scales to a large roster (smoke test)', () => {
    const big = Array.from({ length: 500 }, (_, i) => ({
      track_id: i,
      track_name: `Venue ${i} ${i % 3 === 0 ? 'Karting' : 'Raceway'}`,
    }));
    const t = buildTrackTrie(big);
    const ids = searchTrackTrie(t, 'kart');
    expect(ids).not.toBeNull();
    // Every 3rd entry has "Karting" in the name.
    expect(ids!.size).toBe(Math.ceil(500 / 3));
  });
});
