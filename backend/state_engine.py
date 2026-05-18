import copy
from typing import Dict, List

# Hyperparameters
LAMBDA_C = 0.25
MU_C = 0.08
LAMBDA_K = 0.30
MU_K = 0.06
LAMBDA_A = 0.15
LAMBDA_V = 0.20
LAMBDA_R = 0.12
LAMBDA_P = 0.18


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def encode_question(question_text: str, session: dict) -> dict:
    """
    Returns: {pressure, sensitivity, question_type, hit_topics}
    """
    text_lower = question_text.lower()

    # Pressure calculation
    high_pressure_markers = [
        "isn't it true", "you're lying", "how do you explain",
        "did you not", "you knew", "admit", "deny"
    ]
    medium_pressure_markers = ["why did you", "when did you", "who authorized"]
    low_pressure_markers = ["could you describe", "can you explain", "tell me about"]

    pressure = 0.1  # base
    for marker in high_pressure_markers:
        if marker in text_lower:
            pressure += 0.2
    for marker in medium_pressure_markers:
        if marker in text_lower:
            pressure += 0.1
    for marker in low_pressure_markers:
        if marker in text_lower:
            # low pressure overrides base
            pressure = max(pressure, 0.1)

    pressure = _clamp(pressure)

    # Question type
    if any(text_lower.startswith(m) for m in ["isn't it true", "would you agree", "isn't it fair to say"]):
        question_type = "leading"
    elif any(kw in text_lower for kw in ["if ", "suppose", "imagine", "what if"]):
        question_type = "hypothetical"
    elif (text_lower.rstrip().endswith("yes or no") or
          text_lower.rstrip().endswith("correct?") or
          text_lower.rstrip().endswith("right?") or
          len(question_text.split()) <= 8):
        question_type = "closed"
    else:
        question_type = "open"

    # Sensitivity via Jaccard token similarity
    memory = session.get("memory", {})
    question_tokens = set(question_text.lower().split())

    hit_topics = []
    for topic, topic_data in memory.items():
        topic_tokens = set(topic.lower().split())
        if not topic_tokens:
            continue
        intersection = question_tokens & topic_tokens
        union = question_tokens | topic_tokens
        similarity = len(intersection) / len(union) if union else 0.0
        if similarity > 0.15:
            sigma = topic_data.get("sigma", 0.5)
            hit_topics.append({
                "topic": topic,
                "similarity": similarity,
                "sigma": sigma,
                "weighted": similarity * sigma
            })

    hit_topics.sort(key=lambda x: x["similarity"], reverse=True)

    if hit_topics:
        sensitivity = _clamp(max(h["weighted"] for h in hit_topics))
    else:
        sensitivity = 0.0

    hit_topic_names = [h["topic"] for h in hit_topics]

    return {
        "pressure": round(pressure, 4),
        "sensitivity": round(sensitivity, 4),
        "question_type": question_type,
        "hit_topics": hit_topic_names
    }


def update_state(state: dict, state_0: dict, encoding: dict, turn: int) -> dict:
    """
    Apply the differential equations to update state.
    Return new state dict with keys C,K,A,V,R,P clamped to [0,1].
    """
    p = encoding["pressure"]
    s = encoding["sensitivity"]
    q = encoding["question_type"]
    t = turn

    xi = 0.5 * p + 0.3 * s + 0.2 * (1.0 if q == "leading" else 0.0)

    # Composure
    dC = -LAMBDA_C * xi * state["C"] + MU_C * (state_0["C"] - state["C"])
    C_new = _clamp(state["C"] + dC)

    # Knowledge / accuracy
    dK = -LAMBDA_K * s * (state["K"] - 0.1) + MU_K * (1 - p) * (state_0["K"] - state["K"])
    K_new = _clamp(state["K"] + dK)

    # Agreeableness
    sign_A = 1.0 if state["A"] > 0.5 else -1.0
    dA = -LAMBDA_A * p * sign_A * abs(state["A"] - 0.5) + 0.05 * (state_0["A"] - state["A"])
    A_new = _clamp(state["A"] + dA)

    # Verbosity
    dV = (LAMBDA_V * s * (1 - state["V"])
          - LAMBDA_V * (1.0 if q == "leading" else 0.0) * state["V"]
          + 0.05 * (state_0["V"] - state["V"]))
    V_new = _clamp(state["V"] + dV)

    # Rigidity
    dR = LAMBDA_R * p * (1 - state["R"]) - 0.03 * (state["R"] - state_0["R"])
    R_new = _clamp(state["R"] + dR)

    # Performance
    fatigue = min(1.0, t / 20.0)
    dP = -LAMBDA_P * p * state["P"] * fatigue + 0.04 * (state_0["P"] - state["P"])
    P_new = _clamp(state["P"] + dP)

    return {
        "C": round(C_new, 4),
        "K": round(K_new, 4),
        "A": round(A_new, 4),
        "V": round(V_new, 4),
        "R": round(R_new, 4),
        "P": round(P_new, 4)
    }


