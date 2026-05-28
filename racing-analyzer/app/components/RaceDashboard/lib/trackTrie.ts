/**
 * Trie (prefix tree) for fast incremental search across the track list.
 *
 * The track roster has crossed 80+ entries (Apex + AlphaHub combined) and grows
 * whenever the discovery cron picks up a new venue, so a linear .filter() over
 * each keystroke gets noisy. The trie is built once per tracks-array change
 * and answers a query in O(query_length) per token, regardless of roster size.
 *
 * Design choices:
 *   - Each track_name is **tokenized** on whitespace + common punctuation, and
 *     every token is inserted as a separate prefix path. So "Rye House Karting"
 *     responds to "rye", "hou", and "kart" alike — what the user expects when
 *     typing a recognizable word fragment.
 *   - Every node carries the *set of track_ids* whose tokens pass through it,
 *     so a prefix walk yields the answer directly (no traversal of subtree).
 *   - **Multi-token queries** ("kart paris" → both "kart" AND "paris" must
 *     match the same track) are handled by intersecting per-token id sets.
 *   - Empty query returns null → caller treats as "no filter" (show all).
 *
 * Case-insensitive by design — tokens and queries are lowercased before walk.
 */

export interface IndexedTrack {
  track_id: number;
  track_name: string;
}

type TrieNode = {
  children: Map<string, TrieNode>;
  ids: Set<number>;
};

const newNode = (): TrieNode => ({ children: new Map(), ids: new Set() });

const TOKEN_SPLIT_RE = /[\s\-(),./_]+/;

export const tokenize = (s: string): string[] =>
  s
    .toLowerCase()
    .split(TOKEN_SPLIT_RE)
    .filter(Boolean);

export const buildTrackTrie = (tracks: IndexedTrack[]): TrieNode => {
  const root = newNode();
  for (const t of tracks) {
    for (const token of tokenize(t.track_name)) {
      let node = root;
      for (const ch of token) {
        let child = node.children.get(ch);
        if (!child) {
          child = newNode();
          node.children.set(ch, child);
        }
        node = child;
        node.ids.add(t.track_id);
      }
    }
  }
  return root;
};

/**
 * Walk the trie with `prefix` and return the set of track_ids whose names
 * contain a token starting with that prefix. An empty walk returns an empty set.
 */
const matchPrefix = (root: TrieNode, prefix: string): Set<number> => {
  let node: TrieNode | undefined = root;
  for (const ch of prefix) {
    node = node.children.get(ch);
    if (!node) return new Set();
  }
  return node.ids;
};

/**
 * Search the trie for tracks matching `query`. Multi-token queries are
 * intersected (every token must hit at least one of the track's name tokens).
 *
 * Returns `null` for an empty query so the caller can skip filtering — that
 * matters because an empty Set would render an empty list, which we don't want.
 */
export const searchTrackTrie = (
  root: TrieNode,
  query: string,
): Set<number> | null => {
  const tokens = tokenize(query);
  if (tokens.length === 0) return null;
  let acc: Set<number> | null = null;
  for (const tok of tokens) {
    const hits = matchPrefix(root, tok);
    if (acc === null) {
      acc = hits;
    } else {
      // Intersect — every token must match the same track.
      const prev: Set<number> = acc;
      const intersect = new Set<number>();
      prev.forEach((id) => { if (hits.has(id)) intersect.add(id); });
      acc = intersect;
    }
    if (acc.size === 0) return acc;
  }
  return acc;
};
