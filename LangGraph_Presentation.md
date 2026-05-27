# LangGraph — Research Presentation
### Project: Chalchitra | Presented by: Ayush

---

## 1. What is LangGraph?

LangGraph is an open-source Python library built by the **LangChain team**.

It is used to build **AI-powered pipelines as graphs** — where:
- Each **node** = one step (transcribe, detect clips, render, etc.)
- Each **edge** = the connection between steps (what runs next)
- The **state** = shared data that flows through the whole pipeline

> Simple analogy: Think of a flowchart where every box is a task and every arrow is a decision. LangGraph makes that flowchart run as real code.

**GitHub:** https://github.com/langchain-ai/langgraph  
**Docs:** https://langchain-ai.github.io/langgraph/

---

## 2. The Problem with Our Current Pipeline

Our project **Chalchitra** processes podcast/video files through 5 steps:

```
Upload → Transcribe → Enrich → Detect Clips → FFmpeg Cut → Render
```

### Current Issues:

| Problem | Impact |
|---|---|
| Steps run one after another (linear) | Slow — enrich and detect could run together |
| One crash = restart from Step 1 | Wastes time and compute |
| No retry logic | If transcription fails once, whole job fails |
| No way to pause for human review | Cannot add "approve clips before render" feature |
| Adding a new step = editing one big function | Hard to maintain as project grows |

**File with this problem:** `gateway/app/services/pipeline.py`

---

## 3. How LangGraph Fixes This

### 3.1 — Checkpointing (Resume After Crash)

LangGraph saves the pipeline state after every node. If the render step crashes, next run **starts from render**, not from transcription.

```python
from langgraph.checkpoint.memory import MemorySaver

checkpointer = MemorySaver()
app = graph.compile(checkpointer=checkpointer)
```

---

### 3.2 — Parallel Execution

In our pipeline, **Enrich** and **Detect** are independent — both only need the transcript. LangGraph can run them at the same time.

```
transcribe
    |
  ──┴──
  |   |
enrich detect   ← run in parallel (saves ~30-60 seconds)
  |   |
  ──┬──
    |
  ffmpeg
    |
  render
```

---

### 3.3 — Conditional Edges (Smart Routing)

Instead of crashing silently, the graph can route to a retry or error handler:

```python
def should_retry(state):
    if state["error"]:
        return "handle_error"
    return "next_step"

graph.add_conditional_edges("transcribe", should_retry, {
    "handle_error": "error_node",
    "next_step": "enrich"
})
```

---

### 3.4 — Human-in-the-Loop

LangGraph supports **pausing** the pipeline and waiting for a human to approve before continuing.

Use case for Chalchitra:
> "Detect 3 clips → Show to user → User picks the best one → Render only that clip"

```python
graph.add_node("human_review", human_review_node)
graph.compile(interrupt_before=["render"])  # pause before render
```

---

## 4. Current Pipeline vs LangGraph Pipeline

### Current Code (pipeline.py — simplified):

```python
async def run_pipeline(episode_id, file_path):
    # Step 1
    result = await transcribe(episode_id, file_path)
    
    # Step 2
    result = await enrich(episode_id, transcript)
    
    # Step 3
    result = await detect(episode_id, transcript)
    
    # Step 4
    result = await ffmpeg(episode_id, clips)
    
    # Step 5
    result = await render(episode_id, clips)
```

**Problem:** Linear, no recovery, no parallelism.

---

### LangGraph Version:

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict

# 1. Define the shared state
class PipelineState(TypedDict):
    episode_id: str
    file_path:  str
    transcript: str
    clips:      list
    error:      str | None

# 2. Each step becomes a node function
async def transcribe_node(state: PipelineState):
    result = await call_transcription_service(state["episode_id"], state["file_path"])
    return {"transcript": result["text"]}

async def enrich_node(state: PipelineState):
    result = await call_enrich_service(state["episode_id"], state["transcript"])
    return {"metadata": result}

async def detect_node(state: PipelineState):
    result = await call_detect_service(state["episode_id"], state["transcript"])
    return {"clips": result["clips"]}

# 3. Build the graph
graph = StateGraph(PipelineState)

graph.add_node("transcribe", transcribe_node)
graph.add_node("enrich",     enrich_node)
graph.add_node("detect",     detect_node)
graph.add_node("ffmpeg",     ffmpeg_node)
graph.add_node("render",     render_node)

# 4. Connect the steps
graph.set_entry_point("transcribe")
graph.add_edge("transcribe", "enrich")
graph.add_edge("transcribe", "detect")   # parallel with enrich
graph.add_edge("enrich",     "ffmpeg")
graph.add_edge("detect",     "ffmpeg")
graph.add_edge("ffmpeg",     "render")
graph.add_edge("render",     END)

# 5. Compile with checkpointing
app = graph.compile(checkpointer=MemorySaver())
```

---

## 5. Architecture Diagram

```
                    ┌─────────────┐
                    │   UPLOAD    │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  TRANSCRIBE │  ← Whisper (speech to text)
                    └──────┬──────┘
                           │
              ┌────────────┴────────────┐
              │                         │
       ┌──────▼──────┐           ┌──────▼──────┐
       │    ENRICH   │           │    DETECT   │  ← Run in PARALLEL
       │  (LLM: title│           │ (LLM: find  │
       │  show notes)│           │  best clips)│
       └──────┬──────┘           └──────┬──────┘
              │                         │
              └────────────┬────────────┘
                           │
                    ┌──────▼──────┐
                    │    FFMPEG   │  ← Cut video clips
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │    RENDER   │  ← Add captions, branding
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │    DONE     │
                    └─────────────┘
```

---

## 6. Why This Matters for Chalchitra

| Feature | Without LangGraph | With LangGraph |
|---|---|---|
| Pipeline crash recovery | Restart from Step 1 | Resume from where it crashed |
| Enrich + Detect | Run one after another | Run at the same time |
| Error handling | Silent fail | Route to retry or error node |
| Human clip review | Not possible | Built-in interrupt support |
| Adding new steps | Edit one big function | Add a node + edge |
| Observability | Manual logs | LangSmith dashboard (built-in tracing) |

---

## 7. Installation

```bash
pip install langgraph langchain-core
```

Optional — for observability/tracing:
```bash
pip install langsmith
```

---

## 8. Plan of Action

1. **Phase 1** — Convert `pipeline.py` to a LangGraph `StateGraph`
2. **Phase 2** — Add checkpointing so pipeline can resume after crash
3. **Phase 3** — Make `enrich` and `detect` nodes run in parallel
4. **Phase 4** — Add human-in-the-loop clip approval before render
5. **Phase 5** — Connect LangSmith for visual pipeline monitoring

---

## 9. References

- LangGraph Docs: https://langchain-ai.github.io/langgraph/
- LangGraph GitHub: https://github.com/langchain-ai/langgraph
- LangSmith (Tracing): https://smith.langchain.com/
- Our Pipeline File: `gateway/app/services/pipeline.py`

---

*Researched and prepared by Ayush — May 2026*
