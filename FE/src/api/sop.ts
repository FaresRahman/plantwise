import { apiRequest, BASE_URL, getToken } from "./client";

export interface SopDocument {
  id: number;
  name: string;
  version: number;
  source_type: string;
  tags: string[];
  chunk_count: number;
  uploaded_at: string;
}

export interface MostAskedEntry {
  document_name: string;
  query_count: number;
}

export function listSopDocuments() {
  return apiRequest<SopDocument[]>("/sop/documents");
}

export function getMostAskedSop(limit = 5) {
  return apiRequest<MostAskedEntry[]>(`/sop/most-asked?limit=${limit}`);
}

async function postDocumentForm(form: FormData): Promise<SopDocument> {
  const token = getToken();
  let res: Response;
  try {
    res = await fetch(`${BASE_URL}/sop/documents`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      body: form,
    });
  } catch {
    // fetch() throws a browser-internal error ("Failed to fetch", ...) when
    // no HTTP response is ever received (server down, CORS rejection,
    // offline) — not something a plant operator should see verbatim.
    throw new Error("Can't reach the server right now. Check your connection and try again.");
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? res.statusText);
  }
  return res.json();
}

export function uploadSopDocument(file: File, name: string, tags: string): Promise<SopDocument> {
  const form = new FormData();
  form.append("file", file);
  if (name) form.append("name", name);
  form.append("tags", tags);
  return postDocumentForm(form);
}

/** BRD §4.4: document upload is "PDF/DOCX; optional URL" — fetches and
 * indexes a document by URL instead of a local file upload. */
export function uploadSopDocumentFromUrl(url: string, name: string, tags: string): Promise<SopDocument> {
  const form = new FormData();
  form.append("url", url);
  if (name) form.append("name", name);
  form.append("tags", tags);
  return postDocumentForm(form);
}

export function deleteSopDocument(id: number) {
  return apiRequest<void>(`/sop/documents/${id}`, { method: "DELETE" });
}