def update_memory(memory: dict, hit_topics: list, pressure: float, turn: int) -> dict:
    """
    Update recall quality (rho) for topics that were hit vs not hit.
    """
    mem = copy.deepcopy(memory)

    hit_set = set(hit_topics)

    for topic, data in mem.items():
        if topic in hit_set:
            delta = 0.25 * pressure
            mem[topic]["rho"] = max(0.1, data["rho"] - delta)
            mem[topic]["hit_count"] = data.get("hit_count", 0) + 1
            mem[topic]["last_hit_turn"] = turn
        else:
            mem[topic]["rho"] = min(1.0, data["rho"] + 0.02)

    return mem


_DIM_FULL_NAMES = {
    "C": "Composure", "K": "Knowledge", "A": "Agreeableness",
    "V": "Verbosity", "R": "Rigidity", "P": "Performance"
}


def detect_events(new_state: dict, prev_state: dict, encoding: dict, question_text: str) -> list:
    """Detect notable behavioral events this turn for UI display."""
    p = encoding["pressure"]
    q_type = encoding["question_type"]
    C = new_state["C"]
    A = new_state["A"]
    R = new_state["R"]
    V = new_state["V"]
    delta_C = C - prev_state["C"]

    events = []

    # Witness rattled / intimidated
    if p > 0.58 and (C < 0.38 or delta_C < -0.05):
        events.append({
            "type": "intimidation",
            "label": "WITNESS RATTLED",
            "detail": f"pressure {p:.2f} · composure {C:.2f}"
        })

    # Witness combative / hostile
    if A < 0.28 and R > 0.60:
        events.append({
            "type": "combative",
            "label": "WITNESS COMBATIVE",
            "detail": f"agreeableness {A:.2f} · rigidity {R:.2f}"
        })

    # Attorney interrupts (short + high-pressure closed/leading)
    words = len(question_text.split())
    if p > 0.45 and words <= 8 and q_type in ("closed", "leading"):
        events.append({
            "type": "attorney_interrupts",
            "label": "ATTORNEY INTERRUPTS",
            "detail": f"{words}-word {q_type} at pressure {p:.2f}"
        })

    # Witness talks over / pushes through
    if R > 0.72 and V > 0.58 and p > 0.35:
        events.append({
            "type": "witness_interrupts",
            "label": "WITNESS TALKS OVER",
            "detail": f"rigidity {R:.2f} · verbosity {V:.2f}"
        })

    # Significant personality shift
    shifts = []
    for dim in ["C", "K", "A", "V", "R", "P"]:
        d = new_state[dim] - prev_state[dim]
        if abs(d) >= 0.06:
            arrow = "▲" if d > 0 else "▼"
            shifts.append(f"{_DIM_FULL_NAMES[dim]} {arrow}{abs(d):.2f}")
    if shifts:
        events.append({
            "type": "personality_shift",
            "label": "PERSONALITY SHIFT",
            "detail": " · ".join(shifts)
        })

    return events


def compute_scores(state: dict) -> dict:
    """
    Compute derived behavioral scores from state.
    """
    C = state["C"]
    K = state["K"]
    A = state["A"]
    V = state["V"]
    R = state["R"]
    P = state["P"]

    consistency = 0.5 * K + 0.4 * R - 0.1 * (1 - K) * (1 - R)
    evasion = 0.5 * (1 - K) + 0.3 * abs(V - 0.5) * 2 + 0.2 * P
    realism_raw = 1.0 - 0.3 * (abs(C - 0.5) * 2) - 0.3 * (abs(K - 0.5) * 2) - 0.4 * (max(0, P - 0.8) * 5)
    realism = max(0, realism_raw)
    adversarial = 0.4 * (1 - K) + 0.3 * (1 - A) + 0.2 * R + 0.1 * (1 - C)

    return {
        "consistency": round(consistency, 3),
        "evasion": round(evasion, 3),
        "realism": round(realism, 3),
        "adversarial": round(adversarial, 3)
    }
