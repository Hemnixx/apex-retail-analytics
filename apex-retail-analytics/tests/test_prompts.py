from __future__ import annotations


PROMPT_LOG = [
    {
        "prompt": "Suggest a detection and tracking stack for retail CCTV with occlusion and speed constraints.",
        "decision": "Use YOLOv8 for detection and ByteTrack for tracking because the combination balances accuracy and throughput.",
    },
    {
        "prompt": "How should staff and customer sessions be separated in CCTV footage?",
        "decision": "Use zone and session heuristics plus an explicit staff flag so the API can filter staff events without hiding them.",
    },
    {
        "prompt": "What framework and validation strategy should the API use?",
        "decision": "Use FastAPI with Pydantic models so malformed event payloads fail validation before hitting the analytics layer.",
    },
    {
        "prompt": "How should the solution stay production-ready for the hackathon gate?",
        "decision": "Keep the API containerized, add tests, and ensure the detector can fall back to a dry run instead of crashing.",
    },
]


def test_prompt_log_is_present() -> None:
    assert len(PROMPT_LOG) >= 4
    assert all("prompt" in item and "decision" in item for item in PROMPT_LOG)
