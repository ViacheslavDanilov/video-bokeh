"use client";

import { useEffect, useState } from "react";
import { Controls } from "@/components/controls";
import { Viewer } from "@/components/viewer";
import type { LibraryInfo, Scene, SceneParams } from "@/lib/api";
import { ApiError, createScene, fetchLibrary } from "@/lib/api";

const DEFAULTS: SceneParams = {
  seed: 0,
  frames: 80,
  size: 512,
  n_objects_min: 4,
  n_objects_max: 5,
};

export default function Page() {
  const [library, setLibrary] = useState<LibraryInfo | null>(null);
  const [params, setParams] = useState<SceneParams>(DEFAULTS);
  const [scene, setScene] = useState<Scene | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchLibrary(controller.signal)
      .then(setLibrary)
      .catch((cause) => {
        if (cause instanceof DOMException && cause.name === "AbortError")
          return;
        setError(cause instanceof ApiError ? cause.message : String(cause));
      });
    return () => controller.abort();
  }, []);

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      setScene(await createScene(params));
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
            <span>{library.depth_model ?? "unknown model"}</span>
            <span>
              {library.n_foregrounds} objects, {library.n_backgrounds}{" "}
              backgrounds
            </span>
            {library.asset_size && <span>{library.asset_size} px assets</span>}
          </p>
        ) : (
          <p className="text-muted-foreground text-xs">
            {error ? "no library" : "reading the library"}
          </p>
        )}
      </header>

      <main className="flex flex-1 flex-col gap-6 p-6 lg:flex-row">
        <aside className="lg:border-border w-full shrink-0 lg:w-64 lg:border-r lg:pr-6">
          <Controls
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
          <Viewer scene={scene} generating={busy} />
        </section>
      </main>

      <footer className="text-muted-foreground border-border border-t px-6 py-3 text-xs">
        These are the model&rsquo;s inputs. Bokeh rendering runs on a GPU in its
        own container and is not wired up yet.
      </footer>
    </div>
  );
}
