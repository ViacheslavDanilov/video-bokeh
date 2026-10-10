"use client";

import { useEffect, useRef, useState } from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { Controls } from "@/components/controls";
import { Button } from "@/components/ui/button";
import { Viewer } from "@/components/viewer";
import type { LibraryInfo, Sequence, SequenceParams } from "@/lib/api";
import {
  ApiError,
  createSequence,
  fetchLibraries,
  libraryLabel,
} from "@/lib/api";
import { useStoredFlag } from "@/lib/stored-flag";
import { cn } from "@/lib/utils";

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
  // Apart, so a list read that works again clears its own error and not a Generate's.
  const [error, setError] = useState<string | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  // The list as last read, for the effect's handler, which outlives any one render.
  const librariesRef = useRef<LibraryInfo[]>([]);
  // Folded away, the parameters leave their width to the panes.
  const [parametersShown, setParametersShown] = useStoredFlag(
    "video-bokeh.parameters-shown",
    true,
  );

  useEffect(() => {
    let controller = new AbortController();
    const load = () => {
      controller.abort();
      controller = new AbortController();
      fetchLibraries(controller.signal)
        .then((found) => {
          const before = librariesRef.current;
          librariesRef.current = found;
          setLibraries(found);
          setListError(null);
          // The selection follows its library: by id while it is mounted, by directory
          // once it is rebuilt there under a new id, else the first.
          setParams((p) => {
            const name = before.find((lib) => lib.id === p.library)?.name;
            const kept =
              found.find((lib) => lib.id === p.library) ??
              found.find((lib) => lib.name === name);
            return { ...p, library: (kept ?? found[0])?.id ?? "" };
          });
        })
        .catch((cause) => {
          if (cause instanceof DOMException && cause.name === "AbortError")
            return;
          setListError(
            cause instanceof ApiError ? cause.message : String(cause),
          );
        });
    };
    load();
    // A library built while the page is open, by make libraries or the lab script, shows
    // in the picker when the person comes back to the page.
    window.addEventListener("focus", load);
    return () => {
      window.removeEventListener("focus", load);
      controller.abort();
    };
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
        <div className="flex items-center gap-2">
          {/* Only where the parameters sit beside the panes: stacked above them on a
              narrow screen, folding them away would give the panes nothing. */}
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label="Parameters"
            aria-expanded={parametersShown}
            aria-controls="parameters"
            title={parametersShown ? "Hide parameters" : "Show parameters"}
            className="text-muted-foreground -ml-1.5 self-center max-lg:hidden"
            onClick={() => setParametersShown(!parametersShown)}
          >
            {parametersShown ? <PanelLeftClose /> : <PanelLeftOpen />}
          </Button>
          <h1 className="text-lg font-medium tracking-tight">Video Bokeh</h1>
        </div>
        {library ? (
          <p className="text-muted-foreground flex flex-wrap items-baseline gap-x-4 text-xs">
            <span>
              library{" "}
              <span className="text-foreground font-mono">{library.id}</span>
            </span>
            <span>{libraryLabel(library)}</span>
            <span>
              {library.n_foregrounds} objects, {library.n_backgrounds}{" "}
              backgrounds
            </span>
            {library.asset_size && <span>{library.asset_size} px assets</span>}
          </p>
        ) : (
          <p className="text-muted-foreground text-xs">
            {listError ? "no library" : "reading the libraries"}
          </p>
        )}
      </header>

      <main className="flex flex-1 flex-col gap-6 p-6 lg:flex-row">
        <aside
          id="parameters"
          className={cn(
            "lg:border-border w-full shrink-0 lg:w-64 lg:border-r lg:pr-6",
            !parametersShown && "lg:hidden",
          )}
        >
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
          {(
            [
              ["list", listError],
              ["generate", error],
            ] as const
          ).map(
            ([key, message]) =>
              message && (
                <p
                  key={key}
                  role="alert"
                  className="border-destructive bg-destructive/8 text-foreground rounded-lg border-l-2 px-4 py-3 text-sm"
                >
                  {message}
                </p>
              ),
          )}
          <Viewer
            sequence={sequence}
            library={libraryLabel(shown)}
            generating={busy}
          />
        </section>
      </main>

      <footer className="text-muted-foreground border-border border-t px-6 py-3 text-xs">
        Bokeh comes with each sequence, rendered by the layered renderer, when
        the API runs with torch installed.
      </footer>
    </div>
  );
}
