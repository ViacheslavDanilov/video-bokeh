"use client";

import { useEffect, useState } from "react";
import { Controls } from "@/components/controls";
import { Viewer } from "@/components/viewer";
import type { LibraryInfo, Sequence, SequenceParams } from "@/lib/api";
import {
  ApiError,
  createSequence,
  estimatorName,
  fetchLibraries,
} from "@/lib/api";

const DEFAULTS: SequenceParams = {
  // Filled with the first library once the list arrives.
  library: "",
  seed: 0,
  frames: 80,
  size: 512,
  n_objects_min: 4,
  n_objects_max: 5,
};

export default function Page() {
  const [libraries, setLibraries] = useState<LibraryInfo[]>([]);
  const [params, setParams] = useState<SequenceParams>(DEFAULTS);
  const [sequence, setSequence] = useState<Sequence | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchLibraries(controller.signal)
      .then((found) => {
        setLibraries(found);
        setParams((p) => ({
          ...p,
          library: p.library || (found[0]?.id ?? ""),
        }));
      })
      .catch((cause) => {
        if (cause instanceof DOMException && cause.name === "AbortError")
          return;
        setError(cause instanceof ApiError ? cause.message : String(cause));
      });
    return () => controller.abort();
  }, []);

  const byId = (id?: string) => libraries.find((lib) => lib.id === id) ?? null;
  const library = byId(params.library);
  // Looked up from the sequence rather than the picker, which may have moved on since.
  const shown = byId(sequence?.library);

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      setSequence(await createSequence(params));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-full flex-1 flex-col">
      <header className="border-border flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b px-6 py-4">
        <h1 className="text-lg font-medium tracking-tight">Video Bokeh</h1>
        {library ? (
          <p className="text-muted-foreground flex flex-wrap items-baseline gap-x-4 text-xs">
            <span>
              library{" "}
              <span className="text-foreground font-mono">{library.id}</span>
            </span>
            <span>{estimatorName(library)}</span>
            <span>
              {library.n_foregrounds} objects, {library.n_backgrounds}{" "}
              backgrounds
            </span>
            {library.asset_size && <span>{library.asset_size} px assets</span>}
          </p>
        ) : (
          <p className="text-muted-foreground text-xs">
            {error ? "no library" : "reading the libraries"}
          </p>
        )}
      </header>

      <main className="flex flex-1 flex-col gap-6 p-6 lg:flex-row">
        <aside className="lg:border-border w-full shrink-0 lg:w-64 lg:border-r lg:pr-6">
          <Controls
            libraries={libraries}
            params={params}
            onChange={setParams}
            onGenerate={generate}
            busy={busy}
            disabled={!library}
          />
        </aside>

        <section className="flex min-w-0 flex-1 flex-col gap-4">
          {error && (
            <p
              role="alert"
              className="border-destructive bg-destructive/8 text-foreground rounded-lg border-l-2 px-4 py-3 text-sm"
            >
              {error}
            </p>
          )}
          <Viewer
            sequence={sequence}
            estimator={estimatorName(shown)}
            generating={busy}
          />
        </section>
      </main>

      <footer className="text-muted-foreground border-border border-t px-6 py-3 text-xs">
        These are the model&rsquo;s inputs. Bokeh rendering runs on a GPU in its
        own container and is not wired up yet.
      </footer>
    </div>
  );
}
