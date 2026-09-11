import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search, Sparkles } from "lucide-react";

import {
  deleteSopDocument,
  getMostAskedSop,
  listSopDocuments,
  MostAskedEntry,
  SopDocument,
  uploadSopDocument,
  uploadSopDocumentFromUrl,
} from "../../api/sop";
import { useAuth } from "../../auth/AuthContext";
import { Badge } from "../../components/Badge";
import { EmptyState } from "../../components/EmptyState";
import { FormSection } from "../_shared/FormSection";
import { QuickField } from "../_shared/QuickLogForm";
import { Skeleton } from "../../components/Loading";
import { ModuleIcon, PageHeader } from "../../components/PageHeader";
import { RowActions } from "../../components/RowActions";
import { Table, TBody, Td, Th, THead, Tr } from "../../components/Table";

export default function SopPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const navigate = useNavigate();

  const [documents, setDocuments] = useState<SopDocument[] | null>(null);
  const [mostAsked, setMostAsked] = useState<MostAskedEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [uploadMode, setUploadMode] = useState<"file" | "url">("file");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [docName, setDocName] = useState("");
  const [docNameTouched, setDocNameTouched] = useState(false);
  const [tags, setTags] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  // Switching File <-> URL should start the form fresh, not carry over a
  // document name/tags picked for the other source — same "clears when you
  // switch away and back" expectation as the Shift Schedules manual form.
  function handleModeChange(mode: "file" | "url") {
    setUploadMode(mode);
    setFile(null);
    setUrl("");
    setDocName("");
    setDocNameTouched(false);
    setTags("");
  }

  function refresh() {
    listSopDocuments()
      .then(setDocuments)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load documents"));
    getMostAskedSop().then(setMostAsked).catch(() => undefined);
  }

  useEffect(refresh, []);

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    setUploading(true);
    setUploadError(null);
    try {
      if (uploadMode === "file") {
        if (!file) return;
        await uploadSopDocument(file, docName.trim(), tags);
        setFile(null);
      } else {
        if (!url.trim()) return;
        await uploadSopDocumentFromUrl(url.trim(), docName.trim(), tags);
        setUrl("");
      }
      setTags("");
      setDocName("");
      setDocNameTouched(false);
      refresh();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  function stripExtension(filename: string): string {
    const idx = filename.lastIndexOf(".");
    return idx > 0 ? filename.slice(0, idx) : filename;
  }

  async function handleDelete(id: number) {
    if (!confirm("Remove this SOP document? It will no longer be searchable.")) return;
    await deleteSopDocument(id);
    refresh();
  }

  const [nameFilter, setNameFilter] = useState("");

  // Matches on the document's name, not its tags — tags are optional, so a
  // document uploaded without any would otherwise be unfindable by any
  // search at all once one was typed.
  const filteredDocuments = documents
    ? nameFilter
      ? documents.filter((d) => d.name.toLowerCase().includes(nameFilter.toLowerCase()))
      : documents
    : [];

  return (
    <div style={{ maxWidth: 1000 }}>
      <PageHeader
        icon={<ModuleIcon name="sop" />}
        title="SOP Library"
        subtitle="Upload, organize, and search your standard operating procedures"
        actions={
          documents && documents.length > 0 ? (
            <button className="btn-outline-accent" onClick={() => navigate("/chat")}>
              <Sparkles size={15} strokeWidth={2} />
              Ask the AI
            </button>
          ) : undefined
        }
      />

      {!error && documents === null && <Skeleton rows={2} />}
      {error && <EmptyState title="Couldn't load documents" message={error} />}
      {!error && documents && documents.length === 0 && (
        <div className="surface" style={{ padding: 16, marginBottom: 12 }}>
          <EmptyState title="No documents yet" message="Upload an SOP document below to start building the library." />
        </div>
      )}
      {documents && documents.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ marginBottom: 12, display: "flex", gap: 8, alignItems: "center", justifyContent: "flex-end" }}>
            {nameFilter && (
              <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
                <span className="num">{filteredDocuments.length}</span> of <span className="num">{documents.length}</span> documents
              </span>
            )}
            <div style={{ position: "relative", maxWidth: 220, width: "100%" }}>
              <Search
                size={14}
                strokeWidth={2}
                style={{ position: "absolute", top: "50%", left: 12, transform: "translateY(-50%)", color: "var(--color-text-tertiary)", pointerEvents: "none" }}
              />
              <input
                className="input"
                value={nameFilter}
                onChange={(e) => setNameFilter(e.target.value)}
                placeholder="Search by name"
                style={{ width: "100%", paddingLeft: 34 }}
              />
            </div>
          </div>
          <Table>
            <THead>
              <Tr>
                <Th>Name</Th>
                <Th numeric align="center">Version</Th>
                <Th align="center">Status</Th>
                <Th>Tags</Th>
                <Th align="center">Last updated</Th>
                {isAdmin && <Th align="right">Actions</Th>}
              </Tr>
            </THead>
            <TBody>
              {filteredDocuments.length === 0 ? (
                <Tr>
                  <td colSpan={isAdmin ? 6 : 5} style={{ textAlign: "center", padding: "24px 16px", color: "var(--color-text-tertiary)" }}>
                    No documents found.
                  </td>
                </Tr>
              ) : (
                filteredDocuments.map((d) => (
                  <Tr key={d.id}>
                    <Td wrap>
                      <span style={{ fontWeight: 600 }}>{d.name}</span>
                    </Td>
                    <Td numeric align="center">v{d.version}</Td>
                    <Td align="center">
                      {d.chunk_count > 0 ? (
                        <Badge variant="ok">Indexed</Badge>
                      ) : (
                        <Badge variant="warning">Indexing</Badge>
                      )}
                    </Td>
                    <Td wrap>
                      <span style={{ display: "inline-block", paddingRight: 24 }}>{d.tags.join(", ")}</span>
                    </Td>
                    <Td align="center">{new Date(d.uploaded_at).toLocaleString()}</Td>
                    {isAdmin && (
                      <Td align="right">
                        <RowActions onDelete={() => handleDelete(d.id)} deleteLabel="Remove" />
                      </Td>
                    )}
                  </Tr>
                ))
              )}
            </TBody>
          </Table>
        </div>
      )}

      {isAdmin && (
        <FormSection
          title="Upload document"
          subtitle="Add an SOP, manual, or safety procedure so the chatbot can answer with citations."
          collapsible
          defaultOpen={false}
        >
          {/* Same tab row as ConfigImportTabs' Manual Entry / File Upload /
              Database Import switch (seg-btn), not the merged seg-toggle
              control, so this reads as the same "pick a source" pattern
              used everywhere else in the app. */}
          <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
            {(["file", "url"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => handleModeChange(mode)}
                className={uploadMode === mode ? "seg-btn seg-btn--active" : "seg-btn"}
              >
                {mode === "file" ? "File" : "URL"}
              </button>
            ))}
          </div>
          <form onSubmit={handleUpload}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {uploadMode === "file" ? (
                <label
                  className="btn-secondary"
                  style={{
                    flex: "1 1 260px",
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: file ? undefined : "var(--color-text-tertiary)",
                  }}
                >
                  {file ? file.name : "Choose file (PDF, DOCX, TXT, MD)"}
                  <input
                    type="file"
                    accept=".pdf,.docx,.txt,.md"
                    style={{ display: "none" }}
                    onChange={(e) => {
                      const chosen = e.target.files?.[0] ?? null;
                      setFile(chosen);
                      // Pre-fill from the filename, but only until the user
                      // edits it themselves — re-uploading a file whose name
                      // differs from the file it's meant to supersede (e.g.
                      // "SOP-MAINT-014-v2.pdf" replacing "SOP-MAINT-014.pdf")
                      // needs an editable name so it still matches the
                      // existing document instead of silently creating a
                      // second, unrelated one.
                      if (chosen && !docNameTouched) setDocName(stripExtension(chosen.name));
                    }}
                  />
                </label>
              ) : (
                <QuickField label="URL" style={{ flex: "1 1 260px" }}>
                  <input
                    className="input"
                    type="url"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="URL (e.g. https://example.com/sop.pdf)"
                  />
                </QuickField>
              )}
              <QuickField label="Document name" style={{ flex: "1 1 260px" }}>
                <input
                  className="input"
                  value={docName}
                  onChange={(e) => {
                    setDocName(e.target.value);
                    setDocNameTouched(true);
                  }}
                  placeholder="Document name"
                />
              </QuickField>
              <QuickField label="Tags" style={{ flex: "1 1 260px" }}>
                <input
                  className="input"
                  value={tags}
                  onChange={(e) => setTags(e.target.value)}
                  placeholder="Tags (e.g. maintenance, safety)"
                />
              </QuickField>
            </div>
            <p style={{ margin: "8px 0 0", fontSize: 11.5, color: "var(--color-text-tertiary)" }}>
              Uploading with the name of an existing document replaces it with a new version.
            </p>
            <div style={{ marginTop: 10, display: "flex", justifyContent: "flex-end" }}>
              <button type="submit" className="btn-primary" disabled={(uploadMode === "file" ? !file : !url.trim()) || uploading}>
                {uploading ? "Uploading..." : "Upload"}
              </button>
            </div>
          </form>
          {uploadError && <p style={{ color: "var(--color-error-600)", fontSize: 13, marginTop: 8 }}>{uploadError}</p>}
        </FormSection>
      )}

      {mostAsked.length > 0 && (
        <div className="surface" style={{ padding: 16, marginBottom: 12 }}>
          <h3 style={{ marginTop: 0, marginBottom: 8, fontSize: 15 }}>Most-asked procedures</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {mostAsked.map((m, i) => (
              <div key={m.document_name} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0", borderBottom: i < mostAsked.length - 1 ? "1px solid var(--color-border-subtle)" : "none" }}>
                <span
                  className="num"
                  style={{
                    width: 20,
                    height: 20,
                    borderRadius: 6,
                    background: "var(--color-neutral-100)",
                    color: "var(--color-text-tertiary)",
                    fontSize: 11,
                    fontWeight: 800,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flex: "none",
                  }}
                >
                  {i + 1}
                </span>
                <span style={{ fontSize: 13, fontWeight: 600, flex: 1 }}>{m.document_name}</span>
                <span className="num" style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{m.query_count} question{m.query_count !== 1 ? "s" : ""}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
