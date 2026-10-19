"""MPIB's ray-tracing kernel, edited to composite each ray in gamma values.

MPIB's kernel (``kernel_Render_updateOutput`` in ``bokeh_generator.py``) sends rays from
aperture samples through the layers, nearest first. Each ray composites the layers it meets,
and the kernel adds every ray's premultiplied color and coverage into one sum per pixel, divided
once at the end. Both the composite and the average happen in the space the colors arrive in,
which the adapter makes linear light.

``per_ray_kernel`` keeps each ray's composite apart instead: the ray composites the layers in
the colors' own space, its straight color is raised to ``power``, and the rays are averaged as
before, each weighted by its coverage. Given gamma values and the power 2.2, a ray composites
as Stage B and our renderer do, and the rays still average in linear light. Given linear colors
and the power 1, it is MPIB's kernel with its sums taken in another order. Plain text editing,
so it runs without the ray tracer's CUDA stack.
"""

from __future__ import annotations

#: Each edit: a line of MPIB's kernel, which must appear once, and what replaces it.
_EDITS = (
    (
        "float alpha_prev = 1;",
        "float alpha_prev = 1;\n"
        "                float rayR = 0, rayG = 0, rayB = 0, rayNum = 0;",
    ),
    ("sumR += f * alpha_prev;", "rayR += f * alpha_prev;"),
    ("sumG += f * alpha_prev;", "rayG += f * alpha_prev;"),
    ("sumB += f * alpha_prev;", "rayB += f * alpha_prev;"),
    ("num += alpha_curr * alpha_prev;", "rayNum += alpha_curr * alpha_prev;"),
)
#: The end of the layer loop, then of the sample loop, where a ray is closed.
_TAIL = """                    }
                }
            }
            bokeh[OFFSET_4(bokeh, b, 0, y, x)] = sumR / num;"""


def per_ray_kernel(kernel: str, power: float) -> str:
    """MPIB's kernel source with each ray's color raised to ``power`` before the average."""
    for old, new in _EDITS:
        if kernel.count(old) != 1:
            raise ValueError(f"MPIB's kernel does not hold {old!r} once")
        kernel = kernel.replace(old, new)
    if kernel.count(_TAIL) != 1:
        raise ValueError("MPIB's kernel does not end its loops as expected")
    close = f"""                    }}
                }}
                if (rayNum > 0) {{
                    sumR += powf(fmaxf(rayR / rayNum, 0.0f), {power:.6f}f) * rayNum;
                    sumG += powf(fmaxf(rayG / rayNum, 0.0f), {power:.6f}f) * rayNum;
                    sumB += powf(fmaxf(rayB / rayNum, 0.0f), {power:.6f}f) * rayNum;
                    num += rayNum;
                }}
            }}
            bokeh[OFFSET_4(bokeh, b, 0, y, x)] = sumR / num;"""
    return kernel.replace(_TAIL, close)
