from fastapi import FastAPI

app = FastAPI(
    title="Video Bokeh",
    description="Depth-aware synthetic bokeh pipeline for video, with a FastAPI backend and Next.js frontend.",
    version="0.1.0",
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}
