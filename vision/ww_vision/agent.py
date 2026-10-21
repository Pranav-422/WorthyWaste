"""The pickup agent: perception -> decision -> action, with every step written to the trace.

Perception is the OpenCV pipeline. The decision compares what the camera saw with what the collector
marked, and picks one action:

  recapture       the photo cannot be judged (bad input, blurry, dark, unsure); ask for a retake
  accept          the camera agrees with the collector, or the collector marked the safer "mixed"
  needs_approval  the collector said "separated" but the camera is sure it is mixed. Points and a fraud
                  flag are real consequences, so a person decides; nothing happens until they do
  accept_unverified  the vision service failed, or retakes ran out: record what the collector marked,
                  hold the points, and say so on the pickup

The risky action (holding a household's points and flagging a collector) is never taken by the agent
alone: it only proposes it, and a human approves or rejects it.
"""
import time

MAX_ATTEMPTS = 3          # the third photo that still cannot be judged goes to a person instead
MIN_CONFIDENCE = 0.55     # below this the camera's verdict is not used
DISAGREE_CONFIDENCE = 0.70  # a disagreement only goes to a person when the camera is this sure


def _step(trace: list, kind: str, title: str, **detail) -> None:
    trace.append({"t": round(time.time(), 3), "kind": kind, "title": title, **detail})


def decide(result: dict | None, *, marked: str | None, attempt: int, error: str | None = None) -> dict:
    """`result` is pipeline.analyze() without its images; `marked` is what the collector tapped."""
    trace: list[dict] = []
    if error is not None or result is None:
        _step(trace, "perception", "Vision failed", error=error or "no result")
        _step(trace, "decision", "Fall back: record what the collector marked, hold points for review")
        return _done(trace, "accept_unverified", "Vision is unavailable; recorded as marked, points held")

    _step(trace, "perception", "Photo analysed", status=result["status"], verdict=result.get("verdict"),
          confidence=result.get("confidence"), quality=result.get("quality"),
          faces_blurred=result.get("faces_blurred", 0), heaps=len(result.get("heaps") or []),
          latency_ms=result.get("timings_ms", {}).get("total"))
    if result.get("faces_blurred"):
        _step(trace, "action", f"Blurred {result['faces_blurred']} face(s) before storing the photo")

    problem = None
    if result["status"] == "bad_input":
        problem = "The file is not a readable photo"
    elif result["status"] == "low_quality":
        problem = "Photo is " + " and ".join(p.replace("_", " ") for p in result["quality"]["problems"])
    elif result["confidence"] < MIN_CONFIDENCE:
        problem = f"Not sure what this is (confidence {result['confidence']:.0%})"
    if problem:
        if attempt < MAX_ATTEMPTS:
            _step(trace, "decision", "Retake needed", why=problem, attempt=attempt, max_attempts=MAX_ATTEMPTS)
            return _done(trace, "recapture", f"{problem}. Take the photo again, closer and in light.")
        _step(trace, "decision", "Retakes used up: hand to a person", why=problem, attempt=attempt)
        return _done(trace, "accept_unverified", f"{problem} after {attempt} photos; recorded as marked, points held")

    seen = result["verdict"]
    if marked is None:
        _step(trace, "decision", f"Camera says {seen}", confidence=result["confidence"])
        return _done(trace, "accept", f"Looks {seen}", segregation=seen)
    if seen == marked:
        _step(trace, "decision", f"Camera agrees: {seen}", confidence=result["confidence"])
        return _done(trace, "accept", f"Camera agrees: {seen}", segregation=seen)
    if marked == "mixed":
        _step(trace, "decision", "Collector marked mixed, camera saw separated: keep the safer mark",
              confidence=result["confidence"])
        return _done(trace, "accept", "Recorded as mixed (the collector's mark)", segregation="mixed")
    if result["confidence"] < DISAGREE_CONFIDENCE:
        _step(trace, "decision", "Camera disagrees but is not sure: trust the collector",
              confidence=result["confidence"], threshold=DISAGREE_CONFIDENCE)
        return _done(trace, "accept", "Recorded as separated; camera was unsure", segregation="separated")
    _step(trace, "decision", "Collector said separated, camera is sure it is mixed",
          confidence=result["confidence"], threshold=DISAGREE_CONFIDENCE)
    _step(trace, "action", "Proposed: hold the points and flag the pickup. Waiting for a person to approve")
    return _done(trace, "needs_approval", "Camera saw mixed waste; a reviewer will decide", segregation="separated")


def _done(trace: list, action: str, message: str, **extra) -> dict:
    return {"action": action, "message": message, "trace": trace, **extra}


def review(trace: list, *, approve: bool, reviewer: str, note: str | None = None) -> dict:
    """A person's decision on a needs_approval run, appended to its trace."""
    trace = list(trace)
    _step(trace, "human", ("Approved" if approve else "Rejected") + f" by {reviewer}", note=note)
    _step(trace, "action", "Pickup marked mixed, no points, collector flagged" if approve
          else "Pickup stays separated, points released")
    return {"trace": trace, "outcome": "mixed" if approve else "separated"}
