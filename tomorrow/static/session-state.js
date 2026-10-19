// The construction page's only HTTP boundary. Presentation code consumes the
// browser Response objects without owning request construction or JSON encoding.
export const state = {
  current: null,
  templateDraft: null,
  templateInitial: null,
  templateMode: false,
  templateDirty: false,
  sheetOpen: false,
  sheetKind: null,
  armedFlexId: null,
  latestSuggestRequest: 0
};

export function request(path, { method = "GET", body } = {}) {
  const options = { method };
  if (body !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = typeof body === "string" ? body : JSON.stringify(body);
  }
  return fetch(path, options);
}

export async function fetchActivitySuggestion(name) {
  if (!name) return null;
  const response = await request("/api/suggest-activity", {
    method: "POST",
    body: { name }
  });
  if (!response.ok) throw new Error("suggest-activity failed: " + response.status);
  return (await response.json()).suggestion;
}
